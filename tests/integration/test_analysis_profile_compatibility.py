from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models.analysis import AnalysisParameters, AnalysisProfileSource
from app.repositories.strategy_repository import StrategyRepository
from app.services.analysis_profiles import AnalysisProfileResolver, AnalysisProfileService
from tests.strategy_fakes import FakeDatabase


pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
NOW = datetime(2025, 6, 3, 8, tzinfo=timezone.utc)


async def test_persist_publish_reload_and_resolve_profile_compatibility():
    database = FakeDatabase()
    repository = StrategyRepository(database)
    identifiers = iter(("profile-1", "profile-version-1", "profile-version-2"))
    service = AnalysisProfileService(
        repository,
        clock=lambda: NOW,
        id_factory=lambda: next(identifiers),
    )
    profile, _ = await service.create_profile(
        user_id="alice",
        name="Balanced",
        factor_context={"factor_ids": ("quality_composite",)},
    )
    await service.publish_draft(profile_id=profile.profile_id, user_id="alice")
    await service.create_next_draft(profile_id=profile.profile_id, user_id="alice")

    reloaded = await repository.get_analysis_profile(profile.profile_id, user_id="alice")
    versions = await repository.list_analysis_profile_versions(
        profile.profile_id, user_id="alice"
    )
    resolved = await AnalysisProfileResolver(repository).resolve(
        user_id="alice", legacy_parameters=AnalysisParameters(profile_id=profile.profile_id)
    )

    assert reloaded is not None and reloaded.version_sequence == 2
    assert [item.version for item in versions] == [1, 2]
    assert resolved.source == AnalysisProfileSource.VERSIONED
    assert resolved.profile_version == 1
    assert resolved.factor_context.factor_ids == ("quality_composite",)
    assert await repository.get_analysis_profile(profile.profile_id, user_id="bob") is None


async def test_analysis_profile_indexes_cover_identity_owner_and_state_scans():
    database = FakeDatabase()
    repository = StrategyRepository(database)
    await repository.ensure_indexes()
    index_names = {
        options["name"]
        for collection in database.collections.values()
        for _, options in collection.indexes
    }
    assert {
        "analysis_profile_id_unique",
        "analysis_profile_owner_updated",
        "analysis_profile_version_number_unique",
        "analysis_profile_version_id_unique",
        "analysis_profile_version_owner_state",
    }.issubset(index_names)
