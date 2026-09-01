"""HTTP-facing AnalysisProfile orchestration kept outside routers."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pymongo import ASCENDING, DESCENDING, ReturnDocument

from app.models.analysis import AnalysisProfile, AnalysisProfileVersion
from app.repositories.strategy_repository import StrategyRepository
from app.services.analysis_profiles import AnalysisProfileService


class AnalysisProfileApiNotFound(LookupError):
    pass


class AnalysisProfileApiService:
    def __init__(
        self,
        *,
        repository: StrategyRepository,
        lifecycle: AnalysisProfileService | None = None,
    ):
        self.repository = repository
        self.lifecycle = lifecycle or AnalysisProfileService(repository)

    async def create(self, *, user_id: str, request):
        payload = request.model_dump(exclude_none=False)
        payload.pop("name", None)
        return await self.lifecycle.create_profile(
            user_id=user_id, name=request.name, **payload
        )

    async def list(
        self, *, user_id: str, page: int, page_size: int
    ) -> tuple[tuple[AnalysisProfile, ...], int]:
        cursor = self.repository.get_db()[
            self.repository.ANALYSIS_PROFILES_COLLECTION
        ].find({"user_id": user_id, "archived_at": None}).sort(
            [("updated_at", DESCENDING), ("profile_id", ASCENDING)]
        )
        documents = await cursor.to_list(length=None)
        total = len(documents)
        start = (page - 1) * page_size
        return (
            tuple(_parse(AnalysisProfile, item) for item in documents[start : start + page_size]),
            total,
        )

    async def detail(
        self, *, user_id: str, profile_id: str
    ) -> tuple[AnalysisProfile, tuple[AnalysisProfileVersion, ...]]:
        profile = await self.repository.get_analysis_profile(
            profile_id, user_id=user_id
        )
        if profile is None:
            raise AnalysisProfileApiNotFound("analysis profile not found")
        versions = await self.repository.list_analysis_profile_versions(
            profile_id, user_id=user_id
        )
        return profile, versions

    async def update_version(
        self, *, user_id: str, profile_id: str, version_id: str, request
    ) -> AnalysisProfileVersion:
        profile = await self.repository.get_analysis_profile(
            profile_id, user_id=user_id
        )
        if profile is None or profile.current_draft_version_id != version_id:
            raise AnalysisProfileApiNotFound("current analysis profile draft not found")
        return await self.lifecycle.update_draft(
            profile_id=profile_id,
            user_id=user_id,
            expected_checksum=request.expected_checksum,
            changes=request.changes,
            change_summary=request.change_summary,
        )

    async def publish(
        self, *, user_id: str, profile_id: str, version_id: str
    ) -> AnalysisProfileVersion:
        profile = await self.repository.get_analysis_profile(
            profile_id, user_id=user_id
        )
        if profile is None or profile.current_draft_version_id != version_id:
            raise AnalysisProfileApiNotFound("current analysis profile draft not found")
        return await self.lifecycle.publish_draft(profile_id=profile_id, user_id=user_id)

    async def create_version(
        self, *, user_id: str, profile_id: str, change_summary: str
    ) -> AnalysisProfileVersion:
        return await self.lifecycle.create_next_draft(
            profile_id=profile_id,
            user_id=user_id,
            change_summary=change_summary,
        )

    async def archive(
        self, *, user_id: str, profile_id: str, archived_at: datetime
    ) -> AnalysisProfile:
        document = await self.repository.get_db()[
            self.repository.ANALYSIS_PROFILES_COLLECTION
        ].find_one_and_update(
            {"profile_id": profile_id, "user_id": user_id, "archived_at": None},
            {"$set": {"archived_at": archived_at, "updated_at": archived_at}},
            return_document=ReturnDocument.AFTER,
        )
        if document is None:
            raise AnalysisProfileApiNotFound("analysis profile not found")
        return _parse(AnalysisProfile, document)


def _parse(model, document: dict[str, Any]):
    payload = dict(document)
    payload.pop("_id", None)
    return model.model_validate(payload)
