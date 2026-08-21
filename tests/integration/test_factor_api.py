import pytest
from typing import Optional
from fastapi.testclient import TestClient
from fastapi import FastAPI, Depends, Header, HTTPException
from app.routers.factors import router as factors_router, get_factor_repository, get_task_repository
from app.routers.auth_db import get_current_user
from app.repositories.factor_repository import FactorRepository
from app.repositories.domain_task_repository import DomainTaskRepository
from app.services.auth_service import AuthService
from tests.integration.test_domain_task_repository import FakeDatabase

app = FastAPI()
app.include_router(factors_router)

def create_fresh_factor_api_setup():
    fake_db = FakeDatabase()
    factor_repo = FactorRepository(db=fake_db)
    task_repo = DomainTaskRepository(db=fake_db)

    async def mock_get_current_user(authorization: Optional[str] = Header(None)):
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="Unauthorized")
        token = authorization.split(" ", 1)[1]
        token_data = AuthService.verify_token(token)
        user_id = AuthService.get_canonical_user_id(token_data)
        if not token_data or not user_id:
            raise HTTPException(status_code=401, detail="Unauthorized")
        return {"id": user_id, "username": user_id, "is_admin": False}

    app.dependency_overrides[get_factor_repository] = lambda: factor_repo
    app.dependency_overrides[get_task_repository] = lambda: task_repo
    app.dependency_overrides[get_current_user] = mock_get_current_user

    return factor_repo, task_repo

@pytest.fixture
def auth_headers():
    token_a = AuthService.create_access_token(sub="user_factor_a")
    token_b = AuthService.create_access_token(sub="user_factor_b")
    return {
        "user_a": {"Authorization": f"Bearer {token_a}"},
        "user_b": {"Authorization": f"Bearer {token_b}"}
    }

def test_list_factor_definitions_api():
    client = TestClient(app)
    res = client.get("/api/factors/definitions?category=price")
    assert res.status_code == 200
    items = res.json()["data"]["items"]
    assert len(items) == 18

    res_single = client.get("/api/factors/definitions/ret_1d")
    assert res_single.status_code == 200
    assert res_single.json()["data"]["factor_id"] == "ret_1d"

@pytest.mark.asyncio
async def test_submit_factor_compute_job_api(auth_headers):
    create_fresh_factor_api_setup()
    client = TestClient(app)

    res = client.post(
        "/api/factors/compute",
        headers=auth_headers["user_a"],
        json={"symbols": ["000001"], "market": "CN", "factor_ids": ["ret_1d"]}
    )
    assert res.status_code == 202
    assert "task_id" in res.json()["data"]

@pytest.mark.asyncio
async def test_snapshot_api_and_isolation(auth_headers):
    factor_repo, task_repo = create_fresh_factor_api_setup()
    client = TestClient(app)

    await factor_repo.save_snapshot(
        snapshot_id="snap_test_100",
        user_id="user_factor_a",
        market="CN",
        factor_ids=["ret_1d"],
        data={"000001": {"ret_1d": [0.01]}},
        checksum="hash100"
    )

    # User A accesses snapshot -> 200
    res_a = client.get("/api/factors/snapshots/snap_test_100", headers=auth_headers["user_a"])
    assert res_a.status_code == 200

    # User A accesses snapshot values -> 200
    res_vals = client.get("/api/factors/snapshots/snap_test_100/values?page=1&page_size=10", headers=auth_headers["user_a"])
    assert res_vals.status_code == 200
    assert "000001" in res_vals.json()["data"]["items"]

    # User B accesses User A snapshot -> 404
    res_b = client.get("/api/factors/snapshots/snap_test_100", headers=auth_headers["user_b"])
    assert res_b.status_code == 404
