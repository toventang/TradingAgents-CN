import uuid
from typing import Optional, List, Dict, Any
from app.core.database import get_mongo_db
from app.models.risk import RiskEvaluationResult
from app.utils.timezone import now_tz


class RiskRepository:
    """风控评估与审计日志持久化 Repository"""

    def __init__(self, db=None):
        self._db = db

    def get_db(self):
        return self._db if self._db is not None else get_mongo_db()

    async def save_audit_log(self, user_id: str, evaluation_res: RiskEvaluationResult) -> Dict[str, Any]:
        db = self.get_db()
        data = evaluation_res.model_dump()
        data["user_id"] = user_id
        await db["risk_audit_logs"].insert_one(data)
        return data

    async def list_audit_logs(
        self,
        user_id: str,
        is_admin: bool = False,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        db = self.get_db()
        query: Dict[str, Any] = {}
        if user_id and not is_admin:
            query["user_id"] = user_id

        cursor = db["risk_audit_logs"].find(query).sort("evaluated_at", -1).skip(offset).limit(limit)
        results = []
        async for doc in cursor:
            doc.pop("_id", None)
            results.append(doc)
        return results
