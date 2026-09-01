"""Owner-scoped lifecycle for immutable AnalysisProfile versions."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from app.models.analysis import (
    AnalysisAnalyst,
    AnalysisFactorContext,
    AnalysisInvestmentHorizon,
    AnalysisModelReference,
    AnalysisProfile,
    AnalysisProfileVersion,
    AnalysisProfileVersionStatus,
    AnalysisResearchDepth,
    AnalysisRiskPreference,
    _analysis_id,
    _analysis_utc_now,
)
from app.repositories.strategy_repository import StrategyConflict, StrategyRepository


class AnalysisProfileNotFound(LookupError):
    pass


class AnalysisProfileLifecycleError(StrategyConflict):
    pass


_CONFIG_FIELDS = {
    "selected_analysts",
    "research_depth",
    "quick_model_ref",
    "deep_model_ref",
    "risk_preference",
    "investment_horizon",
    "enabled_skill_versions",
    "factor_context",
    "strategy_context",
    "debate_rounds",
    "risk_debate_rounds",
    "output_schema_version",
    "disclaimer_profile",
}


class AnalysisProfileService:
    def __init__(
        self,
        repository: StrategyRepository,
        *,
        clock: Callable[[], datetime] = _analysis_utc_now,
        id_factory: Callable[[], str] = _analysis_id,
    ):
        self.repository = repository
        self._clock = clock
        self._id_factory = id_factory

    async def create_profile(
        self,
        *,
        user_id: str,
        name: str,
        selected_analysts: tuple[AnalysisAnalyst | str, ...] = (
            AnalysisAnalyst.MARKET,
            AnalysisAnalyst.FUNDAMENTALS,
            AnalysisAnalyst.NEWS,
            AnalysisAnalyst.SOCIAL,
        ),
        research_depth: AnalysisResearchDepth | str = AnalysisResearchDepth.STANDARD,
        quick_model_ref: AnalysisModelReference | Mapping[str, Any] = AnalysisModelReference(
            config_id="model-config:default-quick"
        ),
        deep_model_ref: AnalysisModelReference | Mapping[str, Any] = AnalysisModelReference(
            config_id="model-config:default-deep"
        ),
        risk_preference: AnalysisRiskPreference | str = AnalysisRiskPreference.BALANCED,
        investment_horizon: AnalysisInvestmentHorizon | str = AnalysisInvestmentHorizon.MEDIUM,
        enabled_skill_versions: tuple[str, ...] = (),
        factor_context: AnalysisFactorContext | Mapping[str, Any] = AnalysisFactorContext(),
        strategy_context: str | None = None,
        debate_rounds: int = 2,
        risk_debate_rounds: int = 1,
        output_schema_version: str = "analysis-report-v1",
        disclaimer_profile: str = "standard-cn-v1",
        change_summary: str = "Initial AnalysisProfile draft",
    ) -> tuple[AnalysisProfile, AnalysisProfileVersion]:
        now = self._clock()
        profile_id = self._id_factory()
        version_id = self._id_factory()
        version = AnalysisProfileVersion(
            profile_version_id=version_id,
            profile_id=profile_id,
            user_id=user_id,
            version=1,
            selected_analysts=selected_analysts,
            research_depth=research_depth,
            quick_model_ref=quick_model_ref,
            deep_model_ref=deep_model_ref,
            risk_preference=risk_preference,
            investment_horizon=investment_horizon,
            enabled_skill_versions=enabled_skill_versions,
            factor_context=factor_context,
            strategy_context=strategy_context,
            debate_rounds=debate_rounds,
            risk_debate_rounds=risk_debate_rounds,
            output_schema_version=output_schema_version,
            disclaimer_profile=disclaimer_profile,
            created_at=now,
            created_by=user_id,
            change_summary=change_summary,
        )
        profile = AnalysisProfile(
            profile_id=profile_id,
            user_id=user_id,
            name=name,
            current_draft_version_id=version_id,
            created_at=now,
            updated_at=now,
        )
        return await self.repository.create_analysis_profile(profile, version)

    async def update_draft(
        self,
        *,
        profile_id: str,
        user_id: str,
        expected_checksum: str,
        changes: Mapping[str, Any],
        change_summary: str | None = None,
    ) -> AnalysisProfileVersion:
        _, draft = await self._current_draft(profile_id, user_id=user_id)
        if draft.checksum != expected_checksum:
            raise StrategyConflict("analysis profile draft checksum changed concurrently")
        unknown = set(changes) - _CONFIG_FIELDS
        if unknown:
            raise ValueError(f"unsupported AnalysisProfile fields: {sorted(unknown)}")
        payload = draft.model_dump(mode="json", exclude={"checksum"})
        payload.update(dict(changes))
        if change_summary is not None:
            payload["change_summary"] = change_summary
        replacement = AnalysisProfileVersion.model_validate(payload)
        return await self.repository.replace_analysis_profile_draft(
            replacement, expected_checksum=expected_checksum
        )

    async def publish_draft(
        self, *, profile_id: str, user_id: str
    ) -> AnalysisProfileVersion:
        _, draft = await self._current_draft(profile_id, user_id=user_id)
        now = self._clock()
        published = AnalysisProfileVersion.model_validate(
            {
                **draft.model_dump(mode="json", exclude={"checksum"}),
                "status": AnalysisProfileVersionStatus.PUBLISHED.value,
                "published_at": now,
            }
        )
        return await self.repository.publish_analysis_profile_version(
            published,
            expected_draft_checksum=draft.checksum,
            updated_at=now,
        )

    async def create_next_draft(
        self,
        *,
        profile_id: str,
        user_id: str,
        change_summary: str = "New AnalysisProfile draft",
    ) -> AnalysisProfileVersion:
        profile = await self._owned_profile(profile_id, user_id=user_id)
        if profile.current_draft_version_id is not None:
            raise AnalysisProfileLifecycleError("analysis profile already has a draft")
        if profile.latest_published_version_id is None:
            raise AnalysisProfileLifecycleError("new draft requires a published parent")
        parent = await self.repository.get_analysis_profile_version(
            profile.latest_published_version_id, user_id=user_id
        )
        if parent is None or parent.status not in {
            AnalysisProfileVersionStatus.PUBLISHED,
            AnalysisProfileVersionStatus.DEPRECATED,
        }:
            raise AnalysisProfileNotFound("published parent profile version not found")
        version_id = self._id_factory()
        now = self._clock()
        reserved = await self.repository.reserve_next_analysis_profile_draft(
            profile_id=profile_id,
            user_id=user_id,
            expected_version_sequence=profile.version_sequence,
            profile_version_id=version_id,
            updated_at=now,
        )
        payload = parent.model_dump(
            mode="json",
            exclude={
                "checksum",
                "profile_version_id",
                "version",
                "status",
                "created_at",
                "published_at",
                "change_summary",
                "parent_version_id",
            },
        )
        draft = AnalysisProfileVersion(
            **payload,
            profile_version_id=version_id,
            version=reserved,
            status=AnalysisProfileVersionStatus.DRAFT,
            created_at=now,
            published_at=None,
            change_summary=change_summary,
            parent_version_id=parent.profile_version_id,
        )
        try:
            return await self.repository.insert_reserved_analysis_profile_version(draft)
        except Exception:
            await self.repository.release_analysis_profile_draft_reservation(
                profile_id=profile_id,
                user_id=user_id,
                profile_version_id=version_id,
                reserved_version=reserved,
            )
            raise

    async def _owned_profile(self, profile_id: str, *, user_id: str) -> AnalysisProfile:
        profile = await self.repository.get_analysis_profile(
            profile_id, user_id=user_id
        )
        if profile is None:
            raise AnalysisProfileNotFound("analysis profile not found")
        return profile

    async def _current_draft(
        self, profile_id: str, *, user_id: str
    ) -> tuple[AnalysisProfile, AnalysisProfileVersion]:
        profile = await self._owned_profile(profile_id, user_id=user_id)
        if profile.current_draft_version_id is None:
            raise AnalysisProfileLifecycleError("analysis profile has no current draft")
        draft = await self.repository.get_analysis_profile_version(
            profile.current_draft_version_id, user_id=user_id
        )
        if draft is None or draft.status != AnalysisProfileVersionStatus.DRAFT:
            raise AnalysisProfileLifecycleError("analysis profile draft pointer is invalid")
        return profile, draft
