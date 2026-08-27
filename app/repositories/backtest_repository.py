import uuid
from typing import Optional, List, Dict, Any
from app.core.database import get_mongo_db
from app.utils.timezone import now_tz
from app.models.backtest import BacktestResult, BacktestStatus, BacktestConfig


class BacktestNotFoundError(Exception):
    """回测任务未找到"""
    pass


class BacktestForbiddenError(Exception):
    """无权访问回测任务"""
    pass


class BacktestRepository:
    """回测任务与结果持久化 Repository"""

    def __init__(self, db=None):
        self._db = db

    def get_db(self):
        return self._db if self._db is not None else get_mongo_db()

    async def create_backtest(self, result: BacktestResult) -> BacktestResult:
        db = self.get_db()
        data = result.model_dump()
        await db["backtests"].insert_one(data)
        return result

    async def get_backtest(self, backtest_id: str) -> Optional[BacktestResult]:
        db = self.get_db()
        doc = await db["backtests"].find_one({"backtest_id": backtest_id})
        if not doc:
            return None
        doc.pop("_id", None)
        return BacktestResult(**doc)

    async def list_backtests(
        self,
        user_id: Optional[str] = None,
        is_admin: bool = False,
        limit: int = 50,
        offset: int = 0
    ) -> List[BacktestResult]:
        db = self.get_db()
        query: Dict[str, Any] = {}
        if user_id and not is_admin:
            query["user_id"] = user_id

        cursor = db["backtests"].find(query).sort("created_at", -1).skip(offset).limit(limit)
        results = []
        async for doc in cursor:
            doc.pop("_id", None)
            results.append(BacktestResult(**doc))
        return results

    async def update_backtest_result(self, backtest_id: str, update_data: Dict[str, Any]) -> Optional[BacktestResult]:
        db = self.get_db()
        res = await db["backtests"].find_one_and_update(
            {"backtest_id": backtest_id},
            {"$set": update_data},
            return_document=True
        )
        if not res:
            return None
        res.pop("_id", None)
        return BacktestResult(**res)

    async def delete_backtest(self, backtest_id: str, user_id: str, is_admin: bool = False) -> bool:
        db = self.get_db()
        bt = await self.get_backtest(backtest_id)
        if not bt:
            raise BacktestNotFoundError(f"Backtest {backtest_id} not found")
        if bt.user_id != user_id and not is_admin:
            raise BacktestForbiddenError(f"User {user_id} cannot delete backtest {backtest_id}")

        res = await db["backtests"].delete_one({"backtest_id": backtest_id})
        return res.deleted_count > 0
