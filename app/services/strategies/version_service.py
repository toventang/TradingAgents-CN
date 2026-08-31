"""Lifecycle orchestration for immutable strategy versions."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from copy import deepcopy
from datetime import datetime
from typing import Any

from app.models.strategy import (
    SYSTEM_USER_ID,
    FrozenFactorDependency,
    FrozenSkillDependency,
    Strategy,
    StrategyCloneSource,
    StrategyKind,
    StrategyValidationResult,
    StrategyVersion,
    StrategyVersionStatus,
    StrategyVisibility,
    new_identifier,
    utc_now,
)
from app.models.symbol import Market
from app.repositories.strategy_repository import (
    StrategyConflict,
    StrategyNotFound,
    StrategyRepository,
)


class StrategyPermissionDenied(PermissionError):
    """The requested mutation targets a read-only or foreign strategy."""


class StrategyLifecycleError(StrategyConflict):
    """A requested lifecycle transition is not legal from current state."""


class StrategyVersionService:
    def __init__(
        self,
        repository: StrategyRepository,
        *,
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[], str] = new_identifier,
    ):
        self.repository = repository
        self._clock = clock
        self._id_factory = id_factory

    async def create_strategy(
        self,
        *,
        user_id: str,
        name: str,
        description: str,
        tags: Sequence[str],
        kind: StrategyKind,
        market: Market,
        definition: dict[str, Any],
        analysis_profile_version_id: str | None = None,
        change_summary: str = "Initial draft",
        visibility: StrategyVisibility = StrategyVisibility.PRIVATE,
    ) -> tuple[Strategy, StrategyVersion]:
        if user_id == SYSTEM_USER_ID or visibility == StrategyVisibility.SYSTEM:
            raise StrategyPermissionDenied("system templates require the internal template method")
        return await self._create_initial(
            user_id=user_id,
            name=name,
            description=description,
            tags=tags,
            kind=kind,
            market=market,
            definition=definition,
            analysis_profile_version_id=analysis_profile_version_id,
            change_summary=change_summary,
            visibility=visibility,
            clone_source=None,
        )

    async def create_system_template(
        self,
        *,
        name: str,
        description: str,
        tags: Sequence[str],
        kind: StrategyKind,
        market: Market,
        definition: dict[str, Any],
        validation_result: StrategyValidationResult,
        factor_dependencies: Sequence[FrozenFactorDependency] = (),
        skill_dependencies: Sequence[FrozenSkillDependency] = (),
        analysis_profile_version_id: str | None = None,
        change_summary: str = "Initial system template",
    ) -> tuple[Strategy, StrategyVersion]:
        """Internal seeding path; returned template is published and read-only."""

        if not validation_result.valid:
            raise StrategyLifecycleError("a system template requires successful validation")
        strategy, draft = await self._create_initial(
            user_id=SYSTEM_USER_ID,
            name=name,
            description=description,
            tags=tags,
            kind=kind,
            market=market,
            definition=definition,
            analysis_profile_version_id=analysis_profile_version_id,
            change_summary=change_summary,
            visibility=StrategyVisibility.SYSTEM,
            clone_source=None,
        )
        published = await self._publish_draft(
            strategy=strategy,
            draft=draft,
            validation_result=validation_result,
            factor_dependencies=factor_dependencies,
            skill_dependencies=skill_dependencies,
            allow_system=True,
        )
        refreshed = await self.repository.get_strategy(
            strategy.strategy_id,
            user_id=SYSTEM_USER_ID,
            include_readonly=False,
        )
        assert refreshed is not None
        return refreshed, published

    async def clone_strategy(
        self,
        *,
        source_strategy_id: str,
        source_strategy_version_id: str,
        user_id: str,
        name: str,
        description: str | None = None,
        tags: Sequence[str] | None = None,
    ) -> tuple[Strategy, StrategyVersion]:
        if user_id == SYSTEM_USER_ID:
            raise StrategyPermissionDenied("users must own cloned strategies")
        source_strategy = await self.repository.get_strategy(
            source_strategy_id, user_id=user_id, include_readonly=True
        )
        if source_strategy is None:
            raise StrategyNotFound("source strategy not found")
        source_version = await self.repository.get_version(
            source_strategy_version_id,
            user_id=source_strategy.user_id,
            include_system=True,
        )
        if (
            source_version is None
            or source_version.strategy_id != source_strategy.strategy_id
            or source_version.status
            not in {StrategyVersionStatus.PUBLISHED, StrategyVersionStatus.DEPRECATED}
        ):
            raise StrategyNotFound("source published strategy version not found")
        clone_source = StrategyCloneSource(
            strategy_id=source_strategy.strategy_id,
            strategy_version_id=source_version.strategy_version_id,
            version=source_version.version,
            checksum=source_version.checksum,
        )
        return await self._create_initial(
            user_id=user_id,
            name=name,
            description=(
                source_strategy.description if description is None else description
            ),
            tags=source_strategy.tags if tags is None else tags,
            kind=source_strategy.kind,
            market=source_version.market,
            definition=deepcopy(source_version.definition),
            analysis_profile_version_id=source_version.analysis_profile_version_id,
            change_summary=f"Cloned from {source_strategy.strategy_id} v{source_version.version}",
            visibility=StrategyVisibility.PRIVATE,
            clone_source=clone_source,
            factor_dependencies=source_version.factor_dependencies,
            skill_dependencies=source_version.skill_dependencies,
        )

    async def update_draft(
        self,
        *,
        strategy_id: str,
        user_id: str,
        definition: dict[str, Any],
        expected_checksum: str,
        analysis_profile_version_id: str | None = None,
        change_summary: str | None = None,
    ) -> StrategyVersion:
        strategy, draft = await self._owned_current_draft(strategy_id, user_id=user_id)
        if draft.checksum != expected_checksum:
            raise StrategyConflict("draft checksum changed concurrently")
        payload = draft.model_dump(mode="json", exclude={"checksum"})
        payload.update(
            {
                "definition": deepcopy(definition),
                "analysis_profile_version_id": analysis_profile_version_id,
                "validation_result": None,
            }
        )
        if change_summary is not None:
            payload["change_summary"] = change_summary
        replacement = StrategyVersion.model_validate(payload)
        if strategy.current_draft_version_id != replacement.strategy_version_id:
            raise StrategyLifecycleError("strategy draft pointer changed concurrently")
        return await self.repository.replace_draft(
            replacement, expected_checksum=expected_checksum
        )

    async def begin_validation(
        self,
        *,
        strategy_id: str,
        user_id: str,
        expected_checksum: str,
    ) -> StrategyVersion:
        _, draft = await self._owned_current_draft(strategy_id, user_id=user_id)
        if draft.checksum != expected_checksum:
            raise StrategyConflict("draft checksum changed concurrently")
        replacement = StrategyVersion.model_validate(
            {
                **draft.model_dump(mode="json", exclude={"checksum"}),
                "status": StrategyVersionStatus.VALIDATING.value,
                "validation_result": None,
            }
        )
        return await self.repository.transition_validation_state(
            replacement,
            expected_status=StrategyVersionStatus.DRAFT,
            expected_checksum=expected_checksum,
        )

    async def complete_validation(
        self,
        *,
        strategy_version_id: str,
        user_id: str,
        validation_result: StrategyValidationResult,
        expected_checksum: str,
    ) -> StrategyVersion:
        version = await self.repository.get_owned_version(
            strategy_version_id, user_id=user_id
        )
        if version is None:
            raise StrategyNotFound("strategy version not found")
        if version.status != StrategyVersionStatus.VALIDATING:
            raise StrategyLifecycleError("only a validating version can complete validation")
        if version.checksum != expected_checksum:
            raise StrategyConflict("strategy version checksum changed concurrently")
        replacement = StrategyVersion.model_validate(
            {
                **version.model_dump(mode="json", exclude={"checksum"}),
                "status": StrategyVersionStatus.DRAFT.value,
                "validation_result": validation_result.model_dump(mode="json"),
            }
        )
        return await self.repository.transition_validation_state(
            replacement,
            expected_status=StrategyVersionStatus.VALIDATING,
            expected_checksum=expected_checksum,
        )

    async def publish_draft(
        self,
        *,
        strategy_id: str,
        user_id: str,
        validation_result: StrategyValidationResult | None = None,
        factor_dependencies: Sequence[FrozenFactorDependency] | None = None,
        skill_dependencies: Sequence[FrozenSkillDependency] | None = None,
    ) -> StrategyVersion:
        strategy, draft = await self._owned_current_draft(strategy_id, user_id=user_id)
        result = validation_result or draft.validation_result
        if result is None:
            raise StrategyLifecycleError("publishing requires a validation result")
        return await self._publish_draft(
            strategy=strategy,
            draft=draft,
            validation_result=result,
            factor_dependencies=(
                draft.factor_dependencies
                if factor_dependencies is None
                else factor_dependencies
            ),
            skill_dependencies=(
                draft.skill_dependencies
                if skill_dependencies is None
                else skill_dependencies
            ),
            allow_system=False,
        )

    async def create_next_draft(
        self,
        *,
        strategy_id: str,
        user_id: str,
        parent_version_id: str | None = None,
        change_summary: str = "New draft",
    ) -> StrategyVersion:
        strategy = await self._get_owned_strategy(strategy_id, user_id=user_id)
        if strategy.current_draft_version_id is not None:
            raise StrategyLifecycleError("strategy already has a current draft")
        selected_parent_id = parent_version_id or strategy.latest_published_version_id
        if selected_parent_id is None:
            raise StrategyLifecycleError("a new draft requires a published parent version")
        parent = await self.repository.get_owned_version(
            selected_parent_id, user_id=user_id
        )
        if (
            parent is None
            or parent.strategy_id != strategy_id
            or parent.status
            not in {StrategyVersionStatus.PUBLISHED, StrategyVersionStatus.DEPRECATED}
        ):
            raise StrategyNotFound("parent published version not found")

        version_id = self._id_factory()
        now = self._clock()
        reserved_version = await self.repository.reserve_next_draft(
            strategy_id=strategy_id,
            user_id=user_id,
            expected_version_sequence=strategy.version_sequence,
            strategy_version_id=version_id,
            updated_at=now,
        )
        draft = StrategyVersion(
            strategy_version_id=version_id,
            strategy_id=strategy_id,
            user_id=user_id,
            version=reserved_version,
            status=StrategyVersionStatus.DRAFT,
            market=parent.market,
            definition=deepcopy(parent.definition),
            analysis_profile_version_id=parent.analysis_profile_version_id,
            factor_dependencies=parent.factor_dependencies,
            skill_dependencies=parent.skill_dependencies,
            created_by=user_id,
            created_at=now,
            change_summary=change_summary,
            parent_version_id=parent.strategy_version_id,
        )
        try:
            return await self.repository.insert_reserved_version(draft)
        except Exception:
            await self.repository.release_draft_reservation(
                strategy_id=strategy_id,
                user_id=user_id,
                strategy_version_id=version_id,
                reserved_version=reserved_version,
            )
            raise

    async def deprecate_version(
        self, strategy_version_id: str, *, user_id: str
    ) -> StrategyVersion:
        if user_id == SYSTEM_USER_ID:
            raise StrategyPermissionDenied("system templates are read-only")
        return await self.repository.deprecate_version(
            strategy_version_id, user_id=user_id
        )

    async def archive_strategy(self, strategy_id: str, *, user_id: str) -> Strategy:
        if user_id == SYSTEM_USER_ID:
            raise StrategyPermissionDenied("system templates are read-only")
        return await self.repository.archive_strategy(
            strategy_id, user_id=user_id, archived_at=self._clock()
        )

    async def _create_initial(
        self,
        *,
        user_id: str,
        name: str,
        description: str,
        tags: Sequence[str],
        kind: StrategyKind,
        market: Market,
        definition: dict[str, Any],
        analysis_profile_version_id: str | None,
        change_summary: str,
        visibility: StrategyVisibility,
        clone_source: StrategyCloneSource | None,
        factor_dependencies: Sequence[FrozenFactorDependency] = (),
        skill_dependencies: Sequence[FrozenSkillDependency] = (),
    ) -> tuple[Strategy, StrategyVersion]:
        now = self._clock()
        strategy_id = self._id_factory()
        version_id = self._id_factory()
        version = StrategyVersion(
            strategy_version_id=version_id,
            strategy_id=strategy_id,
            user_id=user_id,
            version=1,
            market=market,
            definition=deepcopy(definition),
            analysis_profile_version_id=analysis_profile_version_id,
            factor_dependencies=tuple(factor_dependencies),
            skill_dependencies=tuple(skill_dependencies),
            created_by=user_id,
            created_at=now,
            change_summary=change_summary,
        )
        strategy = Strategy(
            strategy_id=strategy_id,
            user_id=user_id,
            name=name,
            description=description,
            tags=tuple(tags),
            kind=kind,
            visibility=visibility,
            current_draft_version_id=version_id,
            clone_source=clone_source,
            created_at=now,
            updated_at=now,
        )
        return await self.repository.create_strategy(strategy, version)

    async def _publish_draft(
        self,
        *,
        strategy: Strategy,
        draft: StrategyVersion,
        validation_result: StrategyValidationResult,
        factor_dependencies: Sequence[FrozenFactorDependency],
        skill_dependencies: Sequence[FrozenSkillDependency],
        allow_system: bool,
    ) -> StrategyVersion:
        if strategy.user_id == SYSTEM_USER_ID and not allow_system:
            raise StrategyPermissionDenied("system templates are read-only")
        if draft.status != StrategyVersionStatus.DRAFT:
            raise StrategyLifecycleError("only a draft can be published")
        if not validation_result.valid:
            raise StrategyLifecycleError("an invalid strategy cannot be published")
        published_at = self._clock()
        payload = draft.model_dump(mode="json", exclude={"checksum"})
        payload.update(
            {
                "status": StrategyVersionStatus.PUBLISHED.value,
                "validation_result": validation_result.model_dump(mode="json"),
                "factor_dependencies": [
                    item.model_dump(mode="json")
                    for item in sorted(
                        factor_dependencies, key=lambda item: (item.factor_id, item.version)
                    )
                ],
                "skill_dependencies": [
                    item.model_dump(mode="json")
                    for item in sorted(
                        skill_dependencies, key=lambda item: (item.skill_id, item.version)
                    )
                ],
                "published_at": published_at,
            }
        )
        published = StrategyVersion.model_validate(payload)
        return await self.repository.publish_version(
            published,
            expected_draft_checksum=draft.checksum,
            updated_at=published_at,
        )

    async def _get_owned_strategy(self, strategy_id: str, *, user_id: str) -> Strategy:
        if user_id == SYSTEM_USER_ID:
            raise StrategyPermissionDenied("system templates are read-only")
        strategy = await self.repository.get_strategy(
            strategy_id,
            user_id=user_id,
            include_archived=False,
            include_readonly=False,
        )
        if strategy is None:
            raise StrategyNotFound("strategy not found")
        return strategy

    async def _owned_current_draft(
        self, strategy_id: str, *, user_id: str
    ) -> tuple[Strategy, StrategyVersion]:
        strategy = await self._get_owned_strategy(strategy_id, user_id=user_id)
        if strategy.current_draft_version_id is None:
            raise StrategyLifecycleError("strategy has no current draft")
        draft = await self.repository.get_owned_version(
            strategy.current_draft_version_id, user_id=user_id
        )
        if draft is None or draft.strategy_id != strategy_id:
            raise StrategyLifecycleError("strategy draft pointer is inconsistent")
        if draft.status != StrategyVersionStatus.DRAFT:
            raise StrategyLifecycleError("current version is not a mutable draft")
        return strategy, draft
