import hashlib
import uuid
from typing import Dict, Any, Optional, List, Tuple
from app.models.skill import Skill, SkillVersion, SkillStatus, SkillType, SkillIOContract
from app.repositories.strategy_repository import get_mongo_db
from app.utils.timezone import now_tz


class SkillRegistry:
    """Skill 注册表与版本管理"""

    def __init__(self, db=None):
        self._db = db

    def get_db(self):
        return self._db if self._db is not None else get_mongo_db()

    async def create_skill(
        self,
        user_id: str,
        name: str,
        code: str,
        description: str = "",
        skill_type: SkillType = SkillType.MARKET,
        contract: Optional[SkillIOContract] = None,
        is_system_skill: bool = False
    ) -> Tuple[Skill, SkillVersion]:
        """新建 Skill 及初始 v1 版本"""
        db = self.get_db()
        sid = f"skill_{uuid.uuid4().hex[:12]}"
        vid = f"v_skill_{uuid.uuid4().hex[:12]}"
        now = now_tz()

        checksum = hashlib.sha256(code.encode("utf-8")).hexdigest()

        skill = Skill(
            skill_id=sid,
            user_id=user_id,
            name=name,
            description=description,
            skill_type=skill_type,
            is_system_skill=is_system_skill,
            status=SkillStatus.DRAFT,
            latest_version_num=1,
            created_at=now,
            updated_at=now
        )

        version = SkillVersion(
            version_id=vid,
            skill_id=sid,
            version_num=1,
            code=code,
            contract=contract or SkillIOContract(),
            checksum=checksum,
            is_published=False,
            commit_message="Initial draft v1",
            created_at=now
        )

        await db["skills"].insert_one(skill.model_dump())
        await db["skill_versions"].insert_one(version.model_dump())
        return skill, version

    async def get_skill(self, skill_id: str) -> Optional[Skill]:
        db = self.get_db()
        doc = await db["skills"].find_one({"skill_id": skill_id})
        if not doc:
            return None
        doc.pop("_id", None)
        return Skill(**doc)

    async def get_latest_version(self, skill_id: str) -> Optional[SkillVersion]:
        db = self.get_db()
        cursor = db["skill_versions"].find({"skill_id": skill_id}).sort("version_num", -1).limit(1)
        async for doc in cursor:
            doc.pop("_id", None)
            return SkillVersion(**doc)
        return None
