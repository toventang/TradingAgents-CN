from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException

import pytest

from app.repositories.backtest_repository import BacktestRepository
from app.repositories.domain_task_repository import DomainTaskRepository
from app.models.domain_task import DomainTaskType
from app.routers.auth_db import get_current_user
from app.routers.backtests import get_parameter_search_service, router
from app.services.backtest.parameter_search import (
    ParameterSearchRunner,
    ParameterSearchRepository,
    ParameterSearchRequest,
    ParameterSearchService,
)
from app.services.backtest.ledger import BacktestEquityDailyRecord
from app.services.domain_tasks import DomainTaskContext, DomainTaskHandlerRegistry
from app.workers.handlers.backtest import register_backtest_handler
from tests.integration.test_backtest_api import (
    ApiFakeDatabase,
    PublishedStrategyRepository,
    asgi_request,
    create_payload,
    decoded,
)


pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def search_payload(**updates):
    payload = {
        "name": "稳健参数实验",
        "base_request": create_payload(
            start_date="2024-01-01",
            end_date="2024-06-30",
            notes="parameter search fixture",
        ),
        "axes": [
            {"name": "lookback", "values": [10, 20]},
            {"name": "threshold", "values": ["0.10", "0.20"]},
        ],
        "mode": "split",
        "split": {"train_end": "2024-03-15", "validation_end": "2024-05-15"},
        "combination_limit": 100,
    }
    payload.update(updates)
    return payload


async def make_api():
    database = ApiFakeDatabase()
    backtests = BacktestRepository(database)
    tasks = DomainTaskRepository(database)
    service = ParameterSearchService(
        repository=ParameterSearchRepository(database),
        backtests=backtests,
        tasks=tasks,
        strategies=PublishedStrategyRepository(),
    )
    active_user = {"id": "owner"}
    app = FastAPI()
    app.include_router(router, prefix="/api")

    async def current_user_override():
        if active_user["id"] is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return active_user

    app.dependency_overrides[get_current_user] = current_user_override
    app.dependency_overrides[get_parameter_search_service] = lambda: service
    return app, database, service, active_user


async def test_create_is_durable_idempotent_and_uses_parameter_search_task_payload():
    app, database, _, active_user = await make_api()
    active_user["id"] = None
    code, _, _ = await asgi_request(app, "GET", "/api/backtests/parameter-search")
    assert code == 401
    active_user["id"] = "owner"

    headers = {"idempotency-key": "parameter-fixture"}
    code, raw, _ = await asgi_request(
        app, "POST", "/api/backtests/parameter-search", search_payload(), headers
    )
    accepted = decoded(raw)
    assert code == 202
    assert accepted["status"] == "queued"
    assert accepted["total_combinations"] == 4
    assert accepted["deduplicated"] is False
    assert "NO_AUTOMATIC_PUBLICATION" in accepted["research_notice"]

    code, raw, _ = await asgi_request(
        app, "POST", "/api/backtests/parameter-search", search_payload(), headers
    )
    duplicate = decoded(raw)
    assert code == 202
    assert duplicate["search_id"] == accepted["search_id"]
    assert duplicate["task_id"] == accepted["task_id"]
    assert duplicate["deduplicated"] is True

    tasks = database[DomainTaskRepository.TASKS_COLLECTION].documents
    assert len(tasks) == 1
    assert tasks[0]["task_type"] == "backtest"
    assert tasks[0]["payload"] == {"parameter_search_id": accepted["search_id"]}
    searches = database[ParameterSearchRepository.SEARCHES_COLLECTION].documents
    assert searches[0]["shared_input_checksum"]
    assert len(searches[0]["windows"]) == 3
    assert "published" not in searches[0]


async def test_owner_scoped_list_detail_results_and_cancel_are_not_shadowed_by_run_route():
    app, _, _, active_user = await make_api()
    code, raw, _ = await asgi_request(
        app, "POST", "/api/backtests/parameter-search", search_payload()
    )
    accepted = decoded(raw)
    assert code == 202
    search_id = accepted["search_id"]

    code, raw, _ = await asgi_request(
        app, "GET", "/api/backtests/parameter-search?page=1&page_size=1"
    )
    page = decoded(raw)
    assert code == 200 and page["total"] == 1 and len(page["items"]) == 1

    code, raw, _ = await asgi_request(
        app, "GET", f"/api/backtests/parameter-search/{search_id}"
    )
    detail = decoded(raw)
    assert code == 200 and detail["task"]["task_id"] == accepted["task_id"]
    assert detail["search"]["research_notice"].startswith("RESEARCH_ONLY")

    code, raw, _ = await asgi_request(
        app, "GET", f"/api/backtests/parameter-search/{search_id}/results"
    )
    results = decoded(raw)
    assert code == 200 and results["items"] == [] and results["total"] == 0

    active_user["id"] = "another-owner"
    for method, path in (
        ("GET", f"/api/backtests/parameter-search/{search_id}"),
        ("GET", f"/api/backtests/parameter-search/{search_id}/results"),
        ("POST", f"/api/backtests/parameter-search/{search_id}/cancel"),
    ):
        code, _, _ = await asgi_request(app, method, path)
        assert code == 404

    active_user["id"] = "owner"
    code, raw, _ = await asgi_request(
        app, "POST", f"/api/backtests/parameter-search/{search_id}/cancel"
    )
    cancelled = decoded(raw)
    assert code == 202
    assert cancelled["search_status"] == "cancelled"
    assert cancelled["task_status"] == "cancelled"


