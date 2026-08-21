import pytest
from typing import Optional
from fastapi.testclient import TestClient
from fastapi import FastAPI, Depends, Header, HTTPException
from app.routers.factors import router as factors_router, get_task_repository
from app.routers.auth_db import get_current_user
from app.repositories.domain_task_repository import DomainTaskRepository
from app.services.auth_service import AuthService
from tests.integration.test_domain_task_repository import FakeDatabase

app = FastAPI()
app.include_router(factors_router)

def create_fresh_analysis_api_setup():
    fake_db = FakeDatabase()
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

    app.dependency_overrides[get_task_repository] = lambda: task_repo
    app.dependency_overrides[get_current_user] = mock_get_current_user

    return task_repo

@pytest.fixture
def auth_headers():
    token_a = AuthService.create_access_token(sub="user_analysis_a")
    token_b = AuthService.create_access_token(sub="user_analysis_b")
    return {
        "user_a": {"Authorization": f"Bearer {token_a}"},
        "user_b": {"Authorization": f"Bearer {token_b}"}
    }

@pytest.mark.asyncio
async def test_factor_analysis_api_job_submission_and_isolation(auth_headers):
    task_repo = create_fresh_analysis_api_setup()
    client = TestClient(app)

    # Submit job -> 202
    res_submit = client.post(
        "/api/factors/analysis",
        headers=auth_headers["user_a"],
        json={"factor_id": "ret_1d", "symbols": ["000001", "000002"]}
    )
    assert res_submit.status_code == 202
    task_id = res_submit.json()["data"]["task_id"]

    # User A reads analysis task -> 200
    res_get_a = client.get(f"/api/factors/analysis/{task_id}", headers=auth_headers["user_a"])
    assert res_get_a.status_code == 200

    # User B reads User A analysis task -> 403 / 404
    res_get_b = client.get(f"/api/factors/analysis/{task_id}", headers=auth_headers["user_b"])
    assert res_get_b.status_code in (403, 404)
