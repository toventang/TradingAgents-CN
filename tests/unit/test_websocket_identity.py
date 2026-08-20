import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI
from app.services.auth_service import AuthService
from app.routers.websocket_notifications import (
    router as ws_router,
    ConnectionManager,
    manager as global_ws_manager,
    register_task_owner,
    send_notification_via_websocket,
    send_task_progress_via_websocket
)

app = FastAPI()
app.include_router(ws_router)

@pytest.mark.asyncio
async def test_websocket_user_isolation():
    manager = ConnectionManager()

    # Create two mock WebSockets for user_a and user_b
    ws_a = AsyncMock()
    ws_b = AsyncMock()

    await manager.connect(ws_a, "user_a")
    await manager.connect(ws_b, "user_b")

    # Send message to user_a
    await manager.send_personal_message({"type": "notification", "data": "hello_a"}, "user_a")

    ws_a.send_text.assert_called_once()
    assert "hello_a" in ws_a.send_text.call_args[0][0]
    ws_b.send_text.assert_not_called()

@pytest.mark.asyncio
async def test_user_b_does_not_receive_user_a_task_progress():
    manager = ConnectionManager()
    ws_a = AsyncMock()
    ws_b = AsyncMock()

    await manager.connect(ws_a, "user_a")
    await manager.connect(ws_b, "user_b")

    # Override global manager for helper test
    from app.routers import websocket_notifications
    orig_manager = websocket_notifications.manager
    websocket_notifications.manager = manager

    try:
        register_task_owner("task_123", "user_a")
        await send_task_progress_via_websocket("task_123", {"progress": 50}, user_id="user_a")

        ws_a.send_text.assert_called_once()
        ws_b.send_text.assert_not_called()
    finally:
        websocket_notifications.manager = orig_manager

def test_invalid_expired_token_closes_websocket():
    client = TestClient(app)

    # Expired/invalid token
    invalid_token = "invalid.jwt.token"

    with pytest.raises(Exception):
        with client.websocket_connect(f"/ws/notifications?token={invalid_token}") as websocket:
            pass

def test_user_b_cannot_subscribe_to_user_a_task():
    client = TestClient(app)

    token_a = AuthService.create_access_token(sub="user_a")
    token_b = AuthService.create_access_token(sub="user_b")

    register_task_owner("task_user_a_only", "user_a")

    # user_b attempts to connect to user_a task stream
    with pytest.raises(Exception):
        with client.websocket_connect(f"/ws/tasks/task_user_a_only?token={token_b}") as websocket:
            pass
