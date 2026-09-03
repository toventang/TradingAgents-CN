"""Authenticated and user-isolated WebSocket notification endpoints."""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set, Tuple

from bson import ObjectId
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.services.auth_service import AuthService, AuthenticatedIdentity
from app.services.notifications_service import (
    NOTIFICATION_FANOUT_CHANNEL,
    NOTIFICATION_INSTANCE_ID,
)

router = APIRouter()
logger = logging.getLogger("webapi.websocket")

POLICY_VIOLATION = 1008


class ConnectionManager:
    """Own notification and task sockets by authenticated user identity."""

    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        self.task_connections: Dict[Tuple[str, str], Set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, user_id: str) -> None:
        await websocket.accept()
        async with self._lock:
            self.active_connections.setdefault(user_id, set()).add(websocket)
            user_count = len(self.active_connections[user_id])
        logger.info("[WS] connected user=%s user_connections=%s", user_id, user_count)

    async def disconnect(self, websocket: WebSocket, user_id: str) -> None:
        async with self._lock:
            connections = self.active_connections.get(user_id)
            if connections is not None:
                connections.discard(websocket)
                if not connections:
                    self.active_connections.pop(user_id, None)
        logger.info("[WS] disconnected user=%s", user_id)

    async def connect_task(
        self,
        websocket: WebSocket,
        user_id: str,
        task_id: str,
    ) -> None:
        await websocket.accept()
        async with self._lock:
            self.task_connections.setdefault((user_id, task_id), set()).add(websocket)
        logger.info("[WS-Task] connected task=%s user=%s", task_id, user_id)

    async def disconnect_task(
        self,
        websocket: WebSocket,
        user_id: str,
        task_id: str,
    ) -> None:
        key = (user_id, task_id)
        async with self._lock:
            connections = self.task_connections.get(key)
            if connections is not None:
                connections.discard(websocket)
                if not connections:
                    self.task_connections.pop(key, None)
        logger.info("[WS-Task] disconnected task=%s user=%s", task_id, user_id)

    async def _send_to_connections(
        self,
        message: dict,
        connections: list[WebSocket],
    ) -> list[WebSocket]:
        serialized = json.dumps(message, ensure_ascii=False)
        dead: list[WebSocket] = []
        for connection in connections:
            try:
                await connection.send_text(serialized)
            except Exception:
                logger.warning("[WS] failed to send message", exc_info=True)
                dead.append(connection)
        return dead

    async def send_personal_message(self, message: dict, user_id: str) -> None:
        async with self._lock:
            connections = list(self.active_connections.get(user_id, set()))
        dead = await self._send_to_connections(message, connections)
        if dead:
            async with self._lock:
                current = self.active_connections.get(user_id)
                if current is not None:
                    current.difference_update(dead)
                    if not current:
                        self.active_connections.pop(user_id, None)

    async def send_task_message(
        self,
        message: dict,
        user_id: str,
        task_id: str,
    ) -> None:
        key = (user_id, task_id)
        async with self._lock:
            connections = list(self.task_connections.get(key, set()))
        dead = await self._send_to_connections(message, connections)
        if dead:
            async with self._lock:
                current = self.task_connections.get(key)
                if current is not None:
                    current.difference_update(dead)
                    if not current:
                        self.task_connections.pop(key, None)

    def get_stats(self) -> dict:
        return {
            "total_users": len(self.active_connections),
            "total_connections": sum(
                len(connections) for connections in self.active_connections.values()
            ),
            "task_subscriptions": sum(
                len(connections) for connections in self.task_connections.values()
            ),
            "users": {
                user_id: len(connections)
                for user_id, connections in self.active_connections.items()
            },
        }


manager = ConnectionManager()


