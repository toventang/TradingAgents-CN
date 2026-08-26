import pytest
from app.models.campaign import Campaign, CampaignStatus, ExitReasonCode
from app.repositories.campaign_repository import CampaignRepository
from app.services.campaigns.risk_exit import CampaignRiskExitService


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
async def test_campaign_risk_exit_stop_loss_and_take_profit():
    db = FakeDB()
    c_repo = CampaignRepository(db=db)
    service = CampaignRiskExitService(campaign_repo=c_repo)

    camp = Campaign(
        campaign_id="c_exit_1",
        user_id="u_exit",
        name="Exit Campaign",
        status=CampaignStatus.ACTIVATED,
        strategy_id="s1",
        strategy_version_num=1,
        portfolio_id="p1",
        initial_allocation_cash=100000.0,
        start_date="2026-01-01"
    )
    await c_repo.update_campaign("c_exit_1", camp.model_dump())
    c_repo.get_db()["campaigns"].docs.append(camp.model_dump())

    positions = {
        "600000.SH": {"quantity": 1000, "buy_price": 10.0, "current_price": 8.5},  # -15% -> Stop Loss
        "000001.SZ": {"quantity": 1000, "buy_price": 10.0, "current_price": 12.5}  # +25% -> Take Profit
    }

    res = await service.evaluate_risk_exits(
        campaign_id="c_exit_1",
        positions=positions,
        stop_loss_pct=0.10,
        take_profit_pct=0.20
    )

    assert res.has_risk_exit is True
    assert len(res.triggers) == 2

    # Check reason codes
    stop_loss_trig = next(t for t in res.triggers if t.symbol == "600000.SH")
    assert stop_loss_trig.reason_code == ExitReasonCode.STOP_LOSS_TRIGGERED

    take_profit_trig = next(t for t in res.triggers if t.symbol == "000001.SZ")
    assert take_profit_trig.reason_code == ExitReasonCode.TAKE_PROFIT_TRIGGERED


@pytest.mark.asyncio
async def test_campaign_resume_flow():
    db = FakeDB()
    c_repo = CampaignRepository(db=db)
    service = CampaignRiskExitService(campaign_repo=c_repo)

    camp = Campaign(
        campaign_id="c_resume_1",
        user_id="u_resume",
        name="Resume Campaign",
        status=CampaignStatus.PAUSED,
        strategy_id="s1",
        strategy_version_num=1,
        portfolio_id="p1",
        initial_allocation_cash=100000.0,
        start_date="2026-01-01"
    )
    await c_repo.update_campaign("c_resume_1", camp.model_dump())
    c_repo.get_db()["campaigns"].docs.append(camp.model_dump())

    resumed = await service.resume_campaign("c_resume_1", "u_resume", "Owner confirmed risk clear")
    assert resumed.status == CampaignStatus.ACTIVATED
