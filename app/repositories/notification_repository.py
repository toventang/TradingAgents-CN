import uuid
from typing import Optional, List, Dict, Any
from app.core.database import get_mongo_db
from app.models.notification import NotificationPreference, NotificationLog
from app.utils.timezone import now_tz


class NotificationRepository:
    """通知偏好与发送日志持久化 Repository"""

    def __init__(self, db=None):
        self._db = db

    def get_db(self):
        return self._db if self._db is not None else get_mongo_db()

    async def get_preference(self, user_id: str) -> NotificationPreference:
        db = self.get_db()
        doc = await db["notification_preferences"].find_one({"user_id": user_id})
        if not doc:
            pref = NotificationPreference(user_id=user_id)
            await db["notification_preferences"].insert_one(pref.model_dump())
            return pref
        doc.pop("_id", None)
        return NotificationPreference(**doc)

    async def update_preference(self, preference: NotificationPreference) -> NotificationPreference:
        db = self.get_db()
        preference.updated_at = now_tz()
        data = preference.model_dump()
        await db["notification_preferences"].update_one(
            {"user_id": preference.user_id},
            {"$set": data},
            upsert=True
        )
        return preference

    async def save_log(self, log: NotificationLog) -> NotificationLog:
        db = self.get_db()
        data = log.model_dump()
        await db["notification_logs"].insert_one(data)
        return log

    async def list_logs(self, user_id: str, limit: int = 50) -> List[NotificationLog]:
        db = self.get_db()
        cursor = db["notification_logs"].find({"user_id": user_id}).sort("created_at", -1).limit(limit)
        results = []
        async for doc in cursor:
            doc.pop("_id", None)
            results.append(NotificationLog(**doc))
        return results
