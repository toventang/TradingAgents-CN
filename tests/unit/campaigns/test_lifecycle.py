import pytest
from app.models.campaign import CampaignStatus
from app.models.strategy import Strategy, StrategyVersion, StrategyStatus
from app.models.paper import PaperPortfolio
from app.repositories.campaign_repository import CampaignRepository
from app.repositories.strategy_repository import StrategyRepository
from app.repositories.paper_repository import PaperRepository
from app.services.campaigns.lifecycle_service import CampaignLifecycleService, CampaignLifecycleError
from app.utils.timezone import now_tz


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
        if "$set" in update:
            for k, v in update["$set"].items():
                doc[k] = v
        return doc


class FakeDB(dict):
    def __getitem__(self, item):
        if item not in self:
            self[item] = FakeCollection()
        return super().__getitem__(item)


@pytest.mark.asyncio
async def test_campaign_activation_validation():
    db = FakeDB()
    c_repo = CampaignRepository(db=db)
    s_repo = StrategyRepository(db=db)
    p_repo = PaperRepository(db=db)
    service = CampaignLifecycleService(campaign_repo=c_repo, strategy_repo=s_repo, paper_repo=p_repo)

    # 1. Setup published strategy & portfolio
    now = now_tz()
    today_str = now.strftime("%Y-%m-%d")

    strat = Strategy(strategy_id="strat_camp", user_id="u_camp", name="Camp Strategy", status=StrategyStatus.PUBLISHED)
    ver = StrategyVersion(version_id="v_camp_1", strategy_id="strat_camp", version_num=1, is_published=True)
    await s_repo.create_strategy(strat)
    await s_repo.save_version(ver)

    port = PaperPortfolio(portfolio_id="p_camp", user_id="u_camp", cash=1000000.0, total_equity=1000000.0)
    await p_repo.create_portfolio(port)

    # 2. Create Campaign Draft with valid future start date
    camp, rev = await service.create_campaign_draft(
        user_id="u_camp",
        name="Campaign Alpha",
        strategy_id="strat_camp",
        strategy_version_num=1,
        portfolio_id="p_camp",
        initial_allocation_cash=500000.0,
        start_date=today_str
    )

    # 3. Validate activation -> Valid
    val = await service.validate_activation(camp.campaign_id, "u_camp")
    assert val.is_valid is True

    # 4. Activate Campaign
    activated = await service.activate_campaign(camp.campaign_id, "u_camp")
    assert activated.status == CampaignStatus.ACTIVATED


@pytest.mark.asyncio
async def test_campaign_activation_retroactive_prohibited():
    db = FakeDB()
    c_repo = CampaignRepository(db=db)
    s_repo = StrategyRepository(db=db)
    p_repo = PaperRepository(db=db)
    service = CampaignLifecycleService(campaign_repo=c_repo, strategy_repo=s_repo, paper_repo=p_repo)

    # Retroactive start_date="2020-01-01"
    camp, rev = await service.create_campaign_draft(
        user_id="u_camp",
        name="Retro Campaign",
        strategy_id="strat_camp",
        strategy_version_num=1,
        portfolio_id="p_camp",
        initial_allocation_cash=500000.0,
        start_date="2020-01-01"
    )

    val = await service.validate_activation(camp.campaign_id, "u_camp")
    assert val.is_valid is False
    assert any("Retroactive start date" in e for e in val.errors)
