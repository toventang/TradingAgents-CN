from __future__ import annotations

import json
from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from fastapi import FastAPI, HTTPException

from app.models.backtest import BrokerOrderStatus, FeeBreakdown, OrderSide
from app.models.strategy import StrategyVersionStatus
from app.models.symbol import Market
from app.repositories.backtest_repository import BacktestRepository
from app.repositories.domain_task_repository import DomainTaskRepository
from app.routers.auth_db import get_current_user
from app.routers.backtests import get_backtest_api_service, router
from app.services.backtest.api_service import BacktestApiService
from app.services.backtest.ledger import (
    BacktestEquityDailyRecord,
    BacktestEventRecord,
    BacktestOrderRecord,
    BacktestPositionDailyRecord,
    BacktestRunRecord,
    BacktestRunStatus,
    BacktestTradeRecord,
)
from tests.unit.domain_tasks.fakes import (
    FakeCollection,
    _apply_update,
    _matches,
)


pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class ApiFakeCollection(FakeCollection):
    async def update_one(self, query, update, upsert=False):
        async with self.lock:
            for document in self.documents:
                if _matches(document, query):
                    _apply_update(document, update)
                    return SimpleNamespace(upserted_id=None, matched_count=1)
            if not upsert:
                return SimpleNamespace(upserted_id=None, matched_count=0)
            document = deepcopy(query)
            document.update(deepcopy(update.get("$setOnInsert", {})))
            _apply_update(document, update)
            self.documents.append(document)
            return SimpleNamespace(
                upserted_id=f"{self.name}-{len(self.documents)}", matched_count=0
            )

    async def count_documents(self, query):
        return sum(1 for document in self.documents if _matches(document, query))


class ApiFakeDatabase:
    def __init__(self):
        self.collections = {}

    def __getitem__(self, name):
        return self.collections.setdefault(name, ApiFakeCollection(name))


class PublishedStrategyRepository:
    async def get_version(self, strategy_version_id, *, user_id, include_system=True):
        del user_id, include_system
        if strategy_version_id == "missing":
            return None
        return SimpleNamespace(
            strategy_version_id=strategy_version_id,
            status=StrategyVersionStatus.PUBLISHED,
            market=Market.CN,
            checksum="a" * 64,
            factor_dependencies=(),
            skill_dependencies=(),
        )


async def asgi_request(app, method, target, payload=None, headers=None):
    parsed = urlsplit(target)
    request_sent = False
    messages = []
    body = b"" if payload is None else json.dumps(payload).encode()
    request_headers = [] if payload is None else [(b"content-type", b"application/json")]
    request_headers.extend(
        (key.lower().encode(), value.encode()) for key, value in (headers or {}).items()
    )

    async def receive():
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": body, "more_body": False}
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
            "headers": request_headers,
            "client": ("test", 1234),
            "server": ("test", 80),
        },
        receive,
        send,
    )
    response_start = next(
        item for item in messages if item["type"] == "http.response.start"
    )
    response_body = b"".join(
        item.get("body", b"")
        for item in messages
        if item["type"] == "http.response.body"
    )
    response_headers = {
        key.decode().lower(): value.decode()
        for key, value in response_start.get("headers", ())
    }
    return response_start["status"], response_body, response_headers


def decoded(response_body):
    return json.loads(response_body or b"null")