async def test_api_rejects_excessive_grid_and_invalid_walk_forward_window():
    app, _, _, _ = await make_api()
    excessive = search_payload(
        axes=[{"name": "lookback", "values": list(range(101))}]
    )
    code, _, _ = await asgi_request(
        app, "POST", "/api/backtests/parameter-search", excessive
    )
    assert code == 422

    invalid_walk = search_payload(
        mode="walk_forward",
        split=None,
        walk_forward={
            "train_sessions": 120,
            "validation_sessions": 20,
            "test_sessions": 20,
            "step_sessions": 20,
        },
    )
    code, raw, _ = await asgi_request(
        app, "POST", "/api/backtests/parameter-search", invalid_walk
    )
    assert code == 422
    assert decoded(raw)["detail"]["code"] == "PARAMETER_SEARCH_INVALID"


async def test_worker_dispatches_independent_child_runs_and_persists_oos_evidence():
    app, database, service, _ = await make_api()
    del app
    accepted = await service.create(
        user_id="owner", request=ParameterSearchRequest.model_validate(search_payload())
    )

    async def execute_child(*, run_id, user_id, task_id, report_progress, is_cancelled):
        del is_cancelled
        run = await service.backtests.mark_run_running(
            run_id, user_id=user_id, task_id=task_id
        )
        for trade_date, equity in (
            (date(2024, 2, 1), Decimal("101")),
            (date(2024, 4, 1), Decimal("103")),
            (date(2024, 6, 3), Decimal("104")),
        ):
            database[BacktestRepository.EQUITY_COLLECTION].documents.append(
                BacktestEquityDailyRecord(
                    run_id=run_id,
                    user_id=user_id,
                    trade_date=trade_date,
                    cash=equity,
                    market_value=Decimal("0"),
                    equity=equity,
                    cumulative_return=equity / Decimal("100") - 1,
                    drawdown=Decimal("0"),
                ).model_dump(mode="json")
            )
        await report_progress(1.0, "child_succeeded", None)
        return await service.backtests.mark_run_succeeded(
            run.run_id, user_id=user_id, summary={"completed_days": 3}
        )

    runner = ParameterSearchRunner(
        repository=service.repository,
        backtests=service.backtests,
        child_executor=execute_child,
    )
    registry = DomainTaskHandlerRegistry()
    handler = register_backtest_handler(
        SimpleNamespace(),
        parameter_search_executor=runner.run,
        registry=registry,
    )

    async def progress(value, stage, message=None):
        del value, stage, message

    async def not_cancelled():
        return False

    result_ref = await handler(
        {"parameter_search_id": accepted.search_id},
        DomainTaskContext(
            task_id=accepted.task_id,
            user_id="owner",
            task_type=DomainTaskType.BACKTEST,
            attempt=1,
            max_attempts=3,
        ),
        progress,
        not_cancelled,
    )

    assert result_ref.collection == ParameterSearchRepository.SEARCHES_COLLECTION
    detail = await service.detail(user_id="owner", search_id=accepted.search_id)
    assert detail.search.status.value == "succeeded"
    assert detail.search.completed_combinations == 4
    results = await service.results(
        user_id="owner", search_id=accepted.search_id, page=1, page_size=20
    )
    assert len(results.items) == 4
    assert sum(item.selected_candidate for item in results.items) == 1
    assert all(item.validation_mean_return is not None for item in results.items)
    assert all(item.test_mean_return is not None for item in results.items)
    child_runs = database[BacktestRepository.RUNS_COLLECTION].documents
    assert len(child_runs) == 4
    shared = {
        tuple(run["input_versions"]["parameter_search_shared_input"])
        for run in child_runs
    }
    assert len(shared) == 1
