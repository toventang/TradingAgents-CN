import asyncio
import hashlib
from app.core.database import get_mongo_db
from app.models.skill import Skill, SkillVersion, SkillStatus
from app.services.skills.system_skills import get_all_system_skills
from app.utils.timezone import now_tz


async def seed_system_skills(db=None) -> int:
    """
    幂等 Synchronize/Seed 系统 Skill 库至 MongoDB。
    使用 skill_id 与 version_id 进行 upsert。
    """
    if db is None:
        db = get_mongo_db()

    templates = get_all_system_skills()
    synced_count = 0
    now = now_tz()

    for tmpl in templates:
        sid = tmpl["skill_id"]
        vid = f"v_sys_{sid}"
        code = tmpl["code"].strip()
        checksum = hashlib.sha256(code.encode("utf-8")).hexdigest()

        skill_obj = Skill(
            skill_id=sid,
            user_id="system",
            name=tmpl["name"],
            description=tmpl["description"],
            skill_type=tmpl["skill_type"],
            is_system_skill=True,
            status=SkillStatus.PUBLISHED,
            latest_version_num=1,
            published_version_num=1,
            created_at=now,
            updated_at=now
        )

        version_obj = SkillVersion(
            version_id=vid,
            skill_id=sid,
            version_num=1,
            code=code,
            contract=tmpl["contract"],
            checksum=checksum,
            is_published=True,
            commit_message="Initial system skill seed",
            created_at=now
        )

        # Upsert Skill
        await db["skills"].update_one(
            {"skill_id": sid},
            {"$set": skill_obj.model_dump()},
            upsert=True
        )

        # Upsert SkillVersion
        await db["skill_versions"].update_one(
            {"version_id": vid},
            {"$set": version_obj.model_dump()},
            upsert=True
        )

        synced_count += 1

    return synced_count


if __name__ == "__main__":
    count = asyncio.run(seed_system_skills())
    print(f"Successfully seeded {count} system skills.")
