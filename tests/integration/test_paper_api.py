import pytest
from typing import Optional
from fastapi.testclient import TestClient
from fastapi import FastAPI, Depends, Header, HTTPException
from app.routers.paper import router as paper_router, get_paper_service
from app.routers.auth_db import get_current_user
from app.services.paper.paper_service import PaperTradingService
from app.services.auth_service import AuthService
from tests.integration.test_domain_task_repository import FakeDatabase

app = FastAPI()
app.include_router(paper_router)

def create_fresh_paper_setup():
    fake_db = FakeDatabase()
    service = PaperTradingService(db=fake_db)

    async def mock_get_current_user(authorization: Optional[str] = Header(None)):
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="Unauthorized")
        token = authorization.split(" ", 1)[1]
        token_data = AuthService.verify_token(token)
        user_id = AuthService.get_canonical_user_id(token_data)
        if not token_data or not user_id:
            raise HTTPException(status_code=401, detail="Unauthorized")
        return {"id": user_id, "username": user_id, "is_admin": False}

    def override_get_service():
        return service

    app.dependency_overrides[get_paper_service] = override_get_service
    app.dependency_overrides[get_current_user] = mock_get_current_user

    return fake_db, service

@pytest.fixture
def auth_headers():
    token_a = AuthService.create_access_token(sub="user_paper_a")
    return {"Authorization": f"Bearer {token_a}"}

@pytest.mark.asyncio
async def test_paper_account_api(auth_headers):
    fake_db, service = create_fresh_paper_setup()
    client = TestClient(app)

    res = client.get("/paper/account", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()["data"]
    assert "account" in data
    assert "positions" in data
    assert data["account"]["cash"]["CNY"] == 1000000.0

@pytest.mark.asyncio
async def test_paper_order_buy_api(auth_headers):
    fake_db, service = create_fresh_paper_setup()
    client = TestClient(app)

    # Seed mock market quote
    await fake_db["market_quotes"].insert_one({"code": "000001", "close": 10.0})

    res = client.post(
        "/paper/order",
        headers=auth_headers,
        json={"code": "000001", "side": "buy", "quantity": 100, "market": "CN"}
    )
    assert res.status_code == 200
    order_data = res.json()["data"]["order"]
    assert order_data["code"] == "000001"
    assert order_data["quantity"] == 100
    assert order_data["status"] == "filled"

@pytest.mark.asyncio
async def test_paper_reset_api(auth_headers):
    fake_db, service = create_fresh_paper_setup()
    client = TestClient(app)

    res_no_confirm = client.post("/paper/reset", headers=auth_headers)
    assert res_no_confirm.status_code == 400

    res_confirm = client.post("/paper/reset?confirm=true", headers=auth_headers)
    assert res_confirm.status_code == 200
    assert res_confirm.json()["data"]["message"] == "账户已重置"