class RedisNotificationRelay:
    """Relay owner-addressed Redis notifications to sockets on this instance."""

    def __init__(
        self,
        connection_manager: ConnectionManager,
        *,
        redis_factory=None,
        instance_id: str = NOTIFICATION_INSTANCE_ID,
        channel: str = NOTIFICATION_FANOUT_CHANNEL,
    ):
        self.manager = connection_manager
        self.redis_factory = redis_factory
        self.instance_id = instance_id
        self.channel = channel
        self._pubsub = None
        self._task: asyncio.Task | None = None
        self._start_lock = asyncio.Lock()

    async def start(self) -> bool:
        if self._task is not None and not self._task.done():
            return True
        async with self._start_lock:
            if self._task is not None and not self._task.done():
                return True
            try:
                if self.redis_factory is None:
                    from app.core.database import get_redis_client

                    redis = get_redis_client()
                else:
                    redis = self.redis_factory()
                self._pubsub = redis.pubsub()
                await self._pubsub.subscribe(self.channel)
                self._task = asyncio.create_task(self._listen())
                return True
            except Exception:
                logger.warning(
                    "[WS] Redis notification relay unavailable; Mongo fallback remains",
                    exc_info=True,
                )
                await self.close()
                return False

    async def close(self) -> None:
        task = self._task
        self._task = None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        pubsub = self._pubsub
        self._pubsub = None
        if pubsub is not None:
            try:
                await pubsub.unsubscribe(self.channel)
            except Exception:
                logger.debug("[WS] Redis relay unsubscribe failed", exc_info=True)
            try:
                close = getattr(pubsub, "aclose", None) or getattr(pubsub, "close")
                result = close()
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.debug("[WS] Redis relay close failed", exc_info=True)

    async def _listen(self) -> None:
        try:
            while self._pubsub is not None:
                message = await self._pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0,
                )
                if message is None:
                    await asyncio.sleep(0)
                    continue
                await self.handle_message(message.get("data"))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("[WS] Redis notification relay stopped", exc_info=True)
        finally:
            if self._pubsub is not None:
                await self.close()

    async def handle_message(self, raw: Any) -> bool:
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            envelope = json.loads(raw) if isinstance(raw, str) else raw
            if not isinstance(envelope, dict) or envelope.get("schema_version") != 1:
                return False
            if envelope.get("origin_instance_id") == self.instance_id:
                return False
            user_id = envelope.get("user_id")
            message = envelope.get("message")
            if not isinstance(user_id, str) or not user_id or not isinstance(message, dict):
                return False
            public_message = _redact_sensitive_fields(message)
            await self.manager.send_personal_message(
                {"type": "notification", "data": public_message},
                user_id,
            )
            return True
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
            logger.warning("[WS] discarded invalid Redis notification envelope")
            return False


notification_relay = RedisNotificationRelay(manager)


def _redact_sensitive_fields(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _redact_sensitive_fields(item)
            for key, item in value.items()
            if key.lower() not in {"user_id", "token", "authorization"}
        }
    if isinstance(value, list):
        return [_redact_sensitive_fields(item) for item in value]
    return value


def _user_id_candidates(user_id: str) -> list[object]:
    candidates: list[object] = [user_id]
    if ObjectId.is_valid(user_id):
        object_id = ObjectId(user_id)
        if object_id not in candidates:
            candidates.append(object_id)
    return candidates


async def _authenticate_websocket(
    websocket: WebSocket,
    token: Optional[str],
) -> Optional[AuthenticatedIdentity]:
    identity = await AuthService.authenticate_token(token or "")
    if identity is None:
        await websocket.close(code=POLICY_VIOLATION, reason="Unauthorized")
    return identity


async def get_task_owner_id(task_id: str) -> Optional[str]:
    """Read ownership from the task record, never from client progress payloads."""
    try:
        from app.services.memory_state_manager import get_memory_state_manager

        task = await get_memory_state_manager().get_task(task_id)
        if task and task.user_id:
            return str(task.user_id)
    except Exception:
        logger.warning("[WS-Task] memory owner lookup failed task=%s", task_id)

    try:
        from app.core.database import get_mongo_db

        database = get_mongo_db()
        if database is not None:
            document = await database["analysis_tasks"].find_one(
                {"task_id": task_id},
                {"user_id": 1},
            )
            if document and document.get("user_id"):
                return str(document["user_id"])
    except Exception:
        logger.warning("[WS-Task] persisted owner lookup failed task=%s", task_id)

    try:
        from app.services.queue_service import get_queue_service

        queue_task = await get_queue_service().get_task(task_id)
        if queue_task is not None and queue_task.get("user"):
            return str(queue_task["user"])
    except Exception:
        logger.warning("[WS-Task] queue owner lookup failed task=%s", task_id)
    return None


