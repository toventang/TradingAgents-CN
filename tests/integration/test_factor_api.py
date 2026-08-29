from __future__ import annotations

import json
from copy import deepcopy
from datetime import date, datetime, timezone
from urllib.parse import urlsplit

import pytest
from fastapi import FastAPI, HTTPException
from pymongo.errors import PyMongoError

from app.models.factor import FactorSnapshot, FactorSnapshotStatus
from app.models.symbol import Market
from app.repositories.domain_task_repository import DomainTaskRepository
from app.repositories.factor_repository import FactorRepository
from app.routers.auth_db import get_current_user
from app.routers.factors import get_factor_api_service, router
from app.services.factors.api_service import FactorApiService
from tests.unit.domain_tasks.fakes import (
    FakeCollection as DomainFakeCollection,
    _apply_update,
    _matches,
)


pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class UpdateResult:
    def __init__(self, upserted_id=None):
        self.upserted_id = upserted_id


class ApiFakeCollection(DomainFakeCollection):
    async def update_one(self, query, update, upsert=False):
        async with self.lock:
            for document in self.documents:
                if _matches(document, query):
                    _apply_update(document, update)
                    return UpdateResult()
            if not upsert:
                return UpdateResult()
            document = deepcopy(query)
            document.update(deepcopy(update.get("$setOnInsert", {})))
            _apply_update(document, update)
            self.documents.append(document)
            return UpdateResult(f"{self.name}-{len(self.documents)}")

    async def count_documents(self, query):
        return sum(1 for document in self.documents if _matches(document, query))

    async def bulk_write(self, operations, ordered=False):
        del ordered
        for operation in operations:
            await self.update_one(operation._filter, operation._doc, operation._upsert)
        return UpdateResult()


class ApiFakeDatabase:
    def __init__(self):
        self.collections = {}

    def __getitem__(self, name):
        return self.collections.setdefault(name, ApiFakeCollection(name))


async def asgi_request(app, method, target, payload=None):
    parsed = urlsplit(target)
    request_sent = False
    messages = []
    body = b"" if payload is None else json.dumps(payload).encode()

    async def receive():
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)

    headers = [] if payload is None else [(b"content-type", b"application/json")]
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
    response_start = next(
        message for message in messages if message["type"] == "http.response.start"
    )
    response_body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    return response_start["status"], json.loads(response_body or b"null")


async def make_api(monkeypatch):
    monkeypatch.setenv("FACTOR_FEATURE_ENABLED", "true")
    database = ApiFakeDatabase()
    factor_repository = FactorRepository(database)
    task_repository = DomainTaskRepository(database)
    await task_repository.ensure_indexes()
    service = FactorApiService(
        factor_repository=factor_repository,
        task_repository=task_repository,
    )
    active_user = {"id": "owner"}
    app = FastAPI()
    app.include_router(router, prefix="/api")

    async def current_user_override():
        if active_user["id"] is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return active_user

    app.dependency_overrides[get_current_user] = current_user_override
    app.dependency_overrides[get_factor_api_service] = lambda: service
    return app, database, service, active_user


def compute_payload(**updates):
    payload = {
        "market": "CN",
        "universe": {
            "snapshot_id": "cn-fixed-2025-01-06",
            "symbols": ["000001", "000002"],
        },
        "start_date": "2024-01-01",
        "end_date": "2025-01-06",
        "as_of": "2025-01-06T15:30:00+00:00",
        "factor_specs": [{"factor_id": "ret_1d", "version": 1}],
        "source_versions": {"daily_bars": "bars-v1"},
        "adj": "qfq",
        "force_recompute": False,
    }
    payload.update(updates)
    return payload


