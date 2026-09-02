"""Owner-scoped application service for backtest HTTP APIs."""

from __future__ import annotations

import csv
import io
import json
from datetime import date
from decimal import Decimal
from enum import Enum
from hashlib import sha256
from typing import Any, Generic, Literal, Mapping, Sequence, TypeVar
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pymongo import ASCENDING, DESCENDING

from app.models.backtest import (
    BacktestPerformanceConfig,
    BacktestPerformanceReport,
    BacktestRequest,
)
from app.models.domain_task import DomainTask, DomainTaskStatus, DomainTaskType
from app.models.strategy import StrategyVersionStatus
from app.repositories.backtest_repository import (
    BacktestPersistenceConflict,
    BacktestRepository,
)
from app.repositories.domain_task_repository import DomainTaskRepository
from app.repositories.strategy_repository import StrategyRepository
from app.services.backtest.data import PointInTimeBacktestDataService
from app.services.backtest.ledger import (
    BacktestEquityDailyRecord,
    BacktestEventRecord,
    BacktestOrderRecord,
    BacktestPositionDailyRecord,
    BacktestRunRecord,
    BacktestRunStatus,
    BacktestTradeRecord,
    stable_checksum,
)
from app.services.backtest.performance import (
    BacktestPerformanceCalculator,
    PerformanceCalculationError,
)
from app.services.domain_tasks import IdempotencyConflictError, TaskNotCancellableError


PageItemT = TypeVar("PageItemT")
ExportResource = Literal[
    "equity", "orders", "trades", "positions", "events", "metrics"
]
ExportFormat = Literal["json", "csv"]


class BacktestApiError(RuntimeError):
    code = "BACKTEST_API_ERROR"


class BacktestApiNotFound(BacktestApiError):
    code = "BACKTEST_NOT_FOUND"


class BacktestApiValidationError(BacktestApiError):
    code = "BACKTEST_REQUEST_INVALID"


class BacktestApiConflict(BacktestApiError):
    code = "BACKTEST_STATE_CONFLICT"


class BacktestApiLimitExceeded(BacktestApiError):
    code = "BACKTEST_RESULT_LIMIT_EXCEEDED"


class BacktestExportAsyncRequired(BacktestApiLimitExceeded):
    code = "BACKTEST_EXPORT_ASYNC_REQUIRED"

    def __init__(self, resource: str, estimated_rows: int, maximum_rows: int):
        super().__init__(
            f"{resource} export has {estimated_rows} rows; synchronous limit is {maximum_rows}"
        )
        self.resource = resource
        self.estimated_rows = estimated_rows
        self.maximum_rows = maximum_rows


class EquityDownsample(str, Enum):
    NONE = "none"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class BacktestAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    task_id: str
    status: BacktestRunStatus
    deduplicated: bool


class BacktestRunDetail(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run: BacktestRunRecord
    task: DomainTask | None


class BacktestCancelResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    task_id: str
    run_status: BacktestRunStatus
    task_status: DomainTaskStatus


class BacktestPage(BaseModel, Generic[PageItemT]):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[PageItemT, ...]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=200)
    total: int = Field(ge=0)


class BacktestEquityPage(BacktestPage[BacktestEquityDailyRecord]):
    downsample: EquityDownsample


class BacktestCompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_ids: tuple[str, ...] = Field(min_length=1, max_length=10)
    annual_risk_free_rate: Decimal = Field(default=Decimal("0"), gt=-1)

    @model_validator(mode="after")
    def unique_runs(self) -> "BacktestCompareRequest":
        if len(set(self.run_ids)) != len(self.run_ids):
            raise ValueError("run_ids must be unique")
        return self


class BacktestComparisonItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    market: str
    start_date: date
    end_date: date
    metrics: BacktestPerformanceReport


class BacktestCompareResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    comparable: bool
    compatibility_warnings: tuple[str, ...]
    items: tuple[BacktestComparisonItem, ...]


class BacktestExportFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    content: bytes
    media_type: str
    filename: str
    row_count: int = Field(ge=0)


class BacktestApiService:
    MAX_PAGE_SIZE = 200
    MAX_METRIC_ROWS = 100_000
    MAX_DOWNSAMPLE_ROWS = 10_000
    MAX_SYNC_EXPORT_ROWS = 5_000

    def __init__(
        self,
        *,
        backtests: BacktestRepository,
        tasks: DomainTaskRepository,
        strategies: StrategyRepository,
        performance: BacktestPerformanceCalculator | None = None,
        data_service: PointInTimeBacktestDataService | None = None,
        user_concurrent_limit: int = 2,
        global_concurrent_limit: int = 20,
    ) -> None:
        if user_concurrent_limit < 1 or global_concurrent_limit < 1:
            raise ValueError("backtest concurrency limits must be positive")
        self.backtests = backtests
        self.tasks = tasks
        self.strategies = strategies
        self.performance = performance or BacktestPerformanceCalculator()
        self.data_service = data_service or PointInTimeBacktestDataService(
            repository=backtests
        )
        self.user_concurrent_limit = user_concurrent_limit
        self.global_concurrent_limit = global_concurrent_limit

    async def create(
        self,
        *,
        user_id: str,
        request: BacktestRequest,
        client_idempotency_key: str | None = None,
    ) -> BacktestAccepted:
        request_payload = request.model_dump(mode="json")
        request_checksum = stable_checksum(request_payload)
        client_key = client_idempotency_key or request_checksum
        key_digest = sha256(f"{user_id}\x1f{client_key}".encode()).hexdigest()
        durable_key = f"backtest:{key_digest}"
        task_id = str(uuid5(NAMESPACE_URL, f"task:{durable_key}"))
        run_id = str(uuid5(NAMESPACE_URL, f"run:{durable_key}"))

        existing = await self.backtests.get_run(run_id, user_id=user_id)
        if existing is not None:
            if existing.request != request_payload:
                raise BacktestApiConflict(
                    "idempotency key was already used with a different request"
                )
            task = await self.tasks.get_task(existing.task_id, user_id)
            if task is None:
                task = await self._create_task(
                    user_id=user_id,
                    task_id=existing.task_id,
                    run_id=existing.run_id,
                    idempotency_key=durable_key,
                )
            return BacktestAccepted(
                run_id=existing.run_id,
                task_id=task.task_id,
                status=existing.status,
                deduplicated=True,
            )

        try:
            self.data_service.validate_request_window(request)
        except ValueError as exc:
            raise BacktestApiValidationError(str(exc)) from exc
        strategy = await self.strategies.get_version(
            request.strategy_version_id, user_id=user_id, include_system=True
        )
        if strategy is None:
            raise BacktestApiValidationError(
                "published strategy version is unavailable to this user"
            )
        if strategy.status != StrategyVersionStatus.PUBLISHED:
            raise BacktestApiValidationError("strategy version must be published")
        if strategy.market != request.market:
            raise BacktestApiValidationError(
                "strategy and backtest markets must match"
            )
        await self._enforce_concurrency(user_id)
        input_versions = {
            "strategy": (str(strategy.checksum),),
            "factors": tuple(
                f"{item.factor_id}:{item.version}:{item.checksum}"
                for item in strategy.factor_dependencies
            ),
            "skills": tuple(
                f"{item.skill_id}:{item.version}:{item.checksum}"
                for item in strategy.skill_dependencies
            ),
        }
        try:
            run = await self.backtests.create_run(
                BacktestRunRecord(
                    run_id=run_id,
                    task_id=task_id,
                    user_id=user_id,
                    strategy_version_id=request.strategy_version_id,
                    market=request.market,
                    request=request_payload,
                    input_versions=input_versions,
                )
            )
        except BacktestPersistenceConflict as exc:
            raise BacktestApiConflict(str(exc)) from exc
        task = await self._create_task(
            user_id=user_id,
            task_id=task_id,
            run_id=run_id,
            idempotency_key=durable_key,
        )
        return BacktestAccepted(
            run_id=run.run_id,
            task_id=task.task_id,
            status=run.status,
            deduplicated=False,
        )

    async def _create_task(self, *, user_id, task_id, run_id, idempotency_key):
        try:
            return await self.tasks.create_task(
                user_id=user_id,
                task_type=DomainTaskType.BACKTEST,
                payload={"run_id": run_id},
                idempotency_key=idempotency_key,
                task_id=task_id,
                stage="backtest_queued",
                message="Backtest queued",
            )
        except IdempotencyConflictError as exc:
            raise BacktestApiConflict(str(exc)) from exc

    async def _enforce_concurrency(self, user_id: str) -> None:
        active = {
            "$in": [BacktestRunStatus.QUEUED.value, BacktestRunStatus.RUNNING.value]
        }
        collection = self.backtests.get_db()[self.backtests.RUNS_COLLECTION]
        user_count = await collection.count_documents(
            {"user_id": user_id, "status": active}
        )
        global_count = await collection.count_documents({"status": active})
        if user_count >= self.user_concurrent_limit:
            raise BacktestApiConflict("user concurrent backtest limit reached")
        if global_count >= self.global_concurrent_limit:
            raise BacktestApiConflict("global concurrent backtest limit reached")

    async def list_runs(
        self,
        *,
        user_id: str,
        status: BacktestRunStatus | None,
        page: int,
        page_size: int,
    ) -> BacktestPage[BacktestRunRecord]:
        query: dict[str, Any] = {"user_id": user_id}
        if status is not None:
            query["status"] = status.value
        documents, total = await self._page(
            self.backtests.RUNS_COLLECTION,
            query,
            [("created_at", DESCENDING), ("run_id", DESCENDING)],
            page,
            page_size,
        )
        return BacktestPage[BacktestRunRecord](
            items=tuple(_parse(BacktestRunRecord, item) for item in documents),
            page=page,
            page_size=page_size,
            total=total,
        )

    async def detail(self, *, user_id: str, run_id: str) -> BacktestRunDetail:
        run = await self._owned_run(user_id, run_id)
        task = await self.tasks.get_task(run.task_id, user_id)
        return BacktestRunDetail(run=run, task=task)

    async def cancel(self, *, user_id: str, run_id: str) -> BacktestCancelResult:
        run = await self._owned_run(user_id, run_id)
        task = await self.tasks.get_task(run.task_id, user_id)
        if task is None:
            raise BacktestApiConflict("durable task for backtest is missing")
        if run.status == BacktestRunStatus.CANCELLED:
            if task.status != DomainTaskStatus.CANCELLED:
                raise BacktestApiConflict("run and task cancellation states differ")
            return BacktestCancelResult(
                run_id=run.run_id,
                task_id=task.task_id,
                run_status=run.status,
                task_status=task.status,
            )
        try:
            task = await self.tasks.request_cancel(task_id=task.task_id, user_id=user_id)
        except TaskNotCancellableError as exc:
            raise BacktestApiConflict(str(exc)) from exc
        if task is None:
            raise BacktestApiConflict("durable task for backtest is missing")
        if (
            task.status == DomainTaskStatus.CANCELLED
            and run.status == BacktestRunStatus.QUEUED
        ):
            run = await self.backtests.mark_run_cancelled(run_id, user_id=user_id)
        else:
            run = await self._owned_run(user_id, run_id)
        return BacktestCancelResult(
            run_id=run.run_id,
            task_id=task.task_id,
            run_status=run.status,
            task_status=task.status,
        )

    async def equity_page(
        self,
        *,
        user_id: str,
        run_id: str,
        start_date: date | None,
        end_date: date | None,
        downsample: EquityDownsample,
        page: int,
        page_size: int,
    ) -> BacktestEquityPage:
        await self._owned_run(user_id, run_id)
        query = self._date_query(user_id, run_id, start_date, end_date)
        if downsample == EquityDownsample.NONE:
            documents, total = await self._page(
                self.backtests.EQUITY_COLLECTION,
                query,
                [("trade_date", ASCENDING)],
                page,
                page_size,
            )
            rows = tuple(_parse(BacktestEquityDailyRecord, item) for item in documents)
        else:
            documents = await self._bounded_all(
                self.backtests.EQUITY_COLLECTION,
                query,
                [("trade_date", ASCENDING)],
                self.MAX_DOWNSAMPLE_ROWS,
            )
            sampled = self._downsample_equity(
                tuple(_parse(BacktestEquityDailyRecord, item) for item in documents),
                downsample,
            )
            total = len(sampled)
            offset = (page - 1) * page_size
            rows = sampled[offset : offset + page_size]
        return BacktestEquityPage(
            items=rows,
            page=page,
            page_size=page_size,
            total=total,
            downsample=downsample,
        )

    async def trades_page(self, **kwargs) -> BacktestPage[BacktestTradeRecord]:
        return await self._ledger_page(
            model=BacktestTradeRecord,
            collection=self.backtests.TRADES_COLLECTION,
            sort=[("trade_date", ASCENDING), ("trade_id", ASCENDING)],
            **kwargs,
        )

    async def positions_page(self, **kwargs) -> BacktestPage[BacktestPositionDailyRecord]:
        return await self._ledger_page(
            model=BacktestPositionDailyRecord,
            collection=self.backtests.POSITIONS_COLLECTION,
            sort=[("trade_date", ASCENDING), ("symbol", ASCENDING)],
            **kwargs,
        )

    async def events_page(self, **kwargs) -> BacktestPage[BacktestEventRecord]:
        return await self._ledger_page(
            model=BacktestEventRecord,
            collection=self.backtests.EVENTS_COLLECTION,
            sort=[("trade_date", ASCENDING), ("sequence", ASCENDING)],
            **kwargs,
        )

    async def _ledger_page(
        self,
        *,
        model,
        collection,
        sort,
        user_id,
        run_id,
        start_date,
        end_date,
        page,
        page_size,
    ):
        await self._owned_run(user_id, run_id)
        query = self._date_query(user_id, run_id, start_date, end_date)
        documents, total = await self._page(
            collection, query, sort, page, page_size
        )
        return BacktestPage[model](
            items=tuple(_parse(model, item) for item in documents),
            page=page,
            page_size=page_size,
            total=total,
        )

    async def metrics(
        self,
        *,
        user_id: str,
        run_id: str,
        annual_risk_free_rate: Decimal = Decimal("0"),
    ) -> BacktestPerformanceReport:
        run = await self._owned_run(user_id, run_id)
        if run.status != BacktestRunStatus.SUCCEEDED:
            raise BacktestApiConflict("metrics require a succeeded backtest")
        inputs = await self._metric_inputs(user_id, run_id)
        try:
            initial_equity = Decimal(str(run.request["initial_cash"]))
        except (KeyError, ValueError, TypeError) as exc:
            raise BacktestApiConflict("run initial cash is unavailable") from exc
        try:
            return self.performance.calculate(
                initial_equity=initial_equity,
                equity=inputs["equity"],
                trades=inputs["trades"],
                orders=inputs["orders"],
                positions=inputs["positions"],
                events=inputs["events"],
                config=BacktestPerformanceConfig(
                    annual_risk_free_rate=annual_risk_free_rate
                ),
            )
        except PerformanceCalculationError as exc:
            raise BacktestApiConflict(str(exc)) from exc

    async def compare(
        self, *, user_id: str, request: BacktestCompareRequest
    ) -> BacktestCompareResult:
        runs = [await self._owned_run(user_id, run_id) for run_id in request.run_ids]
        keys = {
            (
                run.market.value,
                run.request.get("start_date"),
                run.request.get("end_date"),
                run.request.get("initial_cash"),
                run.request.get("benchmark"),
                run.request.get("execution_model_id"),
                run.request.get("base_currency"),
                run.request.get("universe_override"),
                stable_checksum(run.request.get("parameter_overrides", {})),
            )
            for run in runs
        }
        warnings: tuple[str, ...] = ()
        if len(keys) != 1:
            warnings = ("RUN_CONVENTIONS_DIFFER_NO_DIRECT_RANKING",)
        items = []
        for run in runs:
            metrics = await self.metrics(
                user_id=user_id,
                run_id=run.run_id,
                annual_risk_free_rate=request.annual_risk_free_rate,
            )
            items.append(
                BacktestComparisonItem(
                    run_id=run.run_id,
                    market=run.market.value,
                    start_date=date.fromisoformat(str(run.request["start_date"])),
                    end_date=date.fromisoformat(str(run.request["end_date"])),
                    metrics=metrics,
                )
            )
        return BacktestCompareResult(
            comparable=len(keys) == 1,
            compatibility_warnings=warnings,
            items=tuple(items),
        )

    async def export(
        self,
        *,
        user_id: str,
        run_id: str,
        resource: ExportResource,
        format: ExportFormat,
    ) -> BacktestExportFile:
        run = await self._owned_run(user_id, run_id)
        if resource == "metrics":
            models: Sequence[BaseModel] = (
                await self.metrics(user_id=user_id, run_id=run_id),
            )
        else:
            collection, model, sort = self._export_definition(resource)
            query = {"user_id": user_id, "run_id": run_id}
            total = await self.backtests.get_db()[collection].count_documents(query)
            if total > self.MAX_SYNC_EXPORT_ROWS:
                raise BacktestExportAsyncRequired(
                    resource, total, self.MAX_SYNC_EXPORT_ROWS
                )
            documents = await self._bounded_all(
                collection, query, sort, self.MAX_SYNC_EXPORT_ROWS
            )
            models = tuple(_parse(model, item) for item in documents)
        rows = [item.model_dump(mode="json") for item in models]
        if format == "json":
            content = json.dumps(
                {
                    "run_id": run.run_id,
                    "resource": resource,
                    "row_count": len(rows),
                    "items": rows,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            media_type = "application/json"
        else:
            content = _csv_bytes(rows)
            media_type = "text/csv; charset=utf-8"
        return BacktestExportFile(
            content=content,
            media_type=media_type,
            filename=f"backtest-{run.run_id}-{resource}.{format}",
            row_count=len(rows),
        )

    async def _metric_inputs(self, user_id: str, run_id: str):
        query = {"user_id": user_id, "run_id": run_id}
        definitions = {
            "equity": (
                self.backtests.EQUITY_COLLECTION,
                BacktestEquityDailyRecord,
                [("trade_date", ASCENDING)],
            ),
            "trades": (
                self.backtests.TRADES_COLLECTION,
                BacktestTradeRecord,
                [("trade_date", ASCENDING), ("trade_id", ASCENDING)],
            ),
            "orders": (
                self.backtests.ORDERS_COLLECTION,
                BacktestOrderRecord,
                [("created_trade_date", ASCENDING), ("order_id", ASCENDING)],
            ),
            "positions": (
                self.backtests.POSITIONS_COLLECTION,
                BacktestPositionDailyRecord,
                [("trade_date", ASCENDING), ("symbol", ASCENDING)],
            ),
            "events": (
                self.backtests.EVENTS_COLLECTION,
                BacktestEventRecord,
                [("trade_date", ASCENDING), ("sequence", ASCENDING)],
            ),
        }
        result = {}
        for key, (collection, model, sort) in definitions.items():
            documents = await self._bounded_all(
                collection, query, sort, self.MAX_METRIC_ROWS
            )
            result[key] = tuple(_parse(model, item) for item in documents)
        return result

    async def _owned_run(self, user_id: str, run_id: str) -> BacktestRunRecord:
        run = await self.backtests.get_run(run_id, user_id=user_id)
        if run is None:
            raise BacktestApiNotFound("backtest was not found")
        return run

    async def _page(self, collection_name, query, sort, page, page_size):
        if page < 1 or not 1 <= page_size <= self.MAX_PAGE_SIZE:
            raise BacktestApiValidationError("invalid pagination")
        collection = self.backtests.get_db()[collection_name]
        total = await collection.count_documents(query)
        cursor = (
            collection.find(query)
            .sort(sort)
            .skip((page - 1) * page_size)
            .limit(page_size)
        )
        return await cursor.to_list(length=page_size), total

    async def _bounded_all(self, collection_name, query, sort, maximum):
        collection = self.backtests.get_db()[collection_name]
        total = await collection.count_documents(query)
        if total > maximum:
            raise BacktestApiLimitExceeded(
                f"{collection_name} contains {total} rows; limit is {maximum}"
            )
        cursor = collection.find(query).sort(sort).limit(maximum)
        return await cursor.to_list(length=maximum)

    @staticmethod
    def _date_query(user_id, run_id, start_date, end_date):
        if start_date is not None and end_date is not None and end_date < start_date:
            raise BacktestApiValidationError("end_date cannot precede start_date")
        query: dict[str, Any] = {"user_id": user_id, "run_id": run_id}
        bounds = {}
        if start_date is not None:
            bounds["$gte"] = start_date.isoformat()
        if end_date is not None:
            bounds["$lte"] = end_date.isoformat()
        if bounds:
            query["trade_date"] = bounds
        return query

    @staticmethod
    def _downsample_equity(rows, mode):
        grouped = {}
        for row in rows:
            if mode == EquityDownsample.WEEKLY:
                iso = row.trade_date.isocalendar()
                key = (iso.year, iso.week)
            else:
                key = (row.trade_date.year, row.trade_date.month)
            grouped[key] = row
        return tuple(grouped[key] for key in sorted(grouped))

    def _export_definition(self, resource):
        return {
            "equity": (
                self.backtests.EQUITY_COLLECTION,
                BacktestEquityDailyRecord,
                [("trade_date", ASCENDING)],
            ),
            "orders": (
                self.backtests.ORDERS_COLLECTION,
                BacktestOrderRecord,
                [("created_trade_date", ASCENDING), ("order_id", ASCENDING)],
            ),
            "trades": (
                self.backtests.TRADES_COLLECTION,
                BacktestTradeRecord,
                [("trade_date", ASCENDING), ("trade_id", ASCENDING)],
            ),
            "positions": (
                self.backtests.POSITIONS_COLLECTION,
                BacktestPositionDailyRecord,
                [("trade_date", ASCENDING), ("symbol", ASCENDING)],
            ),
            "events": (
                self.backtests.EVENTS_COLLECTION,
                BacktestEventRecord,
                [("trade_date", ASCENDING), ("sequence", ASCENDING)],
            ),
        }[resource]


def _parse(model, document):
    payload = dict(document)
    payload.pop("_id", None)
    payload.pop("record_checksum", None)
    return model.model_validate(payload)


def _csv_bytes(rows: Sequence[Mapping[str, Any]]) -> bytes:
    if not rows:
        return b""
    columns = sorted({key for row in rows for key in row})
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                key: (
                    json.dumps(value, ensure_ascii=False, sort_keys=True)
                    if isinstance(value, (dict, list, tuple))
                    else value
                )
                for key, value in row.items()
            }
        )
    return output.getvalue().encode("utf-8-sig")
