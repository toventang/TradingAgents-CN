from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from fastapi import FastAPI, HTTPException

from app.models.strategy import StrategySignal
from app.models.symbol import Market
from app.repositories.domain_task_repository import DomainTaskRepository
from app.repositories.strategy_repository import StrategyRepository
from app.routers.auth_db import get_current_user
from app.routers.strategies import get_strategy_api_service, router
from app.services.strategies.api_service import StrategyApiService
from app.services.strategies.templates.seeder import seed_system_strategy_templates
from app.services.strategies.version_service import StrategyVersionService
from tests.integration.strategy_api_helpers import asgi_request
from tests.strategy_fakes import FakeDatabase
from tests.unit.strategies.dsl_fixtures import valid_definition


pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
NOW = datetime(2025, 6, 3, 8, tzinfo=timezone.utc)


async def make_api(*, seed_templates=False):
    database = FakeDatabase()
    repository = StrategyRepository(database)
    task_repository = DomainTaskRepository(database)
    await task_repository.ensure_indexes()
    identifiers = iter(f"api-id-{index}" for index in range(1, 100))
    service = StrategyApiService(
        repository=repository,
        task_repository=task_repository,
        version_service=StrategyVersionService(
            repository,
            clock=lambda: NOW,
            id_factory=lambda: next(identifiers),
        ),
    )
    if seed_templates:
        await seed_system_strategy_templates(repository)
    active_user = {"id": "alice"}
    app = FastAPI()
    app.include_router(router, prefix="/api")

    async def user_override():
        if active_user["id"] is None:
            raise HTTPException(401, detail="Not authenticated")
        return active_user

    app.dependency_overrides[get_current_user] = user_override
    app.dependency_overrides[get_strategy_api_service] = lambda: service
    return app, database, repository, task_repository, active_user


def create_payload(**updates):
    payload = {
        "name": "My strategy",
        "description": "Owner-scoped draft",
        "tags": ["test"],
        "kind": "portfolio",
        "market": "CN",
        "definition": valid_definition(),
    }
    payload.update(updates)
    return payload


async def create_draft(app):
    code, body = await asgi_request(app, "POST", "/api/strategies", create_payload())
    assert code == 201, body
    return body


async def test_auth_template_catalog_and_owner_isolation():
    app, _, _, _, active_user = await make_api(seed_templates=True)
    active_user["id"] = None
    code, _ = await asgi_request(app, "GET", "/api/strategies/templates")
    assert code == 401

    active_user["id"] = "alice"
    code, templates = await asgi_request(app, "GET", "/api/strategies/templates")
    assert code == 200
    assert len(templates) == 14
    assert {item["template_id"] for item in templates} >= {
        "value_quality",
        "defensive_risk_off",
    }
    assert templates[0]["strategy_id"].startswith("system-template:")
    assert templates[0]["parameter_ranges"]

    created = await create_draft(app)
    strategy_id = created["strategy"]["strategy_id"]
    code, listing = await asgi_request(app, "GET", "/api/strategies")
    assert code == 200
    assert len(listing["items"]) == 15

    active_user["id"] = "bob"
    code, body = await asgi_request(app, "GET", f"/api/strategies/{strategy_id}")
    assert code == 404
    assert body["detail"]["code"] == "STRATEGY_NOT_FOUND"


async def test_validate_publish_version_clone_and_durable_signal_job():
    app, database, repository, task_repository, active_user = await make_api(
        seed_templates=True
    )
    created = await create_draft(app)
    strategy_id = created["strategy"]["strategy_id"]
    version_id = created["version"]["strategy_version_id"]

    code, validation = await asgi_request(
        app,
        "POST",
        "/api/strategies/validate",
        {"strategy_version_id": version_id},
    )
    assert code == 200 and validation["valid"] is True
    assert validation["factor_dependencies"]

    code, published = await asgi_request(
        app,
        "POST",
        f"/api/strategies/{strategy_id}/versions/{version_id}/publish",
    )
    assert code == 200, published
    assert published["status"] == "published"

    code, body = await asgi_request(
        app,
        "PUT",
        f"/api/strategies/{strategy_id}/versions/{version_id}",
        {
            "expected_checksum": published["checksum"],
            "definition": valid_definition(),
        },
    )
    assert code == 404
    assert body["detail"]["code"] == "STRATEGY_DRAFT_NOT_FOUND"

    signal_request = {
        "universe_snapshot_id": "universe-1",
        "factor_snapshot_ids": ["factor-1"],
        "as_of": "2025-06-03T08:00:00Z",
        "idempotency_key": "signal-run-1",
    }
    code, task = await asgi_request(
        app, "POST", f"/api/strategies/{version_id}/signals", signal_request
    )
    assert code == 202, task
    assert task["task_type"] == "strategy_run"
    assert task["payload"]["strategy_version_id"] == version_id
    code, retried = await asgi_request(
        app, "POST", f"/api/strategies/{version_id}/signals", signal_request
    )
    assert code == 202 and retried["task_id"] == task["task_id"]
    assert len(database[task_repository.TASKS_COLLECTION].documents) == 1
    conflicting_request = dict(signal_request)
    conflicting_request["as_of"] = "2025-06-03T09:00:00Z"
    code, body = await asgi_request(
        app,
        "POST",
        f"/api/strategies/{version_id}/signals",
        conflicting_request,
    )
    assert code == 409
    assert body["detail"]["code"] == "TASK_IDEMPOTENCY_CONFLICT"

    code, next_version = await asgi_request(
        app,
        "POST",
        f"/api/strategies/{strategy_id}/versions",
        {"parent_version_id": version_id, "change_summary": "v2"},
    )
    assert code == 200 and next_version["version"] == 2

    template_id = "system-template:value_quality"
    template_version = "system-template:value_quality:v1"
    code, clone = await asgi_request(
        app,
        "POST",
        f"/api/strategies/{template_id}/clone",
        {"source_version_id": template_version, "name": "My value clone"},
    )
    assert code == 201, clone
    assert clone["strategy"]["user_id"] == "alice"
    assert clone["strategy"]["clone_source"]["strategy_version_id"] == template_version

    active_user["id"] = "bob"
    code, _ = await asgi_request(
        app, "POST", f"/api/strategies/{version_id}/signals", signal_request
    )
    assert code == 404


async def test_signal_query_is_owner_scoped_and_paginated():
    app, database, repository, _, active_user = await make_api()
    for index, (owner, symbol) in enumerate(
        (("alice", "000001"), ("alice", "000002"), ("bob", "000003")), start=1
    ):
        signal = StrategySignal(
            signal_id=f"signal-{index}",
            user_id=owner,
            strategy_version_id="version-1",
            universe_snapshot_id="universe-1",
            market=Market.CN,
            symbol=symbol,
            signal_date=date(2025, 6, 3),
            signal_type="buy",
            reason_codes=("ENTRY_SELECTED",),
            input_contributions={},
            as_of=NOW,
            created_at=NOW,
        )
        database[repository.SIGNALS_COLLECTION].documents.append(
            signal.model_dump(mode="json")
        )

    code, page = await asgi_request(
        app,
        "GET",
        "/api/strategies/signals?strategy_version_id=version-1&signal_date=2025-06-03&page=1&page_size=1",
    )
    assert code == 200
    assert page["total"] == 2 and len(page["items"]) == 1
    assert page["items"][0]["user_id"] == "alice"

    active_user["id"] = "bob"
    code, bob_page = await asgi_request(
        app, "GET", "/api/strategies/signals?strategy_version_id=version-1"
    )
    assert code == 200 and bob_page["total"] == 1