async def test_feature_flag_auth_catalog_detail_validation_and_page_limits(monkeypatch):
    app, _, _, active_user = await make_api(monkeypatch)
    monkeypatch.setenv("FACTOR_FEATURE_ENABLED", "false")
    code, body = await asgi_request(app, "GET", "/api/factors/definitions")
    assert code == 404
    assert body["detail"]["code"] == "FACTOR_FEATURE_DISABLED"

    monkeypatch.setenv("FACTOR_FEATURE_ENABLED", "true")
    active_user["id"] = None
    code, _ = await asgi_request(app, "GET", "/api/factors/definitions")
    assert code == 401
    active_user["id"] = "owner"

    code, body = await asgi_request(
        app,
        "GET",
        "/api/factors/definitions?category=price&market=CN&page=1&page_size=2",
    )
    assert code == 200
    assert body["total"] > 2
    assert len(body["items"]) == 2
    assert all(item["category"] == "price" for item in body["items"])

    code, body = await asgi_request(app, "GET", "/api/factors/definitions/ret_1d")
    assert code == 200
    assert body["factor_id"] == "ret_1d"
    assert body["version"] == 1
    assert "." in body["formula_ref"]

    code, body = await asgi_request(app, "GET", "/api/factors/definitions/missing")
    assert code == 404
    assert body["detail"]["code"] == "FACTOR_DEFINITION_NOT_FOUND"

    code, body = await asgi_request(
        app,
        "POST",
        "/api/factors/validate",
        {"market": "CN", "factor_specs": [{"factor_id": "momentum_composite"}]},
    )
    assert code == 200 and body["valid"] is True
    assert body["execution_order"].index("ret_20d") < body["execution_order"].index(
        "momentum_composite"
    )

    code, body = await asgi_request(
        app,
        "POST",
        "/api/factors/validate",
        {"market": "CN", "factor_specs": [{"factor_id": "unknown_factor"}]},
    )
    assert code == 200 and body["valid"] is False
    assert body["issues"][0]["code"] == "FACTOR_NOT_FOUND"

    code, _ = await asgi_request(
        app, "GET", "/api/factors/definitions?page_size=201"
    )
    assert code == 422


async def test_compute_returns_202_deduplicates_force_reruns_and_scopes_jobs(monkeypatch):
    app, database, _, active_user = await make_api(monkeypatch)
    payload = compute_payload()
    monkeypatch.setenv("FACTOR_FEATURE_ENABLED", "false")
    code, body = await asgi_request(app, "POST", "/api/factors/compute", payload)
    assert code == 404
    assert body["detail"]["code"] == "FACTOR_FEATURE_DISABLED"
    assert database["domain_tasks"].documents == []

    monkeypatch.setenv("FACTOR_FEATURE_ENABLED", "true")
    code, first = await asgi_request(app, "POST", "/api/factors/compute", payload)
    assert code == 202
    assert first["deduplicated"] is False

    code, duplicate = await asgi_request(app, "POST", "/api/factors/compute", payload)
    assert code == 202
    assert duplicate["job_id"] == first["job_id"]
    assert duplicate["task_id"] == first["task_id"]
    assert duplicate["deduplicated"] is True

    forced_payload = compute_payload(force_recompute=True)
    code, forced = await asgi_request(
        app, "POST", "/api/factors/compute", forced_payload
    )
    assert code == 202
    assert forced["job_id"] != first["job_id"]
    assert forced["task_id"] != first["task_id"]
    assert forced["request_checksum"] != first["request_checksum"]
    assert len(database["domain_tasks"].documents) == 2

    code, body = await asgi_request(
        app, "GET", f"/api/factors/jobs/{first['job_id']}"
    )
    assert code == 200
    assert body["user_id"] == "owner"
    assert body["request"]["start_date"] == "2024-01-01"

    active_user["id"] = "other"
    code, body = await asgi_request(
        app, "GET", f"/api/factors/jobs/{first['job_id']}"
    )
    assert code == 404
    assert body["detail"]["code"] == "FACTOR_JOB_NOT_FOUND"

    active_user["id"] = "owner"
    invalid = compute_payload(
        factor_specs=[{"factor_id": "unknown_factor", "version": 1}]
    )
    code, body = await asgi_request(app, "POST", "/api/factors/compute", invalid)
    assert code == 422
    assert body["detail"]["code"] == "FACTOR_REQUEST_INVALID"


