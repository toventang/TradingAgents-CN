import uuid
from typing import Optional, List, Dict, Any
from app.core.database import get_mongo_db
from app.utils.timezone import now_tz
from app.models.analysis import AnalysisProfile, AnalysisProfileVersion


class AnalysisProfileNotFoundError(Exception):
    """AnalysisProfile 未找到"""
    pass


class AnalysisProfileRepository:
    """AnalysisProfile 与版本持久化 Repository"""

    def __init__(self, db=None):
        self._db = db

    def get_db(self):
        return self._db if self._db is not None else get_mongo_db()

    async def create_profile(self, profile: AnalysisProfile, version: AnalysisProfileVersion) -> AnalysisProfile:
        db = self.get_db()
        await db["analysis_profiles"].insert_one(profile.model_dump())
        await db["analysis_profile_versions"].insert_one(version.model_dump())
        return profile

    async def get_profile(self, profile_id: str) -> Optional[AnalysisProfile]:
        db = self.get_db()
        doc = await db["analysis_profiles"].find_one({"profile_id": profile_id})
        if not doc:
            return None
        doc.pop("_id", None)
        return AnalysisProfile(**doc)

    async def get_latest_version(self, profile_id: str) -> Optional[AnalysisProfileVersion]:
        db = self.get_db()
        cursor = db["analysis_profile_versions"].find({"profile_id": profile_id}).sort("version_num", -1).limit(1)
        async for doc in cursor:
            doc.pop("_id", None)
            return AnalysisProfileVersion(**doc)
        return None