async def user_owns_task(task_id: str, user_id: str) -> bool:
    """Check ownership without revealing whether another user's task exists."""
    try:
        from app.services.memory_state_manager import get_memory_state_manager

        task = await get_memory_state_manager().get_task(task_id)
        if task is not None:
            return str(task.user_id) == user_id
    except Exception:
        logger.warning("[WS-Task] memory ownership lookup failed task=%s", task_id)

    try:
        from app.core.database import get_mongo_db

        database = get_mongo_db()
        if database is None:
            document = None
        else:
            document = await database["analysis_tasks"].find_one(
                {
                    "task_id": task_id,
                    "user_id": {"$in": _user_id_candidates(user_id)},
                },
                {"_id": 1},
            )
        if document is not None:
            return True
    except Exception:
        logger.warning("[WS-Task] ownership database lookup failed task=%s", task_id)

    try:
        from app.services.queue_service import get_queue_service

        queue_task = await get_queue_service().get_task(task_id)
        return queue_task is not None and str(queue_task.get("user")) == user_id
    except Exception:
        logger.warning("[WS-Task] ownership queue lookup failed task=%s", task_id)
        return False


async def authorize_task_websocket(
    websocket: WebSocket,
    task_id: str,
    token: Optional[str],
) -> Optional[AuthenticatedIdentity]:
    identity = await _authenticate_websocket(websocket, token)
    if identity is None:
        return None
    if not await user_owns_task(task_id, identity.user_id):
        await websocket.close(code=POLICY_VIOLATION, reason="Unauthorized")
        return None
    return identity


@router.websocket("/ws/notifications")
async def websocket_notifications_endpoint(
    websocket: WebSocket,
    token: Optional[str] = Query(default=None),
):
    identity = await _authenticate_websocket(websocket, token)
    if identity is None:
        return

    await notification_relay.start()
    await manager.connect(websocket, identity.user_id)
    await websocket.send_json(
        {
            "type": "connected",
            "data": {
                "user_id": identity.user_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "message": "WebSocket 连接成功",
            },
        }
    )

    heartbeat_task = None
    try:
        async def send_heartbeat() -> None:
            while True:
                try:
                    await asyncio.sleep(30)
                    await websocket.send_json(
                        {
                            "type": "heartbeat",
                            "data": {
                                "timestamp": datetime.now(timezone.utc).isoformat()
                            },
                        }
                    )
                except Exception:
                    break

        heartbeat_task = asyncio.create_task(send_heartbeat())
        while True:
            try:
                data = await websocket.receive_text()
                logger.debug(
                    "[WS] received client message user=%s bytes=%s",
                    identity.user_id,
                    len(data.encode("utf-8")),
                )
            except WebSocketDisconnect:
                break
            except Exception:
                logger.warning("[WS] receive failed user=%s", identity.user_id)
                break
    finally:
        if heartbeat_task is not None:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
        await manager.disconnect(websocket, identity.user_id)


@router.websocket("/ws/tasks/{task_id}")
async def websocket_task_progress_endpoint(
    websocket: WebSocket,
    task_id: str,
    token: Optional[str] = Query(default=None),
):
    identity = await authorize_task_websocket(websocket, task_id, token)
    if identity is None:
        return

    await manager.connect_task(websocket, identity.user_id, task_id)
    await websocket.send_json(
        {
            "type": "connected",
            "data": {
                "task_id": task_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "message": "已连接任务进度流",
            },
        }
    )

    try:
        while True:
            try:
                data = await websocket.receive_text()
                logger.debug(
                    "[WS-Task] received task=%s user=%s bytes=%s",
                    task_id,
                    identity.user_id,
                    len(data.encode("utf-8")),
                )
            except WebSocketDisconnect:
                break
            except Exception:
                logger.warning(
                    "[WS-Task] receive failed task=%s user=%s",
                    task_id,
                    identity.user_id,
                )
                break
    finally:
        await manager.disconnect_task(websocket, identity.user_id, task_id)


@router.get("/ws/stats")
async def get_websocket_stats():
    return manager.get_stats()


async def send_notification_via_websocket(user_id: str, notification: dict) -> None:
    await manager.send_personal_message(
        {"type": "notification", "data": notification},
        user_id,
    )


async def send_task_progress_via_websocket(
    task_id: str,
    progress_data: dict,
) -> bool:
    owner_id = await get_task_owner_id(task_id)
    if owner_id is None:
        logger.warning("[WS-Task] progress skipped for unknown task=%s", task_id)
        return False

    safe_progress = {
        key: value
        for key, value in progress_data.items()
        if key.lower() not in {"user_id", "token", "authorization"}
    }
    safe_progress.setdefault("task_id", task_id)
    await manager.send_task_message(
        {"type": "progress", "data": safe_progress},
        owner_id,
        task_id,
    )
    return True
