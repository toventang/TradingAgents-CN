from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from app.models.analysis import AnalysisProfileVersionStatus
from app.repositories.strategy_repository import StrategyConflict, StrategyRepository
from app.services.analysis_profiles import (
    AnalysisProfileLifecycleError,
    AnalysisProfileNotFound,
    AnalysisProfileService,
)
from tests.strategy_fakes import FakeDatabase


pytestmark = pytest.mark.asyncio
NOW = datetime(2025, 6, 3, 8, tzinfo=timezone.utc)


def service(database):
    identifiers = iter(f"analysis-id-{index}" for index in range(1, 20))
    return AnalysisProfileService(
        StrategyRepository(database),
        clock=lambda: NOW,
        id_factory=lambda: next(identifiers),
    )


async def test_profile_publish_is_immutable_and_next_version_keeps_provenance():
    database = FakeDatabase()
    profiles = service(database)
    profile, draft = await profiles.create_profile(
        user_id="alice",
        name="My standard research",
        selected_analysts=("market", "fundamentals", "news"),
        research_depth="标准",
        quick_model_ref={"config_id": "model-config:quick"},
        deep_model_ref={"config_id": "model-config:deep"},
        enabled_skill_versions=("skill-risk:v1",),
        factor_context={"factor_ids": ("quality_composite", "ret_20d")},
        strategy_context="strategy-version-1",
    )
    changed = await profiles.update_draft(
        profile_id=profile.profile_id,
        user_id="alice",
        expected_checksum=draft.checksum,
        changes={"research_depth": "深度", "debate_rounds": 3},
        change_summary="Increase research depth",
    )
    published = await profiles.publish_draft(
        profile_id=profile.profile_id, user_id="alice"
    )
    assert published.status == AnalysisProfileVersionStatus.PUBLISHED
    assert published.research_depth.value == "深度"
    assert published.checksum == changed.checksum

    with pytest.raises(AnalysisProfileLifecycleError, match="no current draft"):
        await profiles.update_draft(
            profile_id=profile.profile_id,
            user_id="alice",
            expected_checksum=published.checksum,
            changes={"research_depth": "全面"},
        )

    next_draft = await profiles.create_next_draft(
        profile_id=profile.profile_id, user_id="alice"
    )
    assert next_draft.version == 2
    assert next_draft.parent_version_id == published.profile_version_id
    assert next_draft.enabled_skill_versions == ("skill-risk:v1",)
    assert next_draft.factor_context.factor_ids == ("quality_composite", "ret_20d")


async def test_profile_owner_isolation_and_optimistic_checksum():
    database = FakeDatabase()
    profiles = service(database)
    profile, draft = await profiles.create_profile(user_id="alice", name="Private")

    with pytest.raises(AnalysisProfileNotFound):
        await profiles.update_draft(
            profile_id=profile.profile_id,
            user_id="bob",
            expected_checksum=draft.checksum,
            changes={"research_depth": "快速"},
        )
    with pytest.raises(StrategyConflict, match="checksum changed"):
        await profiles.update_draft(
            profile_id=profile.profile_id,
            user_id="alice",
            expected_checksum="0" * 64,
            changes={"research_depth": "快速"},
        )
    assert (
        await profiles.repository.get_analysis_profile(
            profile.profile_id, user_id="bob"
        )
        is None
    )


async def test_concurrent_next_draft_has_one_winner():
    database = FakeDatabase()
    profiles = service(database)
    profile, _ = await profiles.create_profile(user_id="alice", name="Concurrent")
    await profiles.publish_draft(profile_id=profile.profile_id, user_id="alice")

    results = await asyncio.gather(
        profiles.create_next_draft(profile_id=profile.profile_id, user_id="alice"),
        profiles.create_next_draft(profile_id=profile.profile_id, user_id="alice"),
        return_exceptions=True,
    )
    assert len([item for item in results if not isinstance(item, Exception)]) == 1
    failures = [item for item in results if isinstance(item, Exception)]
    assert len(failures) == 1
    assert isinstance(failures[0], (StrategyConflict, AnalysisProfileLifecycleError))