async def make_api():
    database = ApiFakeDatabase()
    backtests = BacktestRepository(database)
    tasks = DomainTaskRepository(database)
    service = BacktestApiService(
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
    app.dependency_overrides[get_backtest_api_service] = lambda: service
    return app, database, service, active_user


def create_payload(**updates):
    payload = {
        "strategy_version_id": "strategy-v1",
        "market": "CN",
        "start_date": "2024-01-01",
        "end_date": "2024-04-30",
        "initial_cash": "100",
        "benchmark": "000300",
        "execution_model_id": "next_open",
        "parameter_overrides": {},
        "seed": 7,
        "save_daily_positions": True,
        "notes": "api fixture",
    }
    payload.update(updates)
    return payload


def seed_succeeded(database, run_id, *, execution_model="next_open"):
    now = datetime(2024, 5, 1, tzinfo=timezone.utc)
    request = create_payload(execution_model_id=execution_model)
    run = BacktestRunRecord(
        run_id=run_id,
        task_id=f"task-{run_id}",
        user_id="owner",
        strategy_version_id="strategy-v1",
        market=Market.CN,
        request={
            **request,
            "base_currency": "CNY",
            "universe_override": None,
        },
        status=BacktestRunStatus.SUCCEEDED,
        summary={"completed_days": 3},
        started_at=now,
        finished_at=now,
    )
    database[BacktestRepository.RUNS_COLLECTION].documents.append(
        run.model_dump(mode="json")
    )
    days = (date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4))
    equity_values = (
        (Decimal("90"), Decimal("10"), Decimal("100"), Decimal("0.1")),
        (Decimal("101"), Decimal("0"), Decimal("101"), Decimal("0.11")),
        (Decimal("101"), Decimal("0"), Decimal("101"), Decimal("0")),
    )
    for index, day in enumerate(days):
        cash, market_value, value, turnover = equity_values[index]
        record = BacktestEquityDailyRecord(
            run_id=run_id,
            user_id="owner",
            trade_date=day,
            cash=cash,
            market_value=market_value,
            equity=value,
            daily_return=None,
            cumulative_return=value / 100 - 1,
            drawdown=Decimal("0"),
            benchmark_equity=Decimal("100"),
            turnover=turnover,
            gross_exposure=market_value / value,
            net_exposure=market_value / value,
        )
        database[BacktestRepository.EQUITY_COLLECTION].documents.append(
            record.model_dump(mode="json")
        )
    buy = BacktestTradeRecord(
        trade_id=f"buy-{run_id}",
        order_id=f"buy-order-{run_id}",
        run_id=run_id,
        user_id="owner",
        market=Market.CN,
        symbol="600000",
        side=OrderSide.BUY,
        quantity=10,
        raw_price=Decimal("1"),
        slippage=Decimal("0"),
        fill_price=Decimal("1"),
        notional=Decimal("10"),
        fees=FeeBreakdown(),
        trade_date=days[0],
    )
    sell = BacktestTradeRecord(
        trade_id=f"sell-{run_id}",
        order_id=f"sell-order-{run_id}",
        run_id=run_id,
        user_id="owner",
        market=Market.CN,
        symbol="600000",
        side=OrderSide.SELL,
        quantity=10,
        raw_price=Decimal("1.1"),
        slippage=Decimal("0"),
        fill_price=Decimal("1.1"),
        notional=Decimal("11"),
        fees=FeeBreakdown(),
        trade_date=days[1],
    )
    for item in (buy, sell):
        database[BacktestRepository.TRADES_COLLECTION].documents.append(
            item.model_dump(mode="json")
        )
    for item in (buy, sell):
        order = BacktestOrderRecord(
            order_id=item.order_id,
            run_id=run_id,
            user_id="owner",
            signal_id=f"signal-{item.order_id}",
            market=Market.CN,
            symbol=item.symbol,
            side=item.side,
            requested_qty=item.quantity,
            filled_qty=item.quantity,
            remaining_qty=0,
            order_type="next_open",
            created_trade_date=item.trade_date,
            expire_date=days[-1],
            status=BrokerOrderStatus.FILLED,
            execution_attempts=1,
        )
        database[BacktestRepository.ORDERS_COLLECTION].documents.append(
            order.model_dump(mode="json")
        )
    position = BacktestPositionDailyRecord(
        run_id=run_id,
        user_id="owner",
        trade_date=days[0],
        market=Market.CN,
        symbol="600000",
        quantity=10,
        available_qty=0,
        avg_cost=Decimal("1"),
        close=Decimal("1"),
        market_value=Decimal("10"),
        unrealized_pnl=Decimal("0"),
        weight=Decimal("0.1"),
        holding_days=1,
    )
    database[BacktestRepository.POSITIONS_COLLECTION].documents.append(
        position.model_dump(mode="json")
    )
    event = BacktestEventRecord(
        event_id=f"event-{run_id}",
        run_id=run_id,
        user_id="owner",
        trade_date=days[1],
        sequence=1,
        step=6,
        event_type="ORDER_EXECUTION_RESULT",
        data={"order_id": sell.order_id, "status": "partially_filled"},
    )
    database[BacktestRepository.EVENTS_COLLECTION].documents.append(
        event.model_dump(mode="json")
    )
    return run


async def test_create_list_detail_cancel_idempotency_auth_and_owner_isolation():
    app, database, _, active_user = await make_api()
    active_user["id"] = None
    code, _, _ = await asgi_request(app, "GET", "/api/backtests")
    assert code == 401
    active_user["id"] = "owner"

    headers = {"idempotency-key": "fixture-create"}
    code, raw, _ = await asgi_request(
        app, "POST", "/api/backtests", create_payload(), headers
    )
    body = decoded(raw)
    assert code == 202
    assert body["status"] == "queued"
    assert body["deduplicated"] is False
    run_id = body["run_id"]
    task_id = body["task_id"]

    code, raw, _ = await asgi_request(
        app, "POST", "/api/backtests", create_payload(), headers
    )
    duplicate = decoded(raw)
    assert code == 202
    assert duplicate["run_id"] == run_id
    assert duplicate["task_id"] == task_id
    assert duplicate["deduplicated"] is True

    code, raw, _ = await asgi_request(
        app,
        "POST",
        "/api/backtests",
        create_payload(notes="different request"),
        headers,
    )
    assert code == 409
    assert decoded(raw)["detail"]["code"] == "BACKTEST_STATE_CONFLICT"

    active_user["id"] = "another-owner"
    code, _, _ = await asgi_request(app, "GET", f"/api/backtests/{run_id}")
    assert code == 404
    code, _, _ = await asgi_request(app, "POST", f"/api/backtests/{run_id}/cancel")
    assert code == 404
    active_user["id"] = "owner"

    code, raw, _ = await asgi_request(
        app, "GET", "/api/backtests?page=1&page_size=1"
    )
    page = decoded(raw)
    assert code == 200 and page["total"] == 1 and len(page["items"]) == 1
    code, raw, _ = await asgi_request(app, "GET", f"/api/backtests/{run_id}")
    assert code == 200 and decoded(raw)["task"]["task_id"] == task_id
    code, _, _ = await asgi_request(
        app, "GET", "/api/backtests?page_size=201"
    )
    assert code == 422

    code, raw, _ = await asgi_request(app, "POST", f"/api/backtests/{run_id}/cancel")
    cancelled = decoded(raw)
    assert code == 202
    assert cancelled["run_status"] == "cancelled"
    assert cancelled["task_status"] == "cancelled"
    stored = database[BacktestRepository.RUNS_COLLECTION].documents[0]
    assert stored["status"] == "cancelled"


