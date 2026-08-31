from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.models.domain_task import DomainTaskType
from app.models.factor import FactorAnalysisTaskPayload, FactorSnapshot, FactorSnapshotStatus
from app.models.market_data import DailyBar
from app.models.symbol import Market
from app.repositories.factor_repository import FactorRepository
from app.routers.factors import get_factor_analysis_api_service
from app.services.domain_tasks import (
    DomainTaskContext,
    DomainTaskHandlerRegistry,
    TaskCancellationRequested,
    TerminalTaskError,
)
from app.services.factors.analysis import FactorAnalysisApiService, FactorAnalysisService
from app.workers.handlers.factor_analysis import register_factor_analysis_handler
from tests.integration.test_factor_api import ApiFakeDatabase, asgi_request, make_api


pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _false():
    return False


async def _report(progress, stage, message):
    del progress, stage, message


def _payload(snapshot_ids):
    return {
        "snapshot_ids": snapshot_ids,
        "factor_ids": ["ret_1d", "ret_5d"],
        "horizons": [1],
        "quantiles": 5,
        "min_samples": 10,
        "min_cross_section": 5,
        "label_as_of": "2025-01-05T08:00:00+00:00",
        "label_source_version": "bars-label-v1",
        "transaction_cost_bps": 5,
        "correlation_threshold": 0.85,
    }


def _seed_snapshots(database):
    snapshot_ids = []
    base_date = date(2025, 1, 1)
    for offset in range(3):
        snapshot_id = f"{offset + 1:064x}"
        snapshot_ids.append(snapshot_id)
        trade_date = base_date + timedelta(days=offset)
        snapshot = FactorSnapshot(
            snapshot_id=snapshot_id,
            user_id="owner",
            job_id=f"job-{offset}",
            task_id=f"task-{offset}",
            market=Market.CN,
            trade_date=trade_date,
            as_of=datetime.combine(
                trade_date, datetime.min.time(), timezone(timedelta(hours=8))
            ).replace(hour=15),
            universe_snapshot_id="cn-fixed-universe-v1",
            factor_set_checksum=f"{offset + 11:064x}",
            request_checksum=f"{offset + 21:064x}",
            status=FactorSnapshotStatus.READY,
            expected_row_count=5,
            expected_factor_count=2,
            row_count=5,
            factor_count=2,
            source_versions={"daily_bars": "bars-feature-v1"},
            values_checksum=f"{offset + 31:064x}",
            published_at=datetime(2025, 1, 4, tzinfo=timezone.utc),
        )
        database["factor_snapshots"].documents.append(snapshot.model_dump(mode="json"))
        for rank in range(1, 6):
            database["factor_values"].documents.append(
                {
                    "snapshot_id": snapshot_id,
                    "user_id": "owner",
                    "market": "CN",
                    "symbol": f"S{rank}",
                    "trade_date": trade_date.isoformat(),
                    "values": {
                        "ret_1d": float(rank),
                        "ret_5d": float(rank * 2),
                        "market_cap_log": float(rank * 10),
                        "beta_60": float(6 - rank),
                    },
                    "quality": {"ret_1d": None, "ret_5d": None},
                }
            )
    return snapshot_ids


