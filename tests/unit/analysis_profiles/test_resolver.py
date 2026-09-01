from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models.analysis import AnalysisParameters, AnalysisProfileSource
from app.models.strategy import (
    StrategyValidationResult,
    StrategyVersion,
    StrategyVersionStatus,
)
from app.models.symbol import Market
from app.repositories.strategy_repository import StrategyRepository
from app.services.analysis_profiles import (
    AnalysisProfileConflict,
    AnalysisProfileResolutionError,
    AnalysisProfileResolver,
    AnalysisProfileService,
)
from tests.strategy_fakes import FakeDatabase


pytestmark = pytest.mark.asyncio
NOW = datetime(2025, 6, 3, 8, tzinfo=timezone.utc)


async def published_profile(database):
    identifiers = iter(("profile-1", "profile-version-1"))
    profiles = AnalysisProfileService(
        StrategyRepository(database),
        clock=lambda: NOW,
        id_factory=lambda: next(identifiers),
    )
    profile, _ = await profiles.create_profile(
        user_id="alice",
        name="Deep profile",
        selected_analysts=("market", "news"),
        research_depth="深度",
        quick_model_ref={"config_id": "model-config:quick"},
        deep_model_ref={"config_id": "model-config:deep"},
        risk_preference="conservative",
        investment_horizon="long",
        enabled_skill_versions=("skill-news:v2",),
        factor_context={"factor_ids": ("news_sentiment_7d",), "max_evidence_items_per_factor": 2},
        debate_rounds=3,
        risk_debate_rounds=2,
        output_schema_version="analysis-report-v2",
        disclaimer_profile="conservative-cn-v1",
    )
    await profiles.publish_draft(profile_id=profile.profile_id, user_id="alice")
    return profile


async def test_saved_profile_resolves_to_complete_versioned_runtime_shape():
    database = FakeDatabase()
    profile = await published_profile(database)
    resolved = await AnalysisProfileResolver(StrategyRepository(database)).resolve(
        user_id="alice", profile_id=profile.profile_id
    )
    assert resolved.source == AnalysisProfileSource.VERSIONED
    assert resolved.profile_version_id == "profile-version-1"
    assert tuple(item.value for item in resolved.selected_analysts) == ("market", "news")
    assert resolved.research_depth.value == "深度"
    assert resolved.risk_preference.value == "conservative"
    assert resolved.investment_horizon.value == "long"
    assert resolved.enabled_skill_versions == ("skill-news:v2",)
    assert resolved.factor_context.factor_ids == ("news_sentiment_7d",)
    assert resolved.output_schema_version == "analysis-report-v2"


async def test_profile_id_rejects_explicit_conflicting_legacy_fields_only():
    database = FakeDatabase()
    profile = await published_profile(database)
    resolver = AnalysisProfileResolver(StrategyRepository(database))

    # Defaults that were not explicitly supplied are not false conflicts.
    resolved = await resolver.resolve(
        user_id="alice", legacy_parameters=AnalysisParameters(profile_id=profile.profile_id)
    )
    assert resolved.source == AnalysisProfileSource.VERSIONED

    with pytest.raises(AnalysisProfileConflict, match="selected_analysts"):
        await resolver.resolve(
            user_id="alice",
            legacy_parameters=AnalysisParameters(
                profile_id=profile.profile_id,
                selected_analysts=["market"],
            ),
        )
    with pytest.raises(AnalysisProfileConflict, match="conflicting profile_id"):
        await resolver.resolve(
            user_id="alice",
            profile_id="another-profile",
            legacy_parameters=AnalysisParameters(profile_id=profile.profile_id),
        )


async def test_legacy_parameters_create_non_persisted_temporary_profile():
    database = FakeDatabase()
    repository = StrategyRepository(database)
    resolved = await AnalysisProfileResolver(repository).resolve(
        user_id="alice",
        legacy_parameters=AnalysisParameters(
            selected_analysts=["market", "fundamentals"],
            research_depth="全面",
            quick_analysis_model="qwen-turbo",
            deep_analysis_model="qwen-max",
        ),
    )
    assert resolved.source == AnalysisProfileSource.LEGACY_TEMPORARY
    assert resolved.profile_id is None
    assert resolved.debate_rounds == 5
    assert resolved.risk_debate_rounds == 3
    assert resolved.quick_model_ref.config_id.startswith("legacy-model:")
    assert resolved.quick_model_ref.model_name == "qwen-turbo"
    assert resolved.factor_context.factor_ids == ()
    assert repository.ANALYSIS_PROFILES_COLLECTION not in database.collections


async def test_unpublished_and_cross_user_profiles_are_not_resolvable():
    database = FakeDatabase()
    identifiers = iter(("profile-private", "profile-private-v1"))
    profiles = AnalysisProfileService(
        StrategyRepository(database),
        clock=lambda: NOW,
        id_factory=lambda: next(identifiers),
    )
    profile, _ = await profiles.create_profile(user_id="alice", name="Draft")
    resolver = AnalysisProfileResolver(profiles.repository)
    with pytest.raises(AnalysisProfileResolutionError, match="no published"):
        await resolver.resolve(user_id="alice", profile_id=profile.profile_id)
    with pytest.raises(AnalysisProfileResolutionError, match="not found"):
        await resolver.resolve(user_id="bob", profile_id=profile.profile_id)


async def test_strategy_context_requires_readable_published_version():
    database = FakeDatabase()
    repository = StrategyRepository(database)
    database[repository.VERSIONS_COLLECTION].documents.append(
        StrategyVersion(
            strategy_version_id="strategy-version-1",
            strategy_id="strategy-1",
            user_id="alice",
            version=1,
            status=StrategyVersionStatus.PUBLISHED,
            market=Market.CN,
            definition={"fixture": True},
            validation_result=StrategyValidationResult(valid=True, validated_at=NOW),
            created_by="alice",
            created_at=NOW,
            published_at=NOW,
        ).model_dump(mode="json")
    )
    identifiers = iter(("context-profile", "context-profile-v1"))
    profiles = AnalysisProfileService(
        repository,
        clock=lambda: NOW,
        id_factory=lambda: next(identifiers),
    )
    profile, _ = await profiles.create_profile(
        user_id="alice",
        name="Strategy context",
        strategy_context="strategy-version-1",
    )
    await profiles.publish_draft(profile_id=profile.profile_id, user_id="alice")
    resolved = await AnalysisProfileResolver(repository).resolve(
        user_id="alice", profile_id=profile.profile_id
    )
    assert resolved.strategy_context == "strategy-version-1"

    database[repository.VERSIONS_COLLECTION].documents.clear()
    with pytest.raises(AnalysisProfileResolutionError, match="strategy_context"):
        await AnalysisProfileResolver(repository).resolve(
            user_id="alice", profile_id=profile.profile_id
        )
