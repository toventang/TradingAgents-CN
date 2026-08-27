import asyncio
from typing import Optional
from app.core.database import get_mongo_db
from app.models.strategy import Strategy, StrategyVersion, StrategyStatus, UniverseSnapshot
from app.services.strategies.templates.catalog import get_all_system_templates
from app.services.strategies.validator import StrategyDSLValidator
from app.utils.timezone import now_tz


async def seed_system_templates(db=None) -> int:
    """
    幂等 Synchronize/Seed 14 个系统策略模板至 MongoDB。
    使用 Strategy.strategy_id 与 StrategyVersion.version_id 进行 upsert。
    """
    if db is None:
        db = get_mongo_db()

    validator = StrategyDSLValidator()
    templates = get_all_system_templates()
    synced_count = 0
    now = now_tz()

    univ = UniverseSnapshot(universe_id="univ_system_default", user_id="system", name="System Default Universe")

    for tmpl in templates:
        strat_id = tmpl["strategy_id"]
        version_id = f"v_sys_{strat_id}"

        spec = {
            "weights": tmpl["parameters"].get("weights", {}),
            "conditions": tmpl["rules"].get("conditions", {}),
            "rules": tmpl["rules"]
        }
        validator.validate_strategy_spec(spec)

        strategy_obj = Strategy(
            strategy_id=strat_id,
            user_id="system",
            name=tmpl["name"],
            description=tmpl["description"],
            strategy_type=tmpl["strategy_type"],
            is_system_template=True,
            status=StrategyStatus.PUBLISHED,
            latest_version_num=1,
            published_version_num=1,
            created_at=now,
            updated_at=now
        )

        version_obj = StrategyVersion(
            version_id=version_id,
            strategy_id=strat_id,
            version_num=1,
            is_published=True,
            parameters=tmpl["parameters"],
            rules=tmpl["rules"],
            universe=univ,
            commit_message="Initial system template seed",
            published_at=now,
            created_at=now
        )

        # Upsert Strategy
        await db["strategies"].update_one(
            {"strategy_id": strat_id},
            {"$set": strategy_obj.model_dump()},
            upsert=True
        )

        # Upsert StrategyVersion
        await db["strategy_versions"].update_one(
            {"version_id": version_id},
            {"$set": version_obj.model_dump()},
            upsert=True
        )

        synced_count += 1

    return synced_count


if __name__ == "__main__":
    count = asyncio.run(seed_system_templates())
    print(f"Successfully seeded {count} system strategy templates.")
