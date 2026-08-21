import uuid
from typing import Optional, List, Dict, Any
from app.core.database import get_mongo_db
from app.utils.timezone import now_tz
from app.models.strategy import Strategy, StrategyVersion, StrategyStatus


class StrategyNotFoundError(Exception):
    """策略未找到"""
    pass


class StrategyVersionNotFoundError(Exception):
    """策略版本未找到"""
    pass


class StrategyForbiddenError(Exception):
    """无权访问策略"""
    pass


class StrategyRepository:
    """策略与版本持久化 Repository"""

    def __init__(self, db=None):
        self._db = db

    def get_db(self):
        return self._db if self._db is not None else get_mongo_db()

    async def create_strategy(self, strategy: Strategy) -> Strategy:
        db = self.get_db()
        data = strategy.model_dump()
        await db["strategies"].insert_one(data)
        return strategy

    async def get_strategy(self, strategy_id: str) -> Optional[Strategy]:
        db = self.get_db()
        doc = await db["strategies"].find_one({"strategy_id": strategy_id})
        if not doc:
            return None
        doc.pop("_id", None)
        return Strategy(**doc)

    async def list_strategies(
        self,
        user_id: Optional[str] = None,
        include_archived: bool = False,
        include_system: bool = True,
        limit: int = 50,
        offset: int = 0
    ) -> List[Strategy]:
        db = self.get_db()
        query: Dict[str, Any] = {}

        if user_id and include_system:
            query["$or"] = [{"user_id": user_id}, {"is_system_template": True}]
        elif user_id:
            query["user_id"] = user_id
        elif not include_system:
            query["is_system_template"] = False

        if not include_archived:
            query["status"] = {"$ne": StrategyStatus.ARCHIVED}

        cursor = db["strategies"].find(query).sort("updated_at", -1).skip(offset).limit(limit)
        results = []
        async for doc in cursor:
            doc.pop("_id", None)
            results.append(Strategy(**doc))
        return results

    async def update_strategy(self, strategy_id: str, update_data: Dict[str, Any]) -> Strategy:
        db = self.get_db()
        update_data["updated_at"] = now_tz()
        res = await db["strategies"].find_one_and_update(
            {"strategy_id": strategy_id},
            {"$set": update_data},
            return_document=True
        )
        if not res:
            raise StrategyNotFoundError(f"Strategy {strategy_id} not found")
        res.pop("_id", None)
        return Strategy(**res)

    async def archive_strategy(self, strategy_id: str, user_id: str) -> Strategy:
        strat = await self.get_strategy(strategy_id)
        if not strat:
            raise StrategyNotFoundError(f"Strategy {strategy_id} not found")
        if strat.user_id != user_id and not strat.is_system_template:
            raise StrategyForbiddenError(f"User {user_id} cannot archive strategy {strategy_id}")
        if strat.is_system_template:
            raise StrategyForbiddenError("System templates cannot be archived")

        return await self.update_strategy(strategy_id, {"status": StrategyStatus.ARCHIVED})

    async def save_version(self, version: StrategyVersion) -> StrategyVersion:
        db = self.get_db()
        data = version.model_dump()
        await db["strategy_versions"].update_one(
            {"version_id": version.version_id},
            {"$set": data},
            upsert=True
        )
        return version

    async def get_version(self, strategy_id: str, version_id: str) -> Optional[StrategyVersion]:
        db = self.get_db()
        doc = await db["strategy_versions"].find_one({
            "strategy_id": strategy_id,
            "version_id": version_id
        })
        if not doc:
            return None
        doc.pop("_id", None)
        return StrategyVersion(**doc)

    async def list_versions(self, strategy_id: str) -> List[StrategyVersion]:
        db = self.get_db()
        cursor = db["strategy_versions"].find({"strategy_id": strategy_id}).sort("version_num", -1)
        results = []
        async for doc in cursor:
            doc.pop("_id", None)
            results.append(StrategyVersion(**doc))
        return results

    async def get_latest_version(self, strategy_id: str) -> Optional[StrategyVersion]:
        db = self.get_db()
        cursor = db["strategy_versions"].find({"strategy_id": strategy_id}).sort("version_num", -1).limit(1)
        async for doc in cursor:
            doc.pop("_id", None)
            return StrategyVersion(**doc)
        return None