async def test_analysis_api_durable_task_result_and_cross_user_isolation(monkeypatch):
    app, database, base_service, active_user = await make_api(monkeypatch)
    repository = base_service.factor_repository
    analysis_api = FactorAnalysisApiService(
        factor_repository=repository,
        task_repository=base_service.task_repository,
    )
    app.dependency_overrides[get_factor_analysis_api_service] = lambda: analysis_api
    snapshot_ids = _seed_snapshots(database)
    payload = _payload(snapshot_ids)

    code, accepted = await asgi_request(app, "POST", "/api/factors/analyze", payload)
    assert code == 202
    assert accepted["deduplicated"] is False
    assert len(accepted["analysis_id"]) == 64

    code, duplicate = await asgi_request(app, "POST", "/api/factors/analyze", payload)
    assert code == 202
    assert duplicate["task_id"] == accepted["task_id"]
    assert duplicate["analysis_id"] == accepted["analysis_id"]
    assert duplicate["deduplicated"] is True
    task_document = next(
        item for item in database["domain_tasks"].documents
        if item["task_id"] == accepted["task_id"]
    )
    assert task_document["task_type"] == "factor_analysis"

    code, body = await asgi_request(
        app, "GET", f"/api/factors/analysis/{accepted['analysis_id']}"
    )
    assert code == 404
    assert body["detail"]["code"] == "FACTOR_ANALYSIS_NOT_FOUND"

    async def label_loader(**kwargs):
        symbol = kwargs["symbol"]
        rank = int(symbol[1:])
        rows = []
        for offset in range(4):
            rows.append(
                DailyBar(
                    market=Market.CN,
                    symbol=symbol,
                    trade_date=date(2025, 1, 1) + timedelta(days=offset),
                    close=100.0 * (1 + rank / 100.0) ** offset,
                    source="fixture",
                    source_version="bars-label-v1",
                )
            )
        return tuple(rows), "bars-label-v1"

    parsed_payload = FactorAnalysisTaskPayload.model_validate(task_document["payload"])
    registry = DomainTaskHandlerRegistry()
    handler = register_factor_analysis_handler(
        FactorAnalysisService(repository, label_loader=label_loader),
        registry=registry,
    )
    assert registry.resolve(DomainTaskType.FACTOR_ANALYSIS) is handler
    result_ref = await handler(
        parsed_payload.model_dump(mode="json"),
        DomainTaskContext(
            task_id=accepted["task_id"],
            user_id="owner",
            task_type=DomainTaskType.FACTOR_ANALYSIS,
            attempt=1,
            max_attempts=3,
        ),
        _report,
        _false,
    )
    assert result_ref.collection == "factor_analysis_results"
    assert result_ref.id == accepted["analysis_id"]
    repeated_ref = await handler(
        parsed_payload.model_dump(mode="json"),
        DomainTaskContext(
            task_id=accepted["task_id"],
            user_id="owner",
            task_type=DomainTaskType.FACTOR_ANALYSIS,
            attempt=2,
            max_attempts=3,
        ),
        _report,
        _false,
    )
    assert repeated_ref == result_ref
    assert len(database["factor_analysis_results"].documents) == 1
    index_names = {
        options.get("name")
        for _, options in database["factor_analysis_results"].indexes
    }
    assert {
        "factor_analysis_id_unique",
        "factor_analysis_owner_request_unique",
        "factor_analysis_owner_created",
    }.issubset(index_names)

    code, result = await asgi_request(
        app, "GET", f"/api/factors/analysis/{accepted['analysis_id']}"
    )
    assert code == 200
    assert result["user_id"] == "owner"
    assert result["feature_start"] == "2025-01-01"
    assert result["feature_end"] == "2025-01-03"
    assert result["quality"]["row_count"] == 15
    assert result["ic"][0]["rank_mean"] == pytest.approx(1.0)
    assert result["quality"]["label_source_versions"] == ["bars-label-v1"]

    active_user["id"] = "other"
    code, body = await asgi_request(
        app, "GET", f"/api/factors/analysis/{accepted['analysis_id']}"
    )
    assert code == 404
    assert body["detail"]["code"] == "FACTOR_ANALYSIS_NOT_FOUND"
    code, body = await asgi_request(app, "POST", "/api/factors/analyze", payload)
    assert code == 422
    assert body["detail"]["code"] == "FACTOR_ANALYSIS_INVALID"


async def test_analysis_feature_flag_blocks_task_creation(monkeypatch):
    app, database, base_service, _ = await make_api(monkeypatch)
    app.dependency_overrides[get_factor_analysis_api_service] = lambda: FactorAnalysisApiService(
        factor_repository=FactorRepository(database),
        task_repository=base_service.task_repository,
    )
    snapshot_ids = _seed_snapshots(database)
    before = len(database["domain_tasks"].documents)
    monkeypatch.setenv("FACTOR_FEATURE_ENABLED", "false")
    code, body = await asgi_request(
        app, "POST", "/api/factors/analyze", _payload(snapshot_ids)
    )
    assert code == 404
    assert body["detail"]["code"] == "FACTOR_FEATURE_DISABLED"
    assert len(database["domain_tasks"].documents) == before


async def test_analysis_handler_rejects_invalid_payload_and_honors_cancellation():
    handler = register_factor_analysis_handler(
        FactorAnalysisService(FactorRepository(ApiFakeDatabase())),
        registry=DomainTaskHandlerRegistry(),
    )
    context = DomainTaskContext(
        task_id="task-analysis",
        user_id="owner",
        task_type=DomainTaskType.FACTOR_ANALYSIS,
        attempt=1,
        max_attempts=3,
    )
    with pytest.raises(TerminalTaskError) as invalid:
        await handler({}, context, _report, _false)
    assert invalid.value.error_code == "FACTOR_ANALYSIS_REQUEST_INVALID"

    async def cancelled():
        return True

    valid = FactorAnalysisTaskPayload(
        analysis_id="a" * 64,
        request=_payload(["1" * 64]),
    )
    with pytest.raises(TaskCancellationRequested):
        await handler(valid.model_dump(mode="json"), context, _report, cancelled)
