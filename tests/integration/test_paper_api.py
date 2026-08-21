import importlib.util
import json
import sys
import types
from urllib.parse import urlsplit

import pytest
from fastapi import FastAPI

from app.models.paper import PriceSnapshot
from app.services.paper import PaperTradingService
from tests.unit.paper.fakes import FakeDatabase
from tests.unit.paper.test_paper_services import seed_rules

using_local_auth_stub = (
    importlib.util.find_spec("bcrypt") is None
    and "app.routers.auth_db" not in sys.modules
)
if using_local_auth_stub:
    auth_stub = types.ModuleType("app.routers.auth_db")

    async def stub_current_user():
        return {"id": "unconfigured"}

    auth_stub.get_current_user = stub_current_user
    sys.modules["app.routers.auth_db"] = auth_stub

from app.routers.paper import get_paper_trading_service, router
from app.routers.auth_db import get_current_user

if using_local_auth_stub:
    sys.modules.pop("app.routers.auth_db", None)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class StaticPriceService:
    def __init__(self, prices):
        self.prices = prices

    async def get_snapshot(self, identity):
        price = self.prices.get((identity.market.value, identity.code))
        if price is None:
            return None
        return PriceSnapshot(
            market=identity.market,
            symbol=identity.symbol,
            price=price,
            source="api-fixture",
        )


async def asgi_request(app, method, target, payload=None):
    parsed = urlsplit(target)
    body = json.dumps(payload).encode() if payload is not None else b""
    request_sent = False
    messages = []

    async def receive():
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)

    headers = (
        [(b"content-type", b"application/json")]
        if payload is not None
        else []
    )
    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": parsed.path,
            "raw_path": parsed.path.encode(),
            "query_string": parsed.query.encode(),
            "root_path": "",
            "headers": headers,
            "client": ("test", 1234),
            "server": ("test", 80),
        },
        receive,
        send,
    )
    start = next(
        message for message in messages if message["type"] == "http.response.start"
    )
    response_body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    return start["status"], json.loads(response_body or b"null")


async def make_api():
    database = FakeDatabase()
    await seed_rules(database)
    service = PaperTradingService(
        database,
        prices=StaticPriceService({("CN", "600519"): 10.0}),
    )
    active_user = {"id": "owner"}
    app = FastAPI()
    app.include_router(router, prefix="/api")

    async def current_user_override():
        return active_user

    app.dependency_overrides[get_current_user] = current_user_override
    app.dependency_overrides[get_paper_trading_service] = lambda: service
    return app, database, service, active_user


async def test_existing_paper_api_flow_and_owner_isolation():
    app, _, _, active_user = await make_api()
    code, body = await asgi_request(
        app,
        "POST",
        "/api/paper/order",
        {
            "code": "600519",
            "side": "buy",
            "quantity": 100,
            "analysis_id": "analysis-1",
        },
    )
    assert code == 200
    assert body["success"] is True
    assert body["data"]["order"]["status"] == "filled"
    assert body["data"]["order"]["analysis_id"] == "analysis-1"

    for path in (
        "/api/paper/account",
        "/api/paper/positions",
        "/api/paper/orders?limit=20",
    ):
        code, body = await asgi_request(app, "GET", path)
        assert code == 200
        assert body["success"] is True

    active_user["id"] = "other"
    code, body = await asgi_request(app, "GET", "/api/paper/positions")
    assert code == 200
    assert body["data"]["items"] == []

    code, body = await asgi_request(app, "POST", "/api/paper/reset")
    assert code == 400
    assert body["detail"] == "请设置 confirm=true 以确认重置"
    code, body = await asgi_request(
        app,
        "POST",
        "/api/paper/reset?confirm=true",
    )
    assert code == 200
    assert body["data"]["message"] == "账户已重置"


async def test_api_maps_validation_and_partial_write_errors():
    app, database, service, _ = await make_api()
    service.prices.prices[("CN", "600519")] = 20_000.0
    code, body = await asgi_request(
        app,
        "POST",
        "/api/paper/order",
        {"code": "600519", "market": "CN", "side": "buy", "quantity": 100},
    )
    assert code == 400
    assert "可用CNY不足" in body["detail"]

    service.prices.prices[("CN", "600519")] = 10.0
    database["paper_positions"].fail_next["insert_one"] = RuntimeError(
        "fixture failure"
    )
    code, body = await asgi_request(
        app,
        "POST",
        "/api/paper/order",
        {"code": "600519", "market": "CN", "side": "buy", "quantity": 100},
    )
    assert code == 500
    assert body["detail"]["code"] == "PAPER_CONSISTENCY_ERROR"
    assert body["detail"]["recovery_id"]
    assert len(database["paper_consistency_recovery"].documents) == 1
