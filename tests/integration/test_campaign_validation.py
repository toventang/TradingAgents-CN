import pytest
from app.models.campaign import CampaignStatus
from app.repositories.campaign_repository import CampaignRepository
from app.services.campaigns.lifecycle_service import CampaignLifecycleService


@pytest.mark.asyncio
async def test_campaign_lifecycle_owner_isolation():
    fake_docs = []

    class MockCollection:
        async def insert_one(self, doc):
            fake_docs.append(dict(doc))
            return True

        async def find_one(self, query):
            for d in fake_docs:
                if all(d.get(k) == v for k, v in query.items()):
                    return dict(d)
            return None

    class MockDB(dict):
        def __getitem__(self, item):
            if item not in self:
                self[item] = MockCollection([])
            return super().__getitem__(item)

    db = MockDB()
    c_repo = CampaignRepository(db=db)
    service = CampaignLifecycleService(campaign_repo=c_repo)

    camp, rev = await service.create_campaign_draft(
        user_id="owner_user",
        name="Isolated Campaign",
        strategy_id="s1",
        strategy_version_num=1,
        portfolio_id="p1",
        initial_allocation_cash=100000.0,
        start_date="2026-12-31"
    )

    # Attempt activation by non-owner -> invalid
    val = await service.validate_activation(camp.campaign_id, "other_user")
    assert val.is_valid is False
    assert "Forbidden" in val.errors[0]
