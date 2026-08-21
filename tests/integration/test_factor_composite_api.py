import pytest
from typing import Optional
from fastapi.testclient import TestClient
from fastapi import FastAPI, Depends, Header, HTTPException
from app.routers.factors import router as factors_router
from app.routers.auth_db import get_current_user
from app.services.auth_service import AuthService
from tests.integration.test_domain_task_repository import FakeDatabase

app = FastAPI()
app.include_router(factors_router)

def create_fresh_composite_api_setup():
    fake_db = FakeDatabase()

    async def mock_get_current_user(authorization: Optional[str] = Header(None)):
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="Unauthorized")
        token = authorization.split(" ", 1)[1]
        token_data = AuthService.verify_token(token)
        user_id = AuthService.get_canonical_user_id(token_data)
        if not token_data or not user_id:
            raise HTTPException(status_code=401, detail="Unauthorized")
        return {"id": user_id, "username": user_id, "is_admin": False}

    app.dependency_overrides[get_current_user] = mock_get_current_user
    return fake_db

@pytest.fixture
def auth_headers():
    token_a = AuthService.create_access_token(sub="user_comp_a")
    token_b = AuthService.create_access_token(sub="user_comp_b")
    return {
        "user_a": {"Authorization": f"Bearer {token_a}"},
        "user_b": {"Authorization": f"Bearer {token_b}"}
    }

def test_validate_composite_factor_api(auth_headers):
    create_fresh_composite_api_setup()
    client = TestClient(app)

    res = client.post(
        "/api/factors/composites/validate",
        headers=auth_headers["user_a"],
        json={
            "name": "my_composite",
            "base_factors": ["ret_1d", "sma_5"],
            "weights": {"ret_1d": 0.5, "sma_5": 0.5}
        }
    )
    assert res.status_code == 200
    assert res.json()["data"]["valid"] is True
