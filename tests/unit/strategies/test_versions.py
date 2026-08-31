from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from app.models.strategy import (
    FrozenFactorDependency,
    FrozenSkillDependency,
    StrategyKind,
    StrategyValidationResult,
    StrategyVersionStatus,
    StrategyVisibility,
)
from app.models.symbol import Market
from app.repositories.strategy_repository import StrategyConflict, StrategyRepository
from app.services.strategies.version_service import (
    StrategyLifecycleError,
    StrategyNotFound,
    StrategyPermissionDenied,
    StrategyVersionService,
)
from tests.strategy_fakes import FakeDatabase


pytestmark = pytest.mark.asyncio


NOW = datetime(2025, 6, 3, 8, 30, tzinfo=timezone.utc)


def valid_result() -> StrategyValidationResult:
    return StrategyValidationResult(valid=True, validated_at=NOW)


def service(database: FakeDatabase) -> StrategyVersionService:
    counter = iter(f"id-{number}" for number in range(1, 100))
    return StrategyVersionService(
        StrategyRepository(database),
        clock=lambda: NOW,
        id_factory=lambda: next(counter),
    )


async def create_draft(version_service: StrategyVersionService, *, user_id="alice"):
    return await version_service.create_strategy(
        user_id=user_id,
        name="Quality rotation",
        description="Deterministic portfolio strategy",
        tags=("quality", "monthly"),
        kind=StrategyKind.PORTFOLIO,
        market=Market.CN,
        definition={"universe": {"market": "CN"}, "ranking": [{"factor": "quality"}]},
    )


async def test_validation_publish_freezes_dependencies_and_published_version_is_immutable():
    database = FakeDatabase()
    version_service = service(database)
    strategy, draft = await create_draft(version_service)

    validating = await version_service.begin_validation(
        strategy_id=strategy.strategy_id,
        user_id="alice",
        expected_checksum=draft.checksum,
    )
    assert validating.status == StrategyVersionStatus.VALIDATING
    validated = await version_service.complete_validation(
        strategy_version_id=draft.strategy_version_id,
        user_id="alice",
        validation_result=valid_result(),
        expected_checksum=validating.checksum,
    )
    assert validated.status == StrategyVersionStatus.DRAFT
    assert validated.validation_result and validated.validation_result.valid

    published = await version_service.publish_draft(
        strategy_id=strategy.strategy_id,
        user_id="alice",
        factor_dependencies=(
            FrozenFactorDependency(factor_id="quality", version=3, checksum="a" * 64),
        ),
        skill_dependencies=(
            FrozenSkillDependency(skill_id="risk-review", version=2, checksum="b" * 64),
        ),
    )
    assert published.status == StrategyVersionStatus.PUBLISHED
    assert published.published_at == NOW
    assert [(item.factor_id, item.version) for item in published.factor_dependencies] == [
        ("quality", 3)
    ]
    assert [(item.skill_id, item.version) for item in published.skill_dependencies] == [
        ("risk-review", 2)
    ]

    header = await version_service.repository.get_strategy(
        strategy.strategy_id, user_id="alice", include_readonly=False
    )
    assert header is not None
    assert header.current_draft_version_id is None
    assert header.latest_published_version_id == published.strategy_version_id

    with pytest.raises(StrategyLifecycleError, match="no current draft"):
        await version_service.update_draft(
            strategy_id=strategy.strategy_id,
            user_id="alice",
            definition={"changed": True},
            expected_checksum=published.checksum,
        )

    forged_draft = published.model_dump(mode="json", exclude={"checksum"})
    forged_draft.update({"status": "draft", "published_at": None, "validation_result": None})
    from app.models.strategy import StrategyVersion

    with pytest.raises(StrategyConflict):
        await version_service.repository.replace_draft(
            StrategyVersion.model_validate(forged_draft),
            expected_checksum=published.checksum,
        )

    archived = await version_service.archive_strategy(
        strategy.strategy_id, user_id="alice"
    )
    assert archived.archived_at == NOW
    assert (
        await version_service.repository.get_strategy(
            strategy.strategy_id, user_id="alice"
        )
        is None
    )
    assert (
        await version_service.repository.get_strategy(
            strategy.strategy_id,
            user_id="alice",
            include_archived=True,
            include_readonly=False,
        )
        == archived
    )


async def test_concurrent_next_version_creation_has_one_atomic_winner():
    database = FakeDatabase()
    version_service = service(database)
    strategy, draft = await create_draft(version_service)
    await version_service.publish_draft(
        strategy_id=strategy.strategy_id,
        user_id="alice",
        validation_result=valid_result(),
    )

    outcomes = await asyncio.gather(
        version_service.create_next_draft(
            strategy_id=strategy.strategy_id,
            user_id="alice",
            change_summary="candidate A",
        ),
        version_service.create_next_draft(
            strategy_id=strategy.strategy_id,
            user_id="alice",
            change_summary="candidate B",
        ),
        return_exceptions=True,
    )

    winners = [item for item in outcomes if not isinstance(item, Exception)]
    conflicts = [item for item in outcomes if isinstance(item, Exception)]
    assert len(winners) == 1
    assert winners[0].version == 2
    assert winners[0].parent_version_id == draft.strategy_version_id
    assert len(conflicts) == 1
    assert isinstance(conflicts[0], (StrategyConflict, StrategyLifecycleError))
    versions = await version_service.repository.list_versions(
        strategy.strategy_id, user_id="alice"
    )
    assert [item.version for item in versions] == [1, 2]


async def test_owner_isolation_system_template_readonly_and_clone_provenance():
    database = FakeDatabase()
    version_service = service(database)
    private_strategy, private_draft = await create_draft(version_service)

    assert (
        await version_service.repository.get_strategy(
            private_strategy.strategy_id, user_id="bob"
        )
        is None
    )
    assert (
        await version_service.repository.get_version(
            private_draft.strategy_version_id, user_id="bob"
        )
        is None
    )
    with pytest.raises(StrategyNotFound):
        await version_service.update_draft(
            strategy_id=private_strategy.strategy_id,
            user_id="bob",
            definition={"stolen": True},
            expected_checksum=private_draft.checksum,
        )

    template, template_version = await version_service.create_system_template(
        name="System quality",
        description="Read-only seed",
        tags=("system",),
        kind=StrategyKind.RANKING,
        market=Market.US,
        definition={"ranking": [{"factor": "quality"}]},
        validation_result=valid_result(),
    )
    assert template.visibility == StrategyVisibility.SYSTEM
    assert template_version.status == StrategyVersionStatus.PUBLISHED
    assert (
        await version_service.repository.get_strategy(
            template.strategy_id, user_id="bob"
        )
        == template
    )

    with pytest.raises(StrategyPermissionDenied):
        await version_service.archive_strategy(template.strategy_id, user_id="system")

    clone, clone_draft = await version_service.clone_strategy(
        source_strategy_id=template.strategy_id,
        source_strategy_version_id=template_version.strategy_version_id,
        user_id="bob",
        name="My quality clone",
    )
    assert clone.user_id == "bob"
    assert clone.visibility == StrategyVisibility.PRIVATE
    assert clone.clone_source is not None
    assert clone.clone_source.strategy_version_id == template_version.strategy_version_id
    assert clone.clone_source.checksum == template_version.checksum
    assert clone_draft.definition == template_version.definition
    assert clone_draft.strategy_id != template_version.strategy_id
