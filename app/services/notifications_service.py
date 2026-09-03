"""Durable, owner-scoped notifications with best-effort realtime fan-out."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Literal, Optional
from uuid import uuid4

from bson import ObjectId
from pydantic import BaseModel, ConfigDict, Field, field_serializer
from pymongo.errors import DuplicateKeyError

from app.core.database import get_mongo_db, get_redis_client
from app.models.notification import NotificationCreate
from app.utils.timezone import now_tz

logger = logging.getLogger("webapi.notifications")

NOTIFICATION_FANOUT_CHANNEL = "notifications:fanout"
NOTIFICATION_INSTANCE_ID = uuid4().hex
WebSocketSender = Callable[[str, dict[str, Any]], Awaitable[None]]
ALERT_METADATA_KEYS = frozenset(
    {
        "alert_event_id",
        "rule_id",
        "rule_version",
        "market",
        "symbol",
        "stock_name",
        "trigger_type",
        "severity",
        "observed_value",
        "threshold",
        "unit",
        "quote_time",
        "evaluated_at",
        "latency_seconds",
        "source",
        "quality_status",
        "campaign_id",
        "position_id",
        "deep_link",
    }
)


class NotificationItem(BaseModel):
    """REST fallback representation, including the realtime metadata contract."""

    model_config = ConfigDict(extra="forbid")

    id: str
    type: Literal["analysis", "alert", "system"]
    title: str
    content: str | None = None
    link: str | None = None
    source: str | None = None
    severity: Literal["info", "success", "warning", "error"] = "info"
    status: Literal["unread", "read"]
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_serializer("created_at")
    def serialize_datetime(self, value: datetime) -> str:
        return value.isoformat()


class NotificationPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[NotificationItem]
    total: int = 0
    page: int = 1
    page_size: int = 20


class NotificationsService:
    """Persist first, then deliver locally and through cross-instance Redis fan-out.

    MongoDB remains authoritative. Redis or WebSocket failures never remove the
    persisted item, so an authenticated user can recover it through the list API.
    """

    def __init__(
        self,
        db=None,
        redis=None,
        *,
        websocket_sender: WebSocketSender | None = None,
        instance_id: str = NOTIFICATION_INSTANCE_ID,
        clock: Callable[[], datetime] = now_tz,
    ):
        self.collection = "notifications"
        self.channel = NOTIFICATION_FANOUT_CHANNEL
        self.retain_days = 90
        self.max_per_user = 1000
        self._db = db
        self._redis = redis
        self._websocket_sender = websocket_sender
        self.instance_id = instance_id
        self.clock = clock
        self._indexes_ready = False
        self._index_lock = asyncio.Lock()

    def _get_db(self):
        return self._db if self._db is not None else get_mongo_db()

    def _get_redis(self):
        return self._redis if self._redis is not None else get_redis_client()

    async def _ensure_indexes(self) -> None:
        if self._indexes_ready:
            return
        async with self._index_lock:
            if self._indexes_ready:
                return
            collection = self._get_db()[self.collection]
            await collection.create_index(
                [("user_id", 1), ("created_at", -1)],
                name="notification_owner_created",
            )
            await collection.create_index(
                [("user_id", 1), ("status", 1)],
                name="notification_owner_status",
            )
            await collection.create_index(
                [
                    ("user_id", 1),
                    ("type", 1),
                    ("metadata.alert_event_id", 1),
                ],
                unique=True,
                partialFilterExpression={
                    "type": "alert",
                    "metadata.alert_event_id": {"$type": "string"},
                },
                name="notification_alert_event_identity",
            )
            self._indexes_ready = True

    async def create_and_publish(
        self,
        payload: NotificationCreate,
        *,
        publish_realtime: bool = True,
    ) -> str:
        """Idempotently persist an alert notification and publish new items once."""

        await self._ensure_indexes()
        if payload.type == "alert":
            _validate_alert_metadata(payload.metadata)
        collection = self._get_db()[self.collection]
        created_at = self.clock()
        doc = {
            "user_id": payload.user_id,
            "type": payload.type,
            "title": payload.title,
            "content": payload.content,
            "link": payload.link,
            "source": payload.source,
            "severity": payload.severity or "info",
            "status": "unread",
            "created_at": created_at,
            "metadata": payload.metadata or {},
        }
        doc["delivery_checksum"] = _delivery_checksum(doc)
        event_id = doc["metadata"].get("alert_event_id")
        created = True
        if payload.type == "alert" and isinstance(event_id, str) and event_id:
            key = {
                "user_id": payload.user_id,
                "type": "alert",
                "metadata.alert_event_id": event_id,
            }
            try:
                result = await collection.update_one(
                    key,
                    {"$setOnInsert": doc},
                    upsert=True,
                )
                created = result.upserted_id is not None
            except DuplicateKeyError:
                created = False
            stored = await collection.find_one(key)
            if stored is None:
                raise RuntimeError("alert notification upsert was not persisted")
            stored_checksum = stored.get("delivery_checksum") or _delivery_checksum(
                stored
            )
            if stored_checksum != doc["delivery_checksum"]:
                raise ValueError(
                    "alert_event_id already identifies a different notification"
                )
            if stored.get("delivery_checksum") is None:
                await collection.update_one(
                    {"_id": stored["_id"], "user_id": payload.user_id},
                    {"$set": {"delivery_checksum": stored_checksum}},
                )
                stored["delivery_checksum"] = stored_checksum
            doc = stored
            doc_id = str(stored["_id"])
        else:
            result = await collection.insert_one(doc)
            doc_id = str(result.inserted_id)

        message = self._public_message(doc_id, doc)
        if created:
            if publish_realtime:
                await self._send_local(payload.user_id, message)
                await self._publish_cross_instance(payload.user_id, message)
            await self._trim_owner_notifications(payload.user_id)
        return doc_id

    async def _send_local(self, user_id: str, message: dict[str, Any]) -> None:
        try:
            sender = self._websocket_sender
            if sender is None:
                from app.routers.websocket_notifications import (
                    send_notification_via_websocket,
                )

                sender = send_notification_via_websocket
            await sender(user_id, message)
        except Exception:
            logger.warning("local WebSocket notification delivery failed", exc_info=True)

    async def _publish_cross_instance(
        self,
        user_id: str,
        message: dict[str, Any],
    ) -> None:
        envelope = {
            "schema_version": 1,
            "origin_instance_id": self.instance_id,
            "user_id": user_id,
            "message": message,
        }
        try:
            await self._get_redis().publish(
                self.channel,
                json.dumps(envelope, ensure_ascii=False, default=_json_default),
            )
        except Exception:
            logger.warning(
                "Redis notification fan-out failed; Mongo fallback retained",
                exc_info=True,
            )

    async def _trim_owner_notifications(self, user_id: str) -> None:
        collection = self._get_db()[self.collection]
        try:
            await collection.delete_many(
                {
                    "user_id": user_id,
                    "created_at": {
                        "$lt": self.clock() - timedelta(days=self.retain_days)
                    },
                }
            )
            count = await collection.count_documents({"user_id": user_id})
            if count <= self.max_per_user:
                return
            overflow = count - self.max_per_user
            cursor = (
                collection.find({"user_id": user_id}, {"_id": 1})
                .sort("created_at", 1)
                .limit(overflow)
            )
            ids = [item["_id"] async for item in cursor]
            if ids:
                await collection.delete_many({"_id": {"$in": ids}})
        except Exception:
            logger.warning("notification retention cleanup failed", exc_info=True)

    @staticmethod
    def _public_message(doc_id: str, doc: dict[str, Any]) -> dict[str, Any]:
        created_at = doc.get("created_at") or now_tz()
        serialized_created_at = (
            created_at.isoformat()
            if isinstance(created_at, datetime)
            else str(created_at)
        )
        return {
            "id": doc_id,
            "type": doc["type"],
            "title": doc["title"],
            "content": doc.get("content"),
            "link": doc.get("link"),
            "source": doc.get("source"),
            "severity": doc.get("severity", "info"),
            "status": doc.get("status", "unread"),
            "created_at": serialized_created_at,
            "metadata": doc.get("metadata") or {},
        }

    async def unread_count(self, user_id: str) -> int:
        return await self._get_db()[self.collection].count_documents(
            {"user_id": user_id, "status": "unread"}
        )

    async def list(
        self,
        user_id: str,
        *,
        status: Optional[str] = None,
        ntype: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> NotificationPage:
        collection = self._get_db()[self.collection]
        query: dict[str, Any] = {"user_id": user_id}
        if status in ("read", "unread"):
            query["status"] = status
        if ntype in ("analysis", "alert", "system"):
            query["type"] = ntype
        total = await collection.count_documents(query)
        cursor = (
            collection.find(query)
            .sort("created_at", -1)
            .skip((page - 1) * page_size)
            .limit(page_size)
        )
        items = []
        async for document in cursor:
            items.append(
                NotificationItem(
                    id=str(document.get("_id")),
                    type=document["type"],
                    title=document["title"],
                    content=document.get("content"),
                    link=document.get("link"),
                    source=document.get("source"),
                    severity=document.get("severity", "info"),
                    status=document.get("status", "unread"),
                    created_at=document.get("created_at") or self.clock(),
                    metadata=document.get("metadata") or {},
                )
            )
        return NotificationPage(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
        )

    async def mark_read(self, user_id: str, notif_id: str) -> bool:
        try:
            object_id = ObjectId(notif_id)
        except Exception:
            return False
        result = await self._get_db()[self.collection].update_one(
            {"_id": object_id, "user_id": user_id},
            {"$set": {"status": "read"}},
        )
        return result.modified_count > 0

    async def mark_all_read(self, user_id: str) -> int:
        result = await self._get_db()[self.collection].update_many(
            {"user_id": user_id, "status": "unread"},
            {"$set": {"status": "read"}},
        )
        return result.modified_count


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _validate_alert_metadata(metadata: dict[str, Any] | None) -> None:
    if not isinstance(metadata, dict):
        raise ValueError("alert notifications require structured metadata")
    missing = sorted(ALERT_METADATA_KEYS - metadata.keys())
    if missing:
        raise ValueError(f"alert notification metadata is missing: {', '.join(missing)}")
    for key in ("alert_event_id", "rule_id", "market", "trigger_type", "deep_link"):
        if not isinstance(metadata.get(key), str) or not metadata[key]:
            raise ValueError(f"alert notification metadata {key} must be non-empty")
    if not isinstance(metadata.get("rule_version"), int) or metadata["rule_version"] < 1:
        raise ValueError("alert notification rule_version must be positive")


def _delivery_checksum(document: dict[str, Any]) -> str:
    identity = {
        key: document.get(key)
        for key in (
            "user_id",
            "type",
            "title",
            "content",
            "link",
            "source",
            "severity",
            "metadata",
        )
    }
    canonical = json.dumps(
        identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


_notifications_service: NotificationsService | None = None


def get_notifications_service() -> NotificationsService:
    global _notifications_service
    if _notifications_service is None:
        _notifications_service = NotificationsService()
    return _notifications_service
