import json
import importlib.util
import sys
import types
from urllib.parse import urlsplit

import pytest
from fastapi import FastAPI

from app.models.domain_task import DomainTaskStatus
from app.repositories.domain_task_repository import DomainTaskRepository

# This router test does not exercise password/JWT authentication. Keep it
# deterministic when run outside the fully provisioned Jules environment.
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

from app.routers.domain_tasks import get_domain_task_repository, router
from app.routers.auth_db import get_current_user
if using_local_auth_stub:
    sys.modules.pop("app.routers.auth_db", None)
from tests.unit.domain_tasks.fakes import FakeDatabase

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def asgi_request(app, method, target):
    parsed = urlsplit(target)
    request_sent = False
    messages = []

    async def receive():
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)

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
            "headers": [],
            "client": ("test", 1234),
            "server": ("test", 80),
        },
        receive,
        send,
    )
    response_start = next(
        message for message in messages if message["type"] == "http.response.start"
    )
    body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    return response_start["status"], json.loads(body or b"null")


async def make_api():
    repository = DomainTaskRepository(FakeDatabase())
    await repository.ensure_indexes()
    active_user = {"id": "owner"}
    app = FastAPI()
    app.include_router(router, prefix="/api")

    async def current_user_override():
        return active_user

    app.dependency_overrides[get_current_user] = current_user_override
    app.dependency_overrides[get_domain_task_repository] = lambda: repository
    return app, repository, active_user


async def test_task_reads_lists_and_events_are_owner_scoped():
    app, repository, active_user = await make_api()
    own = await repository.create_task(
        user_id="owner",
        task_type="backtest",
        payload={"private": "owner"},
    )
    await repository.create_task(
        user_id="other",
        task_type="backtest",
        payload={"private": "other"},
    )

    code, body = await asgi_request(app, "GET", f"/api/tasks/{own.task_id}")
    assert code == 200
    assert body["user_id"] == "owner"

    code, body = await asgi_request(
        app,
        "GET",
        "/api/tasks?type=backtest&status=queued&page=1&page_size=20",
    )
    assert code == 200
    assert [item["user_id"] for item in body["items"]] == ["owner"]

    code, body = await asgi_request(
        app,
        "GET",
        f"/api/tasks/{own.task_id}/events",
    )
    assert code == 200
    assert body["items"][0]["event_type"] == "created"

    active_user["id"] = "other"
    for path in (
        f"/api/tasks/{own.task_id}",
        f"/api/tasks/{own.task_id}/events",
    ):
        code, body = await asgi_request(app, "GET", path)
        assert code == 404
        assert body["detail"]["code"] == "TASK_NOT_FOUND"


async def test_cancel_returns_202_404_and_409():
    app, repository, _ = await make_api()
    queued = await repository.create_task(
        user_id="owner",
        task_type="factor_compute",
        payload={},
    )

    code, body = await asgi_request(
        app,
        "POST",
        f"/api/tasks/{queued.task_id}/cancel",
    )
    assert code == 202
    assert body["status"] == DomainTaskStatus.CANCELLED.value

    code, body = await asgi_request(
        app,
        "POST",
        "/api/tasks/00000000-0000-0000-0000-000000000000/cancel",
    )
    assert code == 404
    assert body["detail"]["code"] == "TASK_NOT_FOUND"

    running = await repository.create_task(
        user_id="owner",
        task_type="campaign_eval",
        payload={},
        priority=20,
    )
    claimed = await repository.claim_next(
        worker_id="running-worker",
        lease_seconds=30,
    )
    assert claimed.task_id == running.task_id
    code, body = await asgi_request(
        app,
        "POST",
        f"/api/tasks/{running.task_id}/cancel",
    )
    assert code == 202
    assert body["status"] == DomainTaskStatus.CANCELLING.value

    completed = await repository.create_task(
        user_id="owner",
        task_type="backtest",
        payload={},
    )
    await repository.claim_next(worker_id="worker", lease_seconds=30)
    await repository.mark_succeeded(
        task_id=completed.task_id,
        worker_id="worker",
    )
    code, body = await asgi_request(
        app,
        "POST",
        f"/api/tasks/{completed.task_id}/cancel",
    )
    assert code == 409
    assert body["detail"]["code"] == "TASK_NOT_CANCELLABLE"
