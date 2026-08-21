import ast
import json
import time
from pathlib import Path
from types import SimpleNamespace

import jwt
import pytest
from fastapi import WebSocketDisconnect

from app.core.config import settings
from app.routers import websocket_notifications as websocket_module
from app.services.auth_service import AuthService, AuthenticatedIdentity, TokenData

pytestmark = pytest.mark.asyncio


class FakeWebSocket:
    def __init__(self):
        self.accepted = False
        self.closed = None
        self.text_messages = []
        self.json_messages = []

    async def accept(self):
        self.accepted = True

    async def close(self, code, reason=None):
        self.closed = (code, reason)

    async def send_text(self, message):
        self.text_messages.append(message)

    async def send_json(self, message):
        self.json_messages.append(message)

    async def receive_text(self):
        raise WebSocketDisconnect()


def identity(user_id, username):
    return AuthenticatedIdentity(user_id=user_id, username=username)


async def test_verified_payload_maps_to_http_compatible_real_identity():
    token_data = TokenData(sub="alice", exp=int(time.time()) + 60)
    user = SimpleNamespace(
        id="user-a-id",
        username="alice",
        is_active=True,
        is_admin=False,
    )
    resolved = AuthService.identity_from_verified_token(token_data, user)
    assert resolved is not None
    assert resolved.user_id == "user-a-id"
    assert resolved.as_http_user() == {
        "id": "user-a-id",
        "username": "alice",
        "name": "alice",
        "is_admin": False,
        "roles": ["user"],
    }


async def test_legacy_http_token_subject_and_expiry_contract_is_preserved():
    token = AuthService.create_access_token("alice", expires_delta=60)

    token_data = AuthService.verify_token(token)

    assert token_data is not None
    assert token_data.sub == "alice"
    assert token_data.exp > int(time.time())


async def test_user_a_notification_never_reaches_user_b():
    manager = websocket_module.ConnectionManager()
    user_a_socket = FakeWebSocket()
    user_b_socket = FakeWebSocket()
    await manager.connect(user_a_socket, "user-a")
    await manager.connect(user_b_socket, "user-b")

    await manager.send_personal_message({"type": "notification"}, "user-a")

    assert len(user_a_socket.text_messages) == 1
    assert user_b_socket.text_messages == []


async def test_user_b_cannot_subscribe_to_user_a_task(monkeypatch):
    async def authenticate(_token):
        return identity("user-b", "bob")

    async def owns_task(_task_id, _user_id):
        return False

    monkeypatch.setattr(AuthService, "authenticate_token", staticmethod(authenticate))
    monkeypatch.setattr(websocket_module, "user_owns_task", owns_task)
    socket = FakeWebSocket()

    await websocket_module.websocket_task_progress_endpoint(
        socket,
        task_id="task-a",
        token="valid-token",
    )

    assert socket.accepted is False
    assert socket.closed == (1008, "Unauthorized")


async def test_persisted_task_ownership_query_is_user_scoped(monkeypatch):
    from app.core import database as database_module
    from app.services import memory_state_manager as memory_module

    class MissingMemoryTaskManager:
        async def get_task(self, _task_id):
            return None

    class FakeCollection:
        def __init__(self):
            self.query = None
            self.projection = None

        async def find_one(self, query, projection):
            self.query = query
            self.projection = projection
            return {"_id": "persisted-task"}

    collection = FakeCollection()

    class FakeDatabase:
        def __getitem__(self, name):
            assert name == "analysis_tasks"
            return collection

    monkeypatch.setattr(
        memory_module,
        "get_memory_state_manager",
        lambda: MissingMemoryTaskManager(),
    )
    monkeypatch.setattr(database_module, "get_mongo_db", lambda: FakeDatabase())

    assert await websocket_module.user_owns_task("task-a", "user-a") is True
    assert collection.query == {
        "task_id": "task-a",
        "user_id": {"$in": ["user-a"]},
    }
    assert collection.projection == {"_id": 1}


async def test_legacy_queue_task_ownership_uses_persisted_user(monkeypatch):
    from app.core import database as database_module
    from app.services import memory_state_manager as memory_module
    from app.services import queue_service as queue_module

    class MissingMemoryTaskManager:
        async def get_task(self, _task_id):
            return None

    class EmptyCollection:
        async def find_one(self, _query, _projection):
            return None

    class EmptyDatabase:
        def __getitem__(self, _name):
            return EmptyCollection()

    class FakeQueueService:
        async def get_task(self, task_id):
            assert task_id == "queue-task-a"
            return {"id": task_id, "user": "user-a"}

    monkeypatch.setattr(
        memory_module,
        "get_memory_state_manager",
        lambda: MissingMemoryTaskManager(),
    )
    monkeypatch.setattr(database_module, "get_mongo_db", lambda: EmptyDatabase())
    monkeypatch.setattr(
        queue_module,
        "get_queue_service",
        lambda: FakeQueueService(),
    )

    assert (
        await websocket_module.user_owns_task("queue-task-a", "user-a") is True
    )
    assert (
        await websocket_module.user_owns_task("queue-task-a", "user-b") is False
    )
    assert (
        await websocket_module.get_task_owner_id("queue-task-a") == "user-a"
    )


async def test_legacy_analysis_websocket_uses_shared_authorizer():
    source_path = (
        Path(__file__).resolve().parents[2] / "app" / "routers" / "analysis.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    endpoint = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "websocket_task_progress"
    )

    assert "token" in {argument.arg for argument in endpoint.args.args}
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "authorize_task_websocket"
        for node in ast.walk(endpoint)
    )


async def test_task_progress_only_reaches_persisted_owner(monkeypatch):
    manager = websocket_module.ConnectionManager()
    monkeypatch.setattr(websocket_module, "manager", manager)

    user_a_socket = FakeWebSocket()
    user_b_socket = FakeWebSocket()
    await manager.connect_task(user_a_socket, "user-a", "task-a")
    await manager.connect_task(user_b_socket, "user-b", "task-b")

    async def task_owner(task_id):
        return "user-a" if task_id == "task-a" else "user-b"

    monkeypatch.setattr(websocket_module, "get_task_owner_id", task_owner)
    sent = await websocket_module.send_task_progress_via_websocket(
        "task-a",
        {"progress": 50, "user_id": "user-b", "token": "do-not-forward"},
    )

    assert sent is True
    assert len(user_a_socket.text_messages) == 1
    assert user_b_socket.text_messages == []
    payload = json.loads(user_a_socket.text_messages[0])
    assert payload["data"]["task_id"] == "task-a"
    assert "user_id" not in payload["data"]
    assert "token" not in payload["data"]


@pytest.mark.parametrize("endpoint", ["notifications", "tasks"])
async def test_invalid_token_closes_before_accept(monkeypatch, endpoint):
    async def reject(_token):
        return None

    monkeypatch.setattr(AuthService, "authenticate_token", staticmethod(reject))
    socket = FakeWebSocket()
    if endpoint == "notifications":
        await websocket_module.websocket_notifications_endpoint(socket, token="bad")
    else:
        await websocket_module.websocket_task_progress_endpoint(
            socket,
            task_id="task-a",
            token="bad",
        )
    assert socket.accepted is False
    assert socket.closed == (1008, "Unauthorized")


async def test_expired_malformed_and_identityless_tokens_are_rejected():
    expired = AuthService.create_access_token("alice", expires_delta=-1)
    malformed = "not-a-jwt"
    identityless = jwt.encode(
        {"exp": int(time.time()) + 60},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    assert AuthService.verify_token(expired) is None
    assert AuthService.verify_token(malformed) is None
    assert AuthService.verify_token(identityless) is None
