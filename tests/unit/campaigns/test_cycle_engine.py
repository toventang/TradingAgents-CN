import pytest
import pandas as pd
from app.models.campaign import Campaign, CampaignStatus, CampaignCycleStatus
from app.models.strategy import StrategyVersion, UniverseSnapshot
from app.models.paper import PaperPortfolio
from app.repositories.campaign_repository import CampaignRepository
from app.repositories.strategy_repository import StrategyRepository
from app.repositories.paper_repository import PaperRepository
from app.services.campaigns.cycle_engine import CampaignCycleEngine


class FakeCollection:
    def __init__(self):
        self.docs = []

    async def insert_one(self, doc):
        self.docs.append(dict(doc))
        return True

    async def find_one(self, query):
        for d in self.docs:
            if all(d.get(k) == v for k, v in query.items()):
                return dict(d)
        return None

    def find(self, query):
        filtered = [dict(d) for d in self.docs if all(d.get(k) == v for k, v in query.items())]

        class Cursor:
            def __init__(self, items):
                self.items = items

            def sort(self, k, d=1):
                self.items.sort(key=lambda x: x.get(k, 0), reverse=(d == -1))
                return self

            def limit(self, n):
                self.items = self.items[:n]
                return self

            def __aiter__(self):
                return self._gen()

            async def _gen(self):
                for item in self.items:
                    yield item

        return Cursor(filtered)

    async def find_one_and_update(self, query, update, return_document=True):
        doc = await self.find_one(query)
        if not doc:
            return None
        if "$inc" in update:
            for k, v in update["$inc"].items():
                doc[k] = doc.get(k, 0.0) + v
        if "$set" in update:
            for k, v in update["$set"].items():
                doc[k] = v
        return doc

    async def update_one(self, query, update, upsert=False):
        doc = await self.find_one(query)
        if not doc:
            if upsert:
                new_doc = {}
                if "$set" in update:
                    new_doc.update(update["$set"])
                self.docs.append(new_doc)
                return True
            return False
        if "$set" in update:
            for k, v in update["$set"].items():
                doc[k] = v
        return True


class FakeDB(dict):
    def __getitem__(self, item):
        if item not in self:
            self[item] = FakeCollection()
        return super().__getitem__(item)


@pytest.mark.asyncio
async def test_campaign_cycle_execution_flow():
    db = FakeDB()
    c_repo = CampaignRepository(db=db)
    s_repo = StrategyRepository(db=db)
    p_repo = PaperRepository(db=db)
    engine = CampaignCycleEngine(campaign_repo=c_repo, strategy_repo=s_repo, paper_repo=p_repo)

    # 1. Setup activated campaign
    camp = Campaign(
        campaign_id="camp_active_1",
        user_id="u_cycle",
        name="Active Campaign",
        status=CampaignStatus.ACTIVATED,
        strategy_id="strat_c1",
        strategy_version_num=1,
        portfolio_id="p_c1",
        initial_allocation_cash=100000.0,
        start_date="2026-01-01"
    )
    await c_repo.update_campaign("camp_active_1", camp.model_dump())
    c_repo.get_db()["campaigns"].docs.append(camp.model_dump())

    # Strategy version
    univ = UniverseSnapshot(universe_id="u1", user_id="u_cycle", symbols=["600000.SH", "000001.SZ"])
    ver = StrategyVersion(
        version_id="v_c1",
        strategy_id="strat_c1",
        version_num=1,
        is_published=True,
        parameters={"weights": {"ret_1d": 1.0}},
        rules={"conditions": {"op": ">", "factor_id": "ret_1d", "value": 0.0}, "top_k": 1},
        universe=univ
    )
    await s_repo.save_version(ver)

    # Portfolio
    port = PaperPortfolio(portfolio_id="p_c1", user_id="u_cycle", cash=100000.0, total_equity=100000.0)
    await p_repo.create_portfolio(port)

    factors_df = pd.DataFrame({"ret_1d": [0.05, 0.01]}, index=["600000.SH", "000001.SZ"])
    current_prices = {"600000.SH": 10.0, "000001.SZ": 15.0}

    rec = await engine.execute_cycle(
        campaign_id="camp_active_1",
        cycle_date="2026-01-02",
        factor_values_df=factors_df,
        current_prices=current_prices
    )

    assert rec.status == CampaignCycleStatus.COMPLETED
    assert rec.candidates_count == 2
    assert rec.orders_count == 1