async def test_result_pages_metrics_date_filters_downsampling_and_exports():
    app, database, _, _ = await make_api()
    run_id = "result-run"
    seed_succeeded(database, run_id)

    code, raw, _ = await asgi_request(
        app, "GET", f"/api/backtests/{run_id}/equity?page_size=2"
    )
    equity = decoded(raw)
    assert code == 200 and equity["total"] == 3 and len(equity["items"]) == 2
    code, raw, _ = await asgi_request(
        app, "GET", f"/api/backtests/{run_id}/equity?downsample=monthly"
    )
    sampled = decoded(raw)
    assert code == 200 and sampled["total"] == 1
    assert sampled["items"][0]["trade_date"] == "2024-01-04"

    code, raw, _ = await asgi_request(
        app, "GET", f"/api/backtests/{run_id}/trades?page_size=1&page=2"
    )
    trades = decoded(raw)
    assert code == 200 and trades["total"] == 2
    assert trades["items"][0]["side"] == "sell"
    code, raw, _ = await asgi_request(
        app,
        "GET",
        f"/api/backtests/{run_id}/positions?trade_date=2024-01-02",
    )
    assert code == 200 and decoded(raw)["total"] == 1
    code, _, _ = await asgi_request(
        app,
        "GET",
        f"/api/backtests/{run_id}/positions?trade_date=2024-01-02&start_date=2024-01-01",
    )
    assert code == 422
    code, raw, _ = await asgi_request(
        app, "GET", f"/api/backtests/{run_id}/events"
    )
    assert code == 200 and decoded(raw)["total"] == 1

    code, raw, _ = await asgi_request(
        app, "GET", f"/api/backtests/{run_id}/metrics"
    )
    metrics = decoded(raw)
    assert code == 200
    assert Decimal(metrics["total_return"]) == Decimal("0.01")
    assert metrics["trade_count"] == 2
    assert metrics["partially_filled_order_count"] == 1
    assert "sharpe_ratio" in metrics["formulas"]

    code, raw, headers = await asgi_request(
        app, "GET", f"/api/backtests/{run_id}/export?resource=trades&format=json"
    )
    exported = decoded(raw)
    assert code == 200 and exported["row_count"] == 2
    assert headers["content-disposition"].endswith('trades.json"')
    code, raw, headers = await asgi_request(
        app, "GET", f"/api/backtests/{run_id}/export?resource=trades&format=csv"
    )
    assert code == 200 and b"trade_id" in raw
    assert headers["content-type"].startswith("text/csv")


async def test_compare_never_ranks_incompatible_runs_and_large_export_is_deferred():
    app, database, service, active_user = await make_api()
    seed_succeeded(database, "run-a")
    seed_succeeded(database, "run-b")
    seed_succeeded(database, "run-c", execution_model="next_close")

    code, raw, _ = await asgi_request(
        app, "POST", "/api/backtests/compare", {"run_ids": ["run-a", "run-b"]}
    )
    compatible = decoded(raw)
    assert code == 200 and compatible["comparable"] is True
    assert [item["run_id"] for item in compatible["items"]] == ["run-a", "run-b"]

    code, raw, _ = await asgi_request(
        app, "POST", "/api/backtests/compare", {"run_ids": ["run-a", "run-c"]}
    )
    incompatible = decoded(raw)
    assert code == 200 and incompatible["comparable"] is False
    assert incompatible["compatibility_warnings"] == [
        "RUN_CONVENTIONS_DIFFER_NO_DIRECT_RANKING"
    ]

    active_user["id"] = "other-owner"
    code, _, _ = await asgi_request(
        app, "POST", "/api/backtests/compare", {"run_ids": ["run-a"]}
    )
    assert code == 404
    active_user["id"] = "owner"

    events = database[BacktestRepository.EVENTS_COLLECTION].documents
    events.extend(
        {
            "event_id": f"large-{index}",
            "run_id": "run-a",
            "user_id": "owner",
            "trade_date": "2024-01-04",
        }
        for index in range(service.MAX_SYNC_EXPORT_ROWS)
    )
    code, raw, _ = await asgi_request(
        app, "GET", "/api/backtests/run-a/export?resource=events&format=json"
    )
    deferred = decoded(raw)
    assert code == 202
    assert deferred["code"] == "BACKTEST_EXPORT_ASYNC_REQUIRED"
    assert deferred["estimated_rows"] == service.MAX_SYNC_EXPORT_ROWS + 1
