import pytest
from app.services.factors.registry import FactorRegistry, global_factor_registry
from app.repositories.factor_repository import FactorRepository
from tests.integration.test_domain_task_repository import FakeDatabase

def test_registry_lookup():
    ret_1d = global_factor_registry.get_by_id("ret_1d")
    assert ret_1d is not None
    assert ret_1d.name == "1日收益率"

    cn_factors = global_factor_registry.get_by_market("CN")
    assert len(cn_factors) == 171

def test_duplicate_id_rejection():
    from app.models.factor import FactorDefinition, FactorCategory
    f1 = FactorDefinition(factor_id="dup_f", name="F1", category=FactorCategory.PRICE, description="d1")
    f2 = FactorDefinition(factor_id="dup_f", name="F2", category=FactorCategory.PRICE, description="d2")

    with pytest.raises(ValueError, match="Duplicate factor_id"):
        FactorRegistry([f1, f2])

@pytest.mark.asyncio
async def test_factor_repository_idempotent_sync():
    db = FakeDatabase()
    repo = FactorRepository(db=db)

    synced_1 = await repo.sync_definitions()
    assert synced_1 == 171

    # Second sync -> no changes needed, returns 0
    synced_2 = await repo.sync_definitions()
    assert synced_2 == 0
