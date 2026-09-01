"""Resolve saved profiles or legacy request parameters into one runtime shape."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
from typing import Any

from pydantic import ValidationError

from app.models.analysis import (
    AnalysisAnalyst,
    AnalysisFactorContext,
    AnalysisInvestmentHorizon,
    AnalysisModelReference,
    AnalysisParameters,
    AnalysisProfileSource,
    AnalysisProfileVersion,
    AnalysisProfileVersionStatus,
    AnalysisResearchDepth,
    AnalysisRiskPreference,
    ResolvedAnalysisProfile,
)
from app.models.strategy import StrategyVersionStatus
from app.repositories.strategy_repository import StrategyRepository


class AnalysisProfileResolutionError(ValueError):
    pass


class AnalysisProfileConflict(AnalysisProfileResolutionError):
    pass


_PROFILE_CONFLICT_FIELDS = {
    "selected_analysts",
    "research_depth",
    "quick_analysis_model",
    "deep_analysis_model",
}

_DEPTH_DEBATE_DEFAULTS = {
    AnalysisResearchDepth.QUICK: (1, 1),
    AnalysisResearchDepth.BASIC: (1, 1),
    AnalysisResearchDepth.STANDARD: (2, 1),
    AnalysisResearchDepth.DEEP: (3, 2),
    AnalysisResearchDepth.COMPREHENSIVE: (5, 3),
}


class AnalysisProfileResolver:
    def __init__(self, repository: StrategyRepository):
        self.repository = repository

    async def resolve(
        self,
        *,
        user_id: str,
        profile_id: str | None = None,
        legacy_parameters: AnalysisParameters | Mapping[str, Any] | None = None,
    ) -> ResolvedAnalysisProfile:
        parameters = self._legacy_parameters(legacy_parameters)
        embedded_profile_id = parameters.profile_id if parameters is not None else None
        if profile_id and embedded_profile_id and profile_id != embedded_profile_id:
            raise AnalysisProfileConflict("conflicting profile_id values")
        selected_profile_id = profile_id or embedded_profile_id
        if selected_profile_id is not None:
            if parameters is not None:
                conflicts = parameters.model_fields_set & _PROFILE_CONFLICT_FIELDS
                if conflicts:
                    raise AnalysisProfileConflict(
                        "profile_id cannot be combined with inline profile fields: "
                        + ", ".join(sorted(conflicts))
                    )
            return await self._resolve_saved(selected_profile_id, user_id=user_id)
        return self._resolve_legacy(parameters or AnalysisParameters())

    async def _resolve_saved(
        self, profile_id: str, *, user_id: str
    ) -> ResolvedAnalysisProfile:
        profile = await self.repository.get_analysis_profile(
            profile_id, user_id=user_id
        )
        if profile is None:
            raise AnalysisProfileResolutionError("analysis profile not found")
        if profile.latest_published_version_id is None:
            raise AnalysisProfileResolutionError(
                "analysis profile has no published version"
            )
        version = await self.repository.get_analysis_profile_version(
            profile.latest_published_version_id, user_id=user_id
        )
        if version is None or version.status not in {
            AnalysisProfileVersionStatus.PUBLISHED,
            AnalysisProfileVersionStatus.DEPRECATED,
        }:
            raise AnalysisProfileResolutionError(
                "published analysis profile version is unavailable"
            )
        await self._validate_strategy_context(version, user_id=user_id)
        return ResolvedAnalysisProfile(
            source=AnalysisProfileSource.VERSIONED,
            profile_id=profile.profile_id,
            profile_version_id=version.profile_version_id,
            profile_version=version.version,
            **_runtime_fields(version),
        )

    async def _validate_strategy_context(
        self, version: AnalysisProfileVersion, *, user_id: str
    ) -> None:
        if version.strategy_context is None:
            return
        strategy_version = await self.repository.get_version(
            version.strategy_context, user_id=user_id, include_system=True
        )
        if strategy_version is None or strategy_version.status not in {
            StrategyVersionStatus.PUBLISHED,
            StrategyVersionStatus.DEPRECATED,
        }:
            raise AnalysisProfileResolutionError(
                "strategy_context is not a readable published strategy version"
            )

    @staticmethod
    def _legacy_parameters(
        value: AnalysisParameters | Mapping[str, Any] | None,
    ) -> AnalysisParameters | None:
        if value is None or isinstance(value, AnalysisParameters):
            return value
        try:
            return AnalysisParameters.model_validate(value)
        except ValidationError as exc:
            raise AnalysisProfileResolutionError("invalid legacy analysis parameters") from exc

    @staticmethod
    def _resolve_legacy(parameters: AnalysisParameters) -> ResolvedAnalysisProfile:
        try:
            analysts = tuple(AnalysisAnalyst(item) for item in parameters.selected_analysts)
            if not analysts or len(set(analysts)) != len(analysts):
                raise ValueError("selected_analysts must be a non-empty unique subset")
            depth = AnalysisResearchDepth(parameters.research_depth)
            quick_name = parameters.quick_analysis_model or "default-quick"
            deep_name = parameters.deep_analysis_model or "default-deep"
            debate_rounds, risk_rounds = _DEPTH_DEBATE_DEFAULTS[depth]
            return ResolvedAnalysisProfile(
                source=AnalysisProfileSource.LEGACY_TEMPORARY,
                selected_analysts=analysts,
                research_depth=depth,
                quick_model_ref=AnalysisModelReference(
                    config_id=_legacy_model_config_id(quick_name), model_name=quick_name
                ),
                deep_model_ref=AnalysisModelReference(
                    config_id=_legacy_model_config_id(deep_name), model_name=deep_name
                ),
                risk_preference=AnalysisRiskPreference.BALANCED,
                investment_horizon=AnalysisInvestmentHorizon.MEDIUM,
                enabled_skill_versions=(),
                factor_context=AnalysisFactorContext(),
                strategy_context=None,
                debate_rounds=debate_rounds,
                risk_debate_rounds=risk_rounds,
                output_schema_version="analysis-report-v1",
                disclaimer_profile="standard-cn-v1",
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise AnalysisProfileResolutionError(
                "legacy analysis parameters cannot form a valid temporary profile"
            ) from exc


def _runtime_fields(version: AnalysisProfileVersion) -> dict[str, Any]:
    return {
        "selected_analysts": version.selected_analysts,
        "research_depth": version.research_depth,
        "quick_model_ref": version.quick_model_ref,
        "deep_model_ref": version.deep_model_ref,
        "risk_preference": version.risk_preference,
        "investment_horizon": version.investment_horizon,
        "enabled_skill_versions": version.enabled_skill_versions,
        "factor_context": version.factor_context,
        "strategy_context": version.strategy_context,
        "debate_rounds": version.debate_rounds,
        "risk_debate_rounds": version.risk_debate_rounds,
        "output_schema_version": version.output_schema_version,
        "disclaimer_profile": version.disclaimer_profile,
    }


def _legacy_model_config_id(model_name: str) -> str:
    """Create a safe reference ID even when a legacy model name contains `/`."""

    digest = hashlib.sha256(model_name.encode("utf-8")).hexdigest()[:20]
    return f"legacy-model:{digest}"
