import pytest
from app.models.campaign import CampaignStatus
from app.repositories.campaign_repository import CampaignRepository
from app.services.campaigns.cycle_engine import CampaignCycleEngine


@pytest.mark.asyncio
async def test_campaign_cycle_engine_not_activated_fails():
    fake_docs = []

    class MockCollection:
        async def find_one(self, query):
            for d in fake_docs:
                if all(d.get(k) == v for k, v in query.items()):
                    return dict(d)
            return None

    class MockDB(dict):
        def __getitem__(self, item):
            if item not in self:
                self[item] = MockCollection()
            return super().__getitem__(item)

    db = MockDB()
    c_repo = CampaignRepository(db=db)
    engine = CampaignCycleEngine(campaign_repo=c_repo)

    import pandas as pd
    res = await engine.execute_cycle("non_existent_camp", "2026-01-01", pd.DataFrame(), {})
    assert res.status.value == "failed"
