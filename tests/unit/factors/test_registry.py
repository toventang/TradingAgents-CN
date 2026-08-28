from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.models.factor import (
    FactorCategory,
    FactorDefinition,
    FactorStatus,
    ParameterSpec,
    ParameterType,
)
from app.repositories.factor_repository import (
    FactorDefinitionMirrorConflict,
    FactorRepository,
)
from app.services.factors.registry import FactorRegistry, global_factor_registry


def _factor(factor_id, *, dependencies=(), output_column=None, description="fixture", **extra):
    values = dict(
        factor_id=factor_id,
        name=factor_id,
        description=description,
        category=FactorCategory.PRICE,
        dependencies=dependencies,
    )
    if output_column is not None:
        values["output_column"] = output_column
    values.update(extra)
    return FactorDefinition(**values)


def test_registry_queries_and_dependency_order():
    assert global_factor_registry.count == 171
    assert global_factor_registry.get_by_id("ret_1d").name == "1日收益率"
    assert len(global_factor_registry.get_by_market("CN")) == 171
    assert len(global_factor_registry.get_by_status(FactorStatus.ACTIVE)) == 171
    assert len(global_factor_registry.get_by_category(FactorCategory.TREND)) == 23

    order = [item.factor_id for item in global_factor_registry.dependency_order(["value_composite"])]
    assert order[-1] == "value_composite"
    assert order.index("pe_ttm") < order.index("earnings_yield") < order.index("value_composite")
    assert len(global_factor_registry.catalog_checksum) == 64


def test_registry_rejects_duplicates_unknown_dependencies_cycles_and_outputs():
    with pytest.raises(ValueError, match="Duplicate factor_id"):
        FactorRegistry([_factor("duplicate"), _factor("duplicate")])
    with pytest.raises(ValueError, match="Unknown dependencies"):
        FactorRegistry([_factor("derived", dependencies=("missing",))])
    with pytest.raises(ValueError, match="Dependency cycle"):
        FactorRegistry([
            _factor("cycle_a", dependencies=("cycle_b",)),
            _factor("cycle_b", dependencies=("cycle_a",)),
        ])
    with pytest.raises(ValueError, match="Output collision"):
        FactorRegistry([
            _factor("output_a", output_column="shared_output"),
            _factor("output_b", output_column="shared_output"),
        ])


def test_definition_rejects_invalid_versions_checksums_and_parameter_defaults():
    with pytest.raises(ValidationError):
        _factor("bad_version", version=0)
    with pytest.raises(ValidationError):
        _factor("bad_version", version="1")
    with pytest.raises(ValidationError, match="illegal parameter defaults"):
        _factor(
            "bad_default",
            params_schema={
                "window": ParameterSpec(type=ParameterType.INTEGER, minimum=2, maximum=10)
            },
            default_params={"window": 1},
        )
    with pytest.raises(ValidationError, match="checksum does not match"):
        _factor("bad_checksum", checksum="0" * 64)


class FakeCollection:
    def __init__(self):
        self.documents = []
        self.indexes = []

    async def create_index(self, keys, **options):
        self.indexes.append((tuple(keys), options))

    async def find_one(self, query, sort=None):
        matches = [item for item in self.documents if all(item.get(k) == v for k, v in query.items())]
        if sort:
            for key, direction in reversed(sort):
                matches.sort(key=lambda item: item.get(key), reverse=direction < 0)
        return deepcopy(matches[0]) if matches else None

    async def update_one(self, query, update, upsert=False):
        existing = await self.find_one(query)
        if existing is None and upsert:
            document = deepcopy(query)
            document.update(deepcopy(update.get("$setOnInsert", {})))
            self.documents.append(document)


class FakeDatabase:
    def __init__(self):
        self.collection = FakeCollection()

    def __getitem__(self, name):
        assert name == "factor_definitions"
        return self.collection


@pytest.mark.asyncio
async def test_definition_mirror_is_idempotent_metadata_only_and_immutable():
    db = FakeDatabase()
    registry = FactorRegistry([_factor("mirror_factor")])
    repository = FactorRepository(db=db, registry=registry)
    assert await repository.sync_definitions() == 1
    assert await repository.sync_definitions() == 0
    document = db.collection.documents[0]
    assert document["factor_id"] == "mirror_factor"
    assert document["checksum"] == registry.require("mirror_factor").checksum
    assert "code" not in document and "callable" not in document
    assert document["formula_ref"] == "builtin.mirror_factor"

    changed = FactorRegistry([_factor("mirror_factor", description="changed without version bump")])
    with pytest.raises(FactorDefinitionMirrorConflict, match="immutable"):
        await FactorRepository(db=db, registry=changed).sync_definitions()


@pytest.mark.asyncio
async def test_full_active_catalog_mirrors_exactly_once():
    db = FakeDatabase()
    repository = FactorRepository(db=db)
    assert await repository.sync_definitions() == 171
    assert await repository.sync_definitions() == 0
    assert len(db.collection.documents) == 171
    assert len({(item["factor_id"], item["version"]) for item in db.collection.documents}) == 171
