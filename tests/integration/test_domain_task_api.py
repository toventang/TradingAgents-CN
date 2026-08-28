import pytest
from typing import Optional
from fastapi.testclient import TestClient
from fastapi import FastAPI, Depends, Header, HTTPException
from app.routers.domain_tasks import router as domain_tasks_router, get_task_repository
from app.routers.auth_db import get_current_user
from app.repositories.domain_task_repository import DomainTaskRepository
from app.models.domain_task import TaskType, TaskStatus
from app.services.auth_service import AuthService
from tests.integration.test_domain_task_repository import FakeDatabase

app = FastAPI()
app.include_router(domain_tasks_router)

def create_fresh_api_setup():
    fake_db = FakeDatabase()
    fake_repo = DomainTaskRepository(fake_db)

    async def mock_get_current_user(authorization: Optional[str] = Header(None)):
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="Unauthorized")
        token = authorization.split(" ", 1)[1]
        token_data = AuthService.verify_token(token)
        user_id = AuthService.extract_user_id(token_data)
        if not token_data or not user_id:
            raise HTTPException(status_code=401, detail="Unauthorized")
        return {"id": user_id, "username": user_id, "is_admin": False}

    def override_get_repo():
        return fake_repo

    app.dependency_overrides[get_task_repository] = override_get_repo
    app.dependency_overrides[get_current_user] = mock_get_current_user

    return fake_repo

@pytest.fixture
def auth_headers():
    token_a = AuthService.create_access_token(sub="user_a")
    token_b = AuthService.create_access_token(sub="user_b")
    return {
        "user_a": {"Authorization": f"Bearer {token_a}"},
        "user_b": {"Authorization": f"Bearer {token_b}"}
    }

@pytest.mark.asyncio
async def test_get_task_and_owner_isolation_api(auth_headers):
    fake_repo = create_fresh_api_setup()
    client = TestClient(app)

    task = await fake_repo.create_task(
        user_id="user_a",
        task_type=TaskType.FACTOR_COMPUTE,
        payload={"symbols": ["000001"]}
    )

    # Owner user_a fetches task -> 200
    res_a = client.get(f"/api/tasks/{task.task_id}", headers=auth_headers["user_a"])
    assert res_a.status_code == 200
    assert res_a.json()["data"]["task_id"] == task.task_id

    # User_b fetches user_a task -> 403 Forbidden
    res_b = client.get(f"/api/tasks/{task.task_id}", headers=auth_headers["user_b"])
    assert res_b.status_code == 403

@pytest.mark.asyncio
async def test_cancel_task_api_status_codes(auth_headers):
    fake_repo = create_fresh_api_setup()
    client = TestClient(app)

    # Queued task cancel -> 200
    task_queued = await fake_repo.create_task(
        user_id="user_a",
        task_type=TaskType.BACKTEST,
        payload={}
    )
    res_queued = client.post(f"/api/tasks/{task_queued.task_id}/cancel", headers=auth_headers["user_a"])
    assert res_queued.status_code == 200
    assert res_queued.json()["data"]["status"] == "cancelled"

    # Running task cancel -> 202
    task_running = await fake_repo.create_task(
        user_id="user_a",
        task_type=TaskType.BACKTEST,
        payload={}
    )
    claimed = await fake_repo.claim_task(worker_id="worker_1")
    assert claimed.task_id == task_running.task_id
    assert claimed.status == TaskStatus.RUNNING

    res_running = client.post(f"/api/tasks/{task_running.task_id}/cancel", headers=auth_headers["user_a"])
    assert res_running.status_code == 202
    assert res_running.json()["data"]["status"] == "cancelling"

@pytest.mark.asyncio
async def test_list_tasks_and_events_api(auth_headers):
    fake_repo = create_fresh_api_setup()
    client = TestClient(app)

    task = await fake_repo.create_task(
        user_id="user_a",
        task_type=TaskType.ALERT_EVAL,
        payload={}
    )

    # List tasks for user_a
    res_list = client.get("/api/tasks?type=alert_eval", headers=auth_headers["user_a"])
    assert res_list.status_code == 200
    items = res_list.json()["data"]["items"]
    assert len(items) >= 1

    # List task events for user_a
    res_events = client.get(f"/api/tasks/{task.task_id}/events", headers=auth_headers["user_a"])
    assert res_events.status_code == 200
    events = res_events.json()["data"]["items"]
    assert len(events) >= 1
