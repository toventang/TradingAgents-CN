"""Integration contract tests for the authenticated alert HTTP API."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from fastapi import FastAPI
from pymongo import ReturnDocument

from app.models.alert import (
    AlertEvent,
    AlertEventKind,
    AlertQualityStatus,
    AlertSeverity,
    ConditionState,
)
from app.repositories.alert_repository import AlertRepository
from app.routers.alerts import get_alert_api_service, router
from app.routers.auth_db import get_current_user
from app.services.alerts.api_service import AlertApiService
from app.services.alerts.evaluator import AlertObservation


pytestmark = [pytest.mark.asyncio, pytest.mark.integration]
NOW = datetime(2026, 8, 17, 2, 0, tzinfo=timezone.utc)


def _get(document, path):
    value = document
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _matches(document, query):
    for key, expected in query.items():
        if key == "$or":
            if not any(_matches(document, item) for item in expected):
                return False
            continue
        if key == "$and":
            if not all(_matches(document, item) for item in expected):
                return False
            continue
        actual = _get(document, key)
        if isinstance(expected, dict):
            for operator, operand in expected.items():
                if operator == "$in" and actual not in operand:
                    return False
                if operator == "$nin" and actual in operand:
                    return False
                if operator == "$lt" and not actual < operand:
                    return False
                if operator == "$lte" and not actual <= operand:
                    return False
                if operator == "$gt" and not actual > operand:
                    return False
                if operator == "$gte" and not actual >= operand:
                    return False
                if operator == "$elemMatch":
                    if not isinstance(actual, list) or not any(_matches(item, operand) for item in actual):
                        return False
            continue
        if actual != expected:
            return False
    return True


class Cursor:
    def __init__(self, documents):
        self.documents = [deepcopy(item) for item in documents]
        self.offset = 0
        self.maximum = None

    def sort(self, spec, direction=None):
        fields = spec if isinstance(spec, list) else [(spec, direction)]
        for field, order in reversed(fields):
            self.documents.sort(
                key=lambda item: (_get(item, field) is not None, _get(item, field)),
                reverse=order < 0,
            )
        return self

    def skip(self, count):
        self.offset = count
        return self

    def limit(self, count):
        self.maximum = count
        return self

    async def to_list(self, length=None):
        values = self.documents[self.offset :]
        maximum = self.maximum if self.maximum is not None else length
        return deepcopy(values if maximum is None else values[:maximum])

    def __aiter__(self):
        values = self.documents[self.offset :]
        if self.maximum is not None:
            values = values[: self.maximum]
        self.iterator = iter(values)
        return self

    async def __anext__(self):
        try:
            return next(self.iterator)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


def _apply(document, update):
    document.update(deepcopy(update.get("$set", {})))
    for key, value in update.get("$inc", {}).items():
        document[key] = document.get(key, 0) + value


class Collection:
    def __init__(self):
        self.documents = []
        self.indexes = []

    async def create_index(self, keys, **options):
        self.indexes.append((keys, options))
        return options.get("name")

    async def update_one(self, query, update, upsert=False):
        for document in self.documents:
            if _matches(document, query):
                _apply(document, update)
                return SimpleNamespace(upserted_id=None, modified_count=1)
        if not upsert:
            return SimpleNamespace(upserted_id=None, modified_count=0)
        document = deepcopy(update.get("$setOnInsert", {}))
        _apply(document, update)
        self.documents.append(document)
        return SimpleNamespace(upserted_id=len(self.documents), modified_count=0)

    async def update_many(self, query, update):
        count = 0
        for document in self.documents:
            if _matches(document, query):
                _apply(document, update)
                count += 1
        return SimpleNamespace(modified_count=count)

    async def find_one(self, query, projection=None, sort=None):
        values = [item for item in self.documents if _matches(item, query)]
        if sort:
            values = Cursor(values).sort(sort).documents
        return deepcopy(values[0]) if values else None

    async def find_one_and_update(
        self, query, update, sort=None, return_document=ReturnDocument.BEFORE
    ):
        del sort
        for document in self.documents:
            if _matches(document, query):
                before = deepcopy(document)
                _apply(document, update)
                return deepcopy(document if return_document == ReturnDocument.AFTER else before)
        return None

    def find(self, query, projection=None):
        del projection
        return Cursor(item for item in self.documents if _matches(item, query))

    async def count_documents(self, query):
        return sum(_matches(item, query) for item in self.documents)


class Database:
    def __init__(self):
        self.collections = {}

    def __getitem__(self, name):
        return self.collections.setdefault(name, Collection())


class PreviewLoader:
    async def load(self, request):
        return {
            target: AlertObservation(
                current_value="11",
                previous_value="9",
                quote_time=NOW,
                ingested_at=NOW,
                source="fixture",
                quality_status=AlertQualityStatus.VALID,
            )
            for target in request.targets
        }


class CapturingNotifications:
    def __init__(self):
        self.calls = []

    async def create_and_publish(self, payload, *, publish_realtime=True):
        self.calls.append((payload, publish_realtime))
        return "notification-1"


def rule_payload(**updates):
    payload = {
        "name": "price breakout",
        "description": "deterministic fixture",
        "enabled": False,
        "alert_type": "price_above",
        "scope": {"scope_type": "symbol", "symbol": "600000"},
        "market": "CN",
        "trigger": {
            "condition": {
                "type": "compare",
                "left": {"kind": "current_value"},
                "operator": "gt",
                "right": {"kind": "constant", "value": "10"},
            }
        },
        "evaluation_mode": "edge",
        "frequency_seconds": 60,
        "active_schedule": {"schedule_type": "market_hours"},
    }
    payload.update(updates)
    return payload


async def request(app, method, target, payload=None, headers=None):
    parsed = urlsplit(target)
    sent = False
    messages = []
    body = b"" if payload is None else json.dumps(payload).encode()

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        messages.append(message)

    raw_headers = [(key.lower().encode(), value.encode()) for key, value in (headers or {}).items()]
    if payload is not None:
        raw_headers.append((b"content-type", b"application/json"))
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
            "headers": raw_headers,
            "client": ("test", 1),
            "server": ("test", 80),
        },
        receive,
        send,
    )
    start = next(item for item in messages if item["type"] == "http.response.start")
    response = b"".join(
        item.get("body", b"") for item in messages if item["type"] == "http.response.body"
    )
    return start["status"], json.loads(response or b"null")


async def make_api(*, quota=200):
    database = Database()
    notifications = CapturingNotifications()
    service = AlertApiService(
        database,
        repository=AlertRepository(database),
        snapshot_loader=PreviewLoader(),
        notifications=notifications,
        clock=lambda: NOW,
        max_rules_per_user=quota,
    )
    active_user = {"id": "owner"}
    app = FastAPI()
    app.include_router(router, prefix="/api")

    async def user_override():
        return active_user

    app.dependency_overrides[get_current_user] = user_override
    app.dependency_overrides[get_alert_api_service] = lambda: service
    return app, database, service, notifications, active_user


async def test_rule_crud_ownership_versions_quota_and_soft_delete():
    app, database, _, _, active_user = await make_api(quota=1)
    code, created = await request(app, "POST", "/api/alerts/rules", rule_payload())
    assert code == 201
    assert created["user_id"] == "owner" and created["version"] == 1
    rule_id = created["rule_id"]

    code, body = await request(app, "GET", "/api/alerts/rules?page_size=10")
    assert code == 200 and body["total"] == 1
    code, detail = await request(app, "GET", f"/api/alerts/rules/{rule_id}")
    assert code == 200 and detail["rule"]["rule_id"] == rule_id

    code, body = await request(app, "POST", "/api/alerts/rules", rule_payload(name="second"))
    assert code == 409 and body["detail"]["code"] == "ALERT_QUOTA_EXCEEDED"

    code, body = await request(
        app,
        "PUT",
        f"/api/alerts/rules/{rule_id}",
        {"name": "renamed"},
        {"if-match": '"9"'},
    )
    assert code == 409 and body["detail"]["code"] == "ALERT_RULE_VERSION_CONFLICT"
    code, updated = await request(
        app,
        "PUT",
        f"/api/alerts/rules/{rule_id}",
        {"name": "renamed"},
        {"if-match": 'W/"1"'},
    )
    assert code == 200 and updated["name"] == "renamed" and updated["version"] == 2

    active_user["id"] = "other"
    code, body = await request(app, "GET", f"/api/alerts/rules/{rule_id}")
    assert code == 403 and body["detail"]["code"] == "ALERT_RULE_FORBIDDEN"
    active_user["id"] = "owner"

    code, deleted = await request(
        app,
        "DELETE",
        f"/api/alerts/rules/{rule_id}",
        headers={"if-match": '"2"'},
    )
    assert code == 200 and deleted["events_retained"] is True
    assert len(database["alert_rules"].documents) == 1
    code, body = await request(app, "GET", f"/api/alerts/rules/{rule_id}")
    assert code == 404 and body["detail"]["code"] == "ALERT_RULE_NOT_FOUND"


async def test_validation_preview_enable_disable_and_test_notification_contracts():
    app, _, _, notifications, _ = await make_api()
    invalid = rule_payload(frequency_seconds=10)
    code, body = await request(app, "POST", "/api/alerts/validate", invalid)
    assert code == 200 and body["valid"] is False
    assert body["error_code"] == "ALERT_FREQUENCY_TOO_HIGH"

    code, preview = await request(app, "POST", "/api/alerts/preview", rule_payload())
    assert code == 200
    assert preview["state_persisted"] is False
    assert preview["notification_sent"] is False
    assert preview["results"][0]["condition_state"] == "true"

    code, created = await request(app, "POST", "/api/alerts/rules", rule_payload())
    rule_id = created["rule_id"]
    code, enabled = await request(
        app,
        "POST",
        f"/api/alerts/rules/{rule_id}/enable",
        {"version": 1},
    )
    assert code == 200 and enabled["enabled"] is True and enabled["version"] == 2
    code, disabled = await request(
        app,
        "POST",
        f"/api/alerts/rules/{rule_id}/disable",
        {"version": 2},
    )
    assert code == 200 and disabled["enabled"] is False

    code, result = await request(
        app, "POST", f"/api/alerts/rules/{rule_id}/test-notification"
    )
    assert code == 200 and result["is_test"] is True
    payload, _ = notifications.calls[0]
    assert payload.title.startswith("[测试]")
    assert payload.metadata["is_test"] is True
    assert payload.metadata["source"] == "alert_test"


async def test_event_filters_acknowledgement_health_and_owner_isolation():
    app, database, _, _, active_user = await make_api()
    code, created = await request(app, "POST", "/api/alerts/rules", rule_payload())
    rule_id = created["rule_id"]
    critical = AlertEvent(
        rule_id=rule_id,
        rule_version=1,
        condition_version=1,
        user_id="owner",
        scope_key="CN:600000",
        symbol="600000",
        kind=AlertEventKind.TRIGGERED,
        severity=AlertSeverity.CRITICAL,
        direction="enter",
        condition_state=ConditionState.TRUE,
        current_value="11",
        previous_value="9",
        quote_time=NOW,
        ingested_at=NOW,
        evaluated_at=NOW + timedelta(seconds=1),
        source="fixture",
        latency_seconds="1",
        quality_status=AlertQualityStatus.VALID,
        fingerprint="a" * 64,
        created_at=NOW + timedelta(seconds=1),
    )
    other = critical.model_copy(
        update={"event_id": "3dfbe928-b089-47ba-b39d-cd6eaedfc991", "user_id": "other", "fingerprint": "b" * 64}
    )
    database["alert_events"].documents.extend(
        [critical.model_dump(mode="json"), other.model_dump(mode="json")]
    )
    database["alert_evaluation_runs"].documents.append(
        {"run_id": "run-1", "status": "completed", "started_at": NOW.isoformat(), "completed_at": NOW.isoformat()}
    )
    database["market_quotes"].documents.append(
        {"symbol": "600000", "source": "fixture", "ingested_at": NOW.isoformat()}
    )

    code, page = await request(
        app, "GET", "/api/alerts/events?symbol=600000&severity=critical"
    )
    assert code == 200 and page["total"] == 1
    assert page["items"][0]["user_id"] == "owner"
    code, acknowledged = await request(
        app, "POST", f"/api/alerts/events/{critical.event_id}/ack"
    )
    assert code == 200 and acknowledged["acknowledged_at"] is not None

    active_user["id"] = "other"
    code, body = await request(app, "POST", f"/api/alerts/events/{critical.event_id}/ack")
    assert code == 403 and body["detail"]["code"] == "ALERT_RULE_FORBIDDEN"
    active_user["id"] = "owner"
    code, health = await request(app, "GET", "/api/alerts/health")
    assert code == 200 and health["status"] == "healthy"
    assert health["evaluation_batches"]["recent_count"] == 1
    assert health["data_sources"]["market_quotes"]["available"] is True