async def test_snapshot_and_value_pages_are_owner_scoped_ready_only_and_finite(monkeypatch):
    app, database, _, active_user = await make_api(monkeypatch)
    now = datetime(2025, 1, 6, 15, 30, tzinfo=timezone.utc)
    ready = FactorSnapshot(
        snapshot_id="a" * 64,
        user_id="owner",
        job_id="job-ready",
        task_id="task-ready",
        market=Market.CN,
        trade_date=date(2025, 1, 6),
        as_of=now,
        universe_snapshot_id="cn-fixed",
        factor_set_checksum="b" * 64,
        request_checksum="c" * 64,
        status=FactorSnapshotStatus.READY,
        expected_row_count=3,
        expected_factor_count=2,
        row_count=3,
        factor_count=2,
        source_versions={"daily_bars": "v1"},
        values_checksum="d" * 64,
        published_at=now,
    )
    other = ready.model_copy(
        update={"snapshot_id": "e" * 64, "user_id": "other"}
    )
    failed = FactorSnapshot(
        snapshot_id="f" * 64,
        user_id="owner",
        job_id="job-failed",
        task_id="task-failed",
        market=Market.CN,
        trade_date=date(2025, 1, 6),
        as_of=now,
        universe_snapshot_id="cn-fixed",
        factor_set_checksum="1" * 64,
        request_checksum="2" * 64,
        status=FactorSnapshotStatus.FAILED,
        expected_row_count=3,
        expected_factor_count=2,
        source_versions={"daily_bars": "v1"},
        error={"code": "fixture"},
    )
    database["factor_snapshots"].documents.extend(
        [item.model_dump(mode="json") for item in (ready, other, failed)]
    )
    for index, symbol in enumerate(("000001", "000002", "000003"), 1):
        database["factor_values"].documents.append(
            {
                "snapshot_id": ready.snapshot_id,
                "user_id": "owner",
                "market": "CN",
                "symbol": symbol,
                "trade_date": "2025-01-06",
                "values": {
                    "ret_1d": float("nan") if index == 1 else index / 100,
                    "ret_5d": index / 10,
                },
                "quality": {"ret_1d": None, "ret_5d": "ok"},
                "created_at": now,
            }
        )

    code, body = await asgi_request(
        app, "GET", "/api/factors/snapshots?page=1&page_size=1"
    )
    assert code == 200
    assert body["total"] == 1
    assert body["items"][0]["snapshot_id"] == ready.snapshot_id

    code, body = await asgi_request(
        app,
        "GET",
        f"/api/factors/snapshots/{ready.snapshot_id}/values?factors=ret_1d&page=1&page_size=2",
    )
    assert code == 200
    assert body["total"] == 3
    assert len(body["items"]) == 2
    assert set(body["items"][0]["values"]) == {"ret_1d"}
    assert body["items"][0]["values"]["ret_1d"] is None
    assert body["items"][0]["quality"]["ret_1d"] == "non_finite_persisted_value"

    code, body = await asgi_request(
        app,
        "GET",
        f"/api/factors/snapshots/{ready.snapshot_id}/values?page=2&page_size=2",
    )
    assert code == 200 and len(body["items"]) == 1

    active_user["id"] = "other"
    code, body = await asgi_request(
        app, "GET", f"/api/factors/snapshots/{ready.snapshot_id}/values"
    )
    assert code == 404
    assert body["detail"]["code"] == "FACTOR_SNAPSHOT_NOT_FOUND"

    active_user["id"] = "owner"
    code, _ = await asgi_request(
        app, "GET", f"/api/factors/snapshots/{failed.snapshot_id}/values"
    )
    assert code == 404
    code, _ = await asgi_request(
        app, "GET", f"/api/factors/snapshots/{ready.snapshot_id}/values?page_size=201"
    )
    assert code == 422


async def test_storage_failures_use_stable_non_sensitive_error(monkeypatch):
    app, _, _, _ = await make_api(monkeypatch)

    class BrokenService:
        async def get_job(self, **kwargs):
            del kwargs
            raise PyMongoError("mongodb://user:secret@private-host")

    app.dependency_overrides[get_factor_api_service] = lambda: BrokenService()
    code, body = await asgi_request(app, "GET", "/api/factors/jobs/job-1")
    assert code == 503
    assert body["detail"] == {
        "code": "FACTOR_STORE_UNAVAILABLE",
        "message": "Factor storage is unavailable",
    }
    assert "secret" not in json.dumps(body)
