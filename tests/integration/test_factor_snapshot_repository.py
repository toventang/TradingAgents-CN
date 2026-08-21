import pytest
from app.repositories.factor_repository import FactorRepository
from tests.integration.test_domain_task_repository import FakeDatabase

@pytest.mark.asyncio
async def test_factor_snapshot_persistence():
    db = FakeDatabase()
    repo = FactorRepository(db=db)

    snap = await repo.save_snapshot(
        snapshot_id="snap_123",
        user_id="user_a",
        market="CN",
        factor_ids=["ret_1d", "sma_5"],
        data={"000001": {"ret_1d": [0.01, 0.02]}},
        checksum="hash123",
        status="ready"
    )

    assert snap["snapshot_id"] == "snap_123"

    fetched = await repo.get_snapshot("snap_123", user_id="user_a")
    assert fetched is not None
    assert fetched["checksum"] == "hash123"

    # Cross user access returns None
    fetched_b = await repo.get_snapshot("snap_123", user_id="user_b")
    assert fetched_b is None
