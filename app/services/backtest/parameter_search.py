"""Deterministic parameter search and out-of-sample evaluation.

The module deliberately keeps research selection separate from strategy
publication.  A search creates immutable child backtests, evaluates them over
pre-declared trading-session windows, and reports validation, test, and
stability evidence.  It never mutates a published strategy version.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal, localcontext
from enum import Enum
from itertools import product
from typing import Any, Literal, Protocol
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator
from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.errors import PyMongoError

from app.models.backtest import BacktestInputBundle, BacktestRequest
from app.models.domain_task import DomainTask, DomainTaskResultRef, DomainTaskStatus, DomainTaskType
from app.models.strategy import StrategyVersionStatus
from app.repositories.backtest_repository import BacktestPersistenceConflict, BacktestRepository
from app.repositories.domain_task_repository import (
    DomainTaskRepository,
    IdempotencyConflictError,
    TaskNotCancellableError,
)
from app.repositories.strategy_repository import StrategyRepository
from app.services.backtest.data import PointInTimeBacktestDataService
from app.services.backtest.engine import BacktestEngine
from app.services.backtest.ledger import BacktestEquityDailyRecord, BacktestRunRecord, BacktestRunStatus
from app.services.domain_tasks import CancellationChecker, ProgressCallback, TaskCancellationRequested


RESEARCH_ONLY_NOTICE = (
    "RESEARCH_ONLY_NO_AUTOMATIC_PUBLICATION: validation selection is accompanied "
    "by held-out test and stability evidence; no strategy is published automatically."
)
DEFAULT_COMBINATION_LIMIT = 100
HARD_COMBINATION_LIMIT = 500


def _stable_checksum(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ParameterSearchError(RuntimeError):
    code = "PARAMETER_SEARCH_ERROR"


class ParameterSearchValidationError(ParameterSearchError):
    code = "PARAMETER_SEARCH_INVALID"


class ParameterSearchNotFound(ParameterSearchError):
    code = "PARAMETER_SEARCH_NOT_FOUND"


class ParameterSearchConflict(ParameterSearchError):
    code = "PARAMETER_SEARCH_CONFLICT"


class ParameterSearchMode(str, Enum):
    SPLIT = "split"
    WALK_FORWARD = "walk_forward"


class ParameterSearchStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    CANCELLED = "cancelled"
    FAILED = "failed"


class EvaluationSegment(str, Enum):
    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"


ParameterValue = bool | StrictInt | Decimal | str


class ParameterGridAxis(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$")
    values: tuple[ParameterValue, ...] = Field(min_length=1, max_length=500)

    @field_validator("name")
    @classmethod
    def trim_name(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("parameter name must be trimmed")
        return value

    @field_validator("values")
    @classmethod
    def require_distinct_finite_values(
        cls, values: tuple[ParameterValue, ...]
    ) -> tuple[ParameterValue, ...]:
        identities: set[str] = set()
        for value in values:
            if isinstance(value, Decimal) and not value.is_finite():
                raise ValueError("parameter values must be finite")
            identity = _stable_checksum({"type": type(value).__name__, "value": value})
            if identity in identities:
                raise ValueError("parameter axis values must be unique")
            identities.add(identity)
        return values


class SplitWindowConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    train_end: date
    validation_end: date

    @model_validator(mode="after")
    def ordered_cutoffs(self) -> "SplitWindowConfig":
        if self.validation_end <= self.train_end:
            raise ValueError("validation_end must be after train_end")
        return self


class WalkForwardConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    train_sessions: StrictInt = Field(ge=20, le=5000)
    validation_sessions: StrictInt = Field(ge=5, le=1000)
    test_sessions: StrictInt = Field(ge=5, le=1000)
    step_sessions: StrictInt = Field(ge=1, le=1000)
    max_folds: StrictInt = Field(default=20, ge=1, le=20)


class ParameterSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    base_request: BacktestRequest
    axes: tuple[ParameterGridAxis, ...] = Field(min_length=1, max_length=3)
    mode: ParameterSearchMode
    split: SplitWindowConfig | None = None
    walk_forward: WalkForwardConfig | None = None
    combination_limit: StrictInt = Field(
        default=DEFAULT_COMBINATION_LIMIT, ge=1, le=HARD_COMBINATION_LIMIT
    )
    name: str = Field(default="参数实验", min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def trim_search_name(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("search name must be trimmed")
        return value

    @model_validator(mode="after")
    def validate_configuration(self) -> "ParameterSearchRequest":
        names = [axis.name for axis in self.axes]
        if len(names) != len(set(names)):
            raise ValueError("parameter axis names must be unique")
        inherited = set(self.base_request.parameter_overrides)
        if inherited.intersection(names):
            raise ValueError("searched parameters cannot also be fixed overrides")
        if self.mode == ParameterSearchMode.SPLIT:
            if self.split is None or self.walk_forward is not None:
                raise ValueError("split mode requires only split configuration")
        elif self.walk_forward is None or self.split is not None:
            raise ValueError("walk_forward mode requires only walk_forward configuration")
        combinations = 1
        for axis in self.axes:
            combinations *= len(axis.values)
        if combinations > HARD_COMBINATION_LIMIT:
            raise ValueError(
                f"parameter grid exceeds hard limit of {HARD_COMBINATION_LIMIT} combinations"
            )
        if combinations > self.combination_limit:
            raise ValueError(
                f"parameter grid has {combinations} combinations, above requested limit "
                f"{self.combination_limit}"
            )
        return self


class ParameterCombination(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    index: StrictInt = Field(ge=0, lt=HARD_COMBINATION_LIMIT)
    values: dict[str, ParameterValue]
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")


class EvaluationWindow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fold: StrictInt = Field(ge=0, le=19)
    segment: EvaluationSegment
    start_date: date
    end_date: date
    session_count: StrictInt = Field(ge=1)


class ParameterSearchPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    combinations: tuple[ParameterCombination, ...]
    windows: tuple[EvaluationWindow, ...]
    trading_dates: tuple[date, ...]
    shared_input_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")


class WindowPerformance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fold: StrictInt = Field(ge=0, le=19)
    segment: EvaluationSegment
    start_date: date
    end_date: date
    observations: StrictInt = Field(ge=0)
    total_return: Decimal | None = None
    max_drawdown: Decimal | None = None
    annualized_volatility: Decimal | None = None


class StabilityEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    neighboring_combinations: StrictInt = Field(ge=0)
    neighboring_validation_dispersion: Decimal | None = None
    fold_validation_dispersion: Decimal | None = None
    positive_test_fold_ratio: Decimal | None = Field(default=None, ge=0, le=1)
    stability_score: Decimal = Field(ge=0, le=1)


class ParameterCombinationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    search_id: str = Field(min_length=1, max_length=128)
    user_id: str = Field(min_length=1, max_length=128)
    combination_index: StrictInt = Field(ge=0, lt=HARD_COMBINATION_LIMIT)
    parameters: dict[str, ParameterValue]
    child_run_id: str = Field(min_length=1, max_length=128)
    status: BacktestRunStatus
    validation_mean_return: Decimal | None = None
    test_mean_return: Decimal | None = None
    train_mean_return: Decimal | None = None
    windows: tuple[WindowPerformance, ...] = ()
    stability: StabilityEvidence | None = None
    validation_rank: StrictInt | None = Field(default=None, ge=1)
    selected_candidate: bool = False
    error: dict[str, Any] | None = None
    completed_at: datetime | None = None


class ParameterSearchRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    search_id: str = Field(min_length=1, max_length=128)
    task_id: str = Field(min_length=1, max_length=128)
    user_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=120)
    strategy_version_id: str = Field(min_length=1, max_length=128)
    market: str = Field(min_length=1, max_length=8)
    request: dict[str, Any]
    input_versions: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    status: ParameterSearchStatus = ParameterSearchStatus.QUEUED
    total_combinations: StrictInt = Field(ge=1, le=HARD_COMBINATION_LIMIT)
    completed_combinations: StrictInt = Field(default=0, ge=0, le=HARD_COMBINATION_LIMIT)
    successful_combinations: StrictInt = Field(default=0, ge=0, le=HARD_COMBINATION_LIMIT)
    shared_input_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    windows: tuple[EvaluationWindow, ...]
    selected_combination_index: StrictInt | None = Field(default=None, ge=0)
    research_notice: Literal[
        "RESEARCH_ONLY_NO_AUTOMATIC_PUBLICATION: validation selection is accompanied by held-out test and stability evidence; no strategy is published automatically."
    ] = RESEARCH_ONLY_NOTICE
    error: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=_utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    updated_at: datetime = Field(default_factory=_utc_now)

    @model_validator(mode="after")
    def validate_progress_and_terminal_state(self) -> "ParameterSearchRecord":
        if self.completed_combinations > self.total_combinations:
            raise ValueError("completed combinations cannot exceed total combinations")
        if self.successful_combinations > self.completed_combinations:
            raise ValueError("successful combinations cannot exceed completed combinations")
        if self.status == ParameterSearchStatus.RUNNING and self.started_at is None:
            raise ValueError("running parameter search requires started_at")
        if self.status in {
            ParameterSearchStatus.SUCCEEDED,
            ParameterSearchStatus.CANCELLED,
            ParameterSearchStatus.FAILED,
        } and self.finished_at is None:
            raise ValueError("terminal parameter search requires finished_at")
        return self


class ParameterSearchAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    search_id: str
    task_id: str
    status: ParameterSearchStatus
    total_combinations: StrictInt
    deduplicated: bool
    research_notice: str = RESEARCH_ONLY_NOTICE


class ParameterSearchDetail(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    search: ParameterSearchRecord
    task: DomainTask | None


class ParameterSearchCancelResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    search_id: str
    task_id: str
    search_status: ParameterSearchStatus
    task_status: DomainTaskStatus


class ParameterSearchPage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[ParameterSearchRecord, ...]
    page: StrictInt = Field(ge=1)
    page_size: StrictInt = Field(ge=1, le=200)
    total: StrictInt = Field(ge=0)


class ParameterResultPage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[ParameterCombinationResult, ...]
    page: StrictInt = Field(ge=1)
    page_size: StrictInt = Field(ge=1, le=200)
    total: StrictInt = Field(ge=0)
    selected_combination_index: StrictInt | None = None
    research_notice: str = RESEARCH_ONLY_NOTICE


class ParameterSearchPlanner:
    """Create deterministic combinations and trading-session windows."""

    def build(
        self,
        request: ParameterSearchRequest,
        trading_dates: Sequence[date],
    ) -> ParameterSearchPlan:
        dates = tuple(trading_dates)
        if not dates or dates != tuple(sorted(set(dates))):
            raise ParameterSearchValidationError(
                "trading dates must be a non-empty sorted unique sequence"
            )
        combinations = self._combinations(request.axes)
        windows = (
            self._split_windows(request, dates)
            if request.mode == ParameterSearchMode.SPLIT
            else self._walk_forward_windows(request, dates)
        )
        shared_request = request.base_request.model_dump(
            mode="json", exclude={"parameter_overrides"}
        )
        return ParameterSearchPlan(
            combinations=combinations,
            windows=windows,
            trading_dates=dates,
            shared_input_checksum=_stable_checksum(
                {"base_request": shared_request, "trading_dates": dates}
            ),
        )

    @staticmethod
    def _combinations(
        axes: Sequence[ParameterGridAxis],
    ) -> tuple[ParameterCombination, ...]:
        names = [axis.name for axis in axes]
        result = []
        for index, selected in enumerate(product(*(axis.values for axis in axes))):
            values = dict(zip(names, selected, strict=True))
            result.append(
                ParameterCombination(
                    index=index,
                    values=values,
                    checksum=_stable_checksum(values),
                )
            )
        return tuple(result)

    @staticmethod
    def _split_windows(
        request: ParameterSearchRequest, dates: tuple[date, ...]
    ) -> tuple[EvaluationWindow, ...]:
        assert request.split is not None
        if not (request.base_request.start_date <= request.split.train_end < request.base_request.end_date):
            raise ParameterSearchValidationError("train_end must be inside the backtest interval")
        if not (request.split.train_end < request.split.validation_end < request.base_request.end_date):
            raise ParameterSearchValidationError(
                "validation_end must be after train_end and before end_date"
            )
        groups = (
            (EvaluationSegment.TRAIN, tuple(day for day in dates if day <= request.split.train_end)),
            (
                EvaluationSegment.VALIDATION,
                tuple(day for day in dates if request.split.train_end < day <= request.split.validation_end),
            ),
            (EvaluationSegment.TEST, tuple(day for day in dates if day > request.split.validation_end)),
        )
        if any(not group for _, group in groups):
            raise ParameterSearchValidationError(
                "train, validation, and test must each contain at least one trading session"
            )
        return tuple(
            EvaluationWindow(
                fold=0,
                segment=segment,
                start_date=group[0],
                end_date=group[-1],
                session_count=len(group),
            )
            for segment, group in groups
        )

    @staticmethod
    def _walk_forward_windows(
        request: ParameterSearchRequest, dates: tuple[date, ...]
    ) -> tuple[EvaluationWindow, ...]:
        assert request.walk_forward is not None
        config = request.walk_forward
        required = config.train_sessions + config.validation_sessions + config.test_sessions
        if len(dates) < required:
            raise ParameterSearchValidationError(
                f"walk-forward configuration requires {required} trading sessions; found {len(dates)}"
            )
        windows: list[EvaluationWindow] = []
        start = 0
        fold = 0
        while start + required <= len(dates) and fold < config.max_folds:
            train_end = start + config.train_sessions
            validation_end = train_end + config.validation_sessions
            test_end = validation_end + config.test_sessions
            sections = (
                (EvaluationSegment.TRAIN, dates[start:train_end]),
                (EvaluationSegment.VALIDATION, dates[train_end:validation_end]),
                (EvaluationSegment.TEST, dates[validation_end:test_end]),
            )
            windows.extend(
                EvaluationWindow(
                    fold=fold,
                    segment=segment,
                    start_date=section[0],
                    end_date=section[-1],
                    session_count=len(section),
                )
                for segment, section in sections
            )
            fold += 1
            start += config.step_sessions
        return tuple(windows)


def calculate_window_performance(
    equity: Sequence[BacktestEquityDailyRecord],
    windows: Sequence[EvaluationWindow],
    *,
    initial_equity: Decimal,
) -> tuple[WindowPerformance, ...]:
    """Evaluate only ledger observations visible inside each declared window."""

    ordered = tuple(sorted(equity, key=lambda item: item.trade_date))
    output: list[WindowPerformance] = []
    for window in windows:
        points = tuple(
            item
            for item in ordered
            if window.start_date <= item.trade_date <= window.end_date
        )
        prior = next(
            (item.equity for item in reversed(ordered) if item.trade_date < window.start_date),
            initial_equity,
        )
        if not points or prior <= 0:
            output.append(
                WindowPerformance(
                    fold=window.fold,
                    segment=window.segment,
                    start_date=window.start_date,
                    end_date=window.end_date,
                    observations=0,
                )
            )
            continue
        returns: list[Decimal] = []
        previous = prior
        peak = prior
        max_drawdown = Decimal("0")
        for point in points:
            returns.append(point.equity / previous - 1)
            previous = point.equity
            peak = max(peak, point.equity)
            max_drawdown = min(max_drawdown, point.equity / peak - 1)
        volatility = _sample_stddev(returns)
        if volatility is not None:
            with localcontext() as ctx:
                ctx.prec = 28
                volatility *= Decimal(252).sqrt()
        output.append(
            WindowPerformance(
                fold=window.fold,
                segment=window.segment,
                start_date=window.start_date,
                end_date=window.end_date,
                observations=len(points),
                total_return=points[-1].equity / prior - 1,
                max_drawdown=max_drawdown,
                annualized_volatility=volatility,
            )
        )
    return tuple(output)


def _mean(values: Sequence[Decimal]) -> Decimal | None:
    return None if not values else sum(values, Decimal("0")) / len(values)


def _sample_stddev(values: Sequence[Decimal]) -> Decimal | None:
    if len(values) < 2:
        return None
    mean = _mean(values)
    assert mean is not None
    variance = sum((value - mean) ** 2 for value in values) / Decimal(len(values) - 1)
    with localcontext() as ctx:
        ctx.prec = 28
        return variance.sqrt()


def summarize_window_returns(
    windows: Sequence[WindowPerformance], segment: EvaluationSegment
) -> Decimal | None:
    return _mean(
        [
            item.total_return
            for item in windows
            if item.segment == segment and item.total_return is not None
        ]
    )


def apply_stability_and_ranking(
    results: Sequence[ParameterCombinationResult],
    axes: Sequence[ParameterGridAxis],
) -> tuple[ParameterCombinationResult, ...]:
    """Rank by validation only while retaining untouched test evidence."""

    successful = [
        item
        for item in results
        if item.status == BacktestRunStatus.SUCCEEDED
        and item.validation_mean_return is not None
    ]
    ranked = sorted(
        successful,
        key=lambda item: (-item.validation_mean_return, item.combination_index),
    )
    ranks = {item.combination_index: rank for rank, item in enumerate(ranked, 1)}
    selected = ranked[0].combination_index if ranked else None
    axis_positions = {
        axis.name: {
            _stable_checksum({"value": value}): index
            for index, value in enumerate(axis.values)
        }
        for axis in axes
    }

    output = []
    for item in results:
        neighbors = []
        if item.validation_mean_return is not None:
            for candidate in successful:
                if candidate.combination_index == item.combination_index:
                    continue
                differences = 0
                adjacent = True
                for axis in axes:
                    left = axis_positions[axis.name][_stable_checksum({"value": item.parameters[axis.name]})]
                    right = axis_positions[axis.name][_stable_checksum({"value": candidate.parameters[axis.name]})]
                    if left != right:
                        differences += 1
                        adjacent = adjacent and abs(left - right) == 1
                if differences == 1 and adjacent:
                    assert candidate.validation_mean_return is not None
                    neighbors.append(candidate.validation_mean_return)
        neighbor_dispersion = _sample_stddev(
            ([item.validation_mean_return] if item.validation_mean_return is not None else [])
            + neighbors
        )
        fold_validation = [
            window.total_return
            for window in item.windows
            if window.segment == EvaluationSegment.VALIDATION
            and window.total_return is not None
        ]
        fold_dispersion = _sample_stddev(fold_validation)
        test_values = [
            window.total_return
            for window in item.windows
            if window.segment == EvaluationSegment.TEST and window.total_return is not None
        ]
        positive_ratio = (
            Decimal(sum(value > 0 for value in test_values)) / len(test_values)
            if test_values
            else None
        )
        penalty = (neighbor_dispersion or Decimal("0")) + (
            fold_dispersion or Decimal("0")
        )
        stability = StabilityEvidence(
            neighboring_combinations=len(neighbors),
            neighboring_validation_dispersion=neighbor_dispersion,
            fold_validation_dispersion=fold_dispersion,
            positive_test_fold_ratio=positive_ratio,
            stability_score=Decimal("1") / (Decimal("1") + abs(penalty)),
        )
        output.append(
            item.model_copy(
                update={
                    "stability": stability,
                    "validation_rank": ranks.get(item.combination_index),
                    "selected_candidate": item.combination_index == selected,
                }
            )
        )
    return tuple(sorted(output, key=lambda item: item.combination_index))


class ParameterSearchRepository:
    SEARCHES_COLLECTION = "backtest_parameter_searches"
    RESULTS_COLLECTION = "backtest_parameter_results"

    def __init__(self, db: Any):
        self.db = db
        self._indexes_ready = False
        self._index_lock = asyncio.Lock()

    async def ensure_indexes(self) -> None:
        if self._indexes_ready:
            return
        async with self._index_lock:
            if self._indexes_ready:
                return
            searches = self.db[self.SEARCHES_COLLECTION]
            results = self.db[self.RESULTS_COLLECTION]
            await searches.create_index([("search_id", ASCENDING)], unique=True, name="parameter_search_id")
            await searches.create_index(
                [("user_id", ASCENDING), ("created_at", DESCENDING)],
                name="parameter_search_owner_created",
            )
            await searches.create_index(
                [("user_id", ASCENDING), ("status", ASCENDING), ("updated_at", ASCENDING)],
                name="parameter_search_owner_state",
            )
            await results.create_index(
                [("user_id", ASCENDING), ("search_id", ASCENDING), ("combination_index", ASCENDING)],
                unique=True,
                name="parameter_result_identity",
            )
            await results.create_index(
                [("user_id", ASCENDING), ("search_id", ASCENDING), ("validation_rank", ASCENDING)],
                name="parameter_result_rank",
            )
            self._indexes_ready = True

    async def create(self, record: ParameterSearchRecord) -> ParameterSearchRecord:
        await self.ensure_indexes()
        key = {"search_id": record.search_id, "user_id": record.user_id}
        await self.db[self.SEARCHES_COLLECTION].update_one(
            key, {"$setOnInsert": record.model_dump(mode="json")}, upsert=True
        )
        existing = await self.get(record.search_id, user_id=record.user_id)
        if existing is None:
            raise RuntimeError("parameter search was not persisted")
        for field in ("task_id", "request", "shared_input_checksum"):
            if getattr(existing, field) != getattr(record, field):
                raise ParameterSearchConflict(
                    f"search_id already exists with different {field}"
                )
        return existing

    async def get(self, search_id: str, *, user_id: str) -> ParameterSearchRecord | None:
        document = await self.db[self.SEARCHES_COLLECTION].find_one(
            {"search_id": search_id, "user_id": user_id}
        )
        return None if document is None else self._parse(ParameterSearchRecord, document)

    async def list(
        self,
        *,
        user_id: str,
        status: ParameterSearchStatus | None,
        page: int,
        page_size: int,
    ) -> ParameterSearchPage:
        self._validate_page(page, page_size)
        query: dict[str, Any] = {"user_id": user_id}
        if status is not None:
            query["status"] = status.value
        collection = self.db[self.SEARCHES_COLLECTION]
        total = await collection.count_documents(query)
        documents = await (
            collection.find(query)
            .sort([("created_at", DESCENDING), ("search_id", DESCENDING)])
            .skip((page - 1) * page_size)
            .limit(page_size)
            .to_list(length=page_size)
        )
        return ParameterSearchPage(
            items=tuple(self._parse(ParameterSearchRecord, item) for item in documents),
            page=page,
            page_size=page_size,
            total=total,
        )

    async def list_results(
        self, *, search_id: str, user_id: str, page: int, page_size: int
    ) -> ParameterResultPage:
        self._validate_page(page, page_size)
        search = await self.get(search_id, user_id=user_id)
        if search is None:
            raise ParameterSearchNotFound("parameter search does not exist")
        query = {"search_id": search_id, "user_id": user_id}
        collection = self.db[self.RESULTS_COLLECTION]
        total = await collection.count_documents(query)
        documents = await (
            collection.find(query)
            .sort([("combination_index", ASCENDING)])
            .skip((page - 1) * page_size)
            .limit(page_size)
            .to_list(length=page_size)
        )
        return ParameterResultPage(
            items=tuple(self._parse(ParameterCombinationResult, item) for item in documents),
            page=page,
            page_size=page_size,
            total=total,
            selected_combination_index=search.selected_combination_index,
        )

    async def upsert_result(self, result: ParameterCombinationResult) -> None:
        await self.ensure_indexes()
        await self.db[self.RESULTS_COLLECTION].update_one(
            {
                "search_id": result.search_id,
                "user_id": result.user_id,
                "combination_index": result.combination_index,
            },
            {"$set": result.model_dump(mode="json")},
            upsert=True,
        )

    async def all_results(
        self, *, search_id: str, user_id: str
    ) -> tuple[ParameterCombinationResult, ...]:
        documents = await self.db[self.RESULTS_COLLECTION].find(
            {"search_id": search_id, "user_id": user_id}
        ).sort([("combination_index", ASCENDING)]).to_list(length=HARD_COMBINATION_LIMIT)
        return tuple(self._parse(ParameterCombinationResult, item) for item in documents)

    async def mark_running(self, search_id: str, *, user_id: str) -> ParameterSearchRecord:
        current = await self.get(search_id, user_id=user_id)
        if current is None:
            raise ParameterSearchNotFound("parameter search does not exist")
        if current.status == ParameterSearchStatus.RUNNING:
            return current
        if current.status != ParameterSearchStatus.QUEUED:
            raise ParameterSearchConflict(f"search in {current.status.value} cannot start")
        now = _utc_now().isoformat()
        document = await self.db[self.SEARCHES_COLLECTION].find_one_and_update(
            {"search_id": search_id, "user_id": user_id, "status": "queued"},
            {"$set": {"status": "running", "started_at": now, "updated_at": now, "error": None}},
            return_document=ReturnDocument.AFTER,
        )
        if document is None:
            raise ParameterSearchConflict("parameter search changed while starting")
        return self._parse(ParameterSearchRecord, document)

    async def update_progress(
        self, search_id: str, *, user_id: str, completed: int, successful: int
    ) -> None:
        await self.db[self.SEARCHES_COLLECTION].update_one(
            {"search_id": search_id, "user_id": user_id, "status": "running"},
            {"$set": {
                "completed_combinations": completed,
                "successful_combinations": successful,
                "updated_at": _utc_now().isoformat(),
            }},
        )

    async def mark_terminal(
        self,
        search_id: str,
        *,
        user_id: str,
        status: ParameterSearchStatus,
        selected_combination_index: int | None = None,
        error: dict[str, Any] | None = None,
    ) -> ParameterSearchRecord:
        if status not in {ParameterSearchStatus.SUCCEEDED, ParameterSearchStatus.CANCELLED, ParameterSearchStatus.FAILED}:
            raise ValueError("terminal parameter-search status required")
        current = await self.get(search_id, user_id=user_id)
        if current is None:
            raise ParameterSearchNotFound("parameter search does not exist")
        if current.status == status:
            return current
        allowed = [ParameterSearchStatus.RUNNING.value]
        if status == ParameterSearchStatus.CANCELLED:
            allowed.append(ParameterSearchStatus.QUEUED.value)
        now = _utc_now().isoformat()
        document = await self.db[self.SEARCHES_COLLECTION].find_one_and_update(
            {"search_id": search_id, "user_id": user_id, "status": {"$in": allowed}},
            {"$set": {
                "status": status.value,
                "selected_combination_index": selected_combination_index,
                "error": error,
                "finished_at": now,
                "updated_at": now,
            }},
            return_document=ReturnDocument.AFTER,
        )
        if document is None:
            raise ParameterSearchConflict("parameter search changed before terminal transition")
        return self._parse(ParameterSearchRecord, document)

    @staticmethod
    def _validate_page(page: int, page_size: int) -> None:
        if page < 1 or not 1 <= page_size <= 200:
            raise ValueError("invalid pagination")

    @staticmethod
    def _parse(model: type[BaseModel], document: Mapping[str, Any]):
        payload = dict(document)
        payload.pop("_id", None)
        return model.model_validate(payload)


class ParameterSearchService:
    def __init__(
        self,
        *,
        repository: ParameterSearchRepository,
        backtests: BacktestRepository,
        tasks: DomainTaskRepository,
        strategies: StrategyRepository,
        data_service: PointInTimeBacktestDataService | None = None,
        planner: ParameterSearchPlanner | None = None,
    ) -> None:
        self.repository = repository
        self.backtests = backtests
        self.tasks = tasks
        self.strategies = strategies
        self.data_service = data_service or PointInTimeBacktestDataService(repository=backtests)
        self.planner = planner or ParameterSearchPlanner()

    async def create(
        self,
        *,
        user_id: str,
        request: ParameterSearchRequest,
        client_idempotency_key: str | None = None,
    ) -> ParameterSearchAccepted:
        payload = request.model_dump(mode="json")
        checksum = _stable_checksum(payload)
        client_key = client_idempotency_key or checksum
        digest = hashlib.sha256(f"{user_id}\x1f{client_key}".encode()).hexdigest()
        durable_key = f"parameter-search:{digest}"
        search_id = str(uuid5(NAMESPACE_URL, f"search:{durable_key}"))
        task_id = str(uuid5(NAMESPACE_URL, f"task:{durable_key}"))
        existing = await self.repository.get(search_id, user_id=user_id)
        if existing is not None:
            if existing.request != payload:
                raise ParameterSearchConflict(
                    "idempotency key was already used with a different request"
                )
            task = await self.tasks.get_task(existing.task_id, user_id)
            if task is None:
                task = await self._create_task(user_id, existing.task_id, search_id, durable_key)
            return ParameterSearchAccepted(
                search_id=search_id,
                task_id=task.task_id,
                status=existing.status,
                total_combinations=existing.total_combinations,
                deduplicated=True,
            )
        strategy = await self.strategies.get_version(
            request.base_request.strategy_version_id,
            user_id=user_id,
            include_system=True,
        )
        if strategy is None or strategy.status != StrategyVersionStatus.PUBLISHED:
            raise ParameterSearchValidationError(
                "published strategy version is unavailable to this user"
            )
        if strategy.market != request.base_request.market:
            raise ParameterSearchValidationError("strategy and backtest markets must match")
        try:
            dates = self.data_service.validate_request_window(request.base_request)
            plan = self.planner.build(request, dates)
        except ValueError as exc:
            if isinstance(exc, ParameterSearchValidationError):
                raise
            raise ParameterSearchValidationError(str(exc)) from exc
        record = await self.repository.create(
            ParameterSearchRecord(
                search_id=search_id,
                task_id=task_id,
                user_id=user_id,
                name=request.name,
                strategy_version_id=request.base_request.strategy_version_id,
                market=request.base_request.market.value,
                request=payload,
                input_versions={
                    "strategy": (str(strategy.checksum),),
                    "factors": tuple(
                        f"{item.factor_id}:{item.version}:{item.checksum}"
                        for item in strategy.factor_dependencies
                    ),
                    "skills": tuple(
                        f"{item.skill_id}:{item.version}:{item.checksum}"
                        for item in strategy.skill_dependencies
                    ),
                },
                total_combinations=len(plan.combinations),
                shared_input_checksum=plan.shared_input_checksum,
                windows=plan.windows,
            )
        )
        task = await self._create_task(user_id, task_id, search_id, durable_key)
        return ParameterSearchAccepted(
            search_id=record.search_id,
            task_id=task.task_id,
            status=record.status,
            total_combinations=record.total_combinations,
            deduplicated=False,
        )

    async def _create_task(self, user_id: str, task_id: str, search_id: str, durable_key: str) -> DomainTask:
        try:
            return await self.tasks.create_task(
                user_id=user_id,
                task_type=DomainTaskType.BACKTEST,
                payload={"parameter_search_id": search_id},
                idempotency_key=durable_key,
                task_id=task_id,
                stage="parameter_search_queued",
                message="Parameter search queued",
            )
        except IdempotencyConflictError as exc:
            raise ParameterSearchConflict(str(exc)) from exc

    async def detail(self, *, user_id: str, search_id: str) -> ParameterSearchDetail:
        search = await self.repository.get(search_id, user_id=user_id)
        if search is None:
            raise ParameterSearchNotFound("parameter search does not exist")
        return ParameterSearchDetail(
            search=search,
            task=await self.tasks.get_task(search.task_id, user_id),
        )

    async def list(
        self, *, user_id: str, status: ParameterSearchStatus | None, page: int, page_size: int
    ) -> ParameterSearchPage:
        return await self.repository.list(
            user_id=user_id, status=status, page=page, page_size=page_size
        )

    async def results(
        self, *, user_id: str, search_id: str, page: int, page_size: int
    ) -> ParameterResultPage:
        return await self.repository.list_results(
            search_id=search_id, user_id=user_id, page=page, page_size=page_size
        )

    async def cancel(self, *, user_id: str, search_id: str) -> ParameterSearchCancelResult:
        search = await self.repository.get(search_id, user_id=user_id)
        if search is None:
            raise ParameterSearchNotFound("parameter search does not exist")
        task = await self.tasks.get_task(search.task_id, user_id)
        if task is None:
            raise ParameterSearchConflict("durable task for parameter search is missing")
        if search.status == ParameterSearchStatus.CANCELLED and task.status == DomainTaskStatus.CANCELLED:
            return ParameterSearchCancelResult(
                search_id=search_id,
                task_id=task.task_id,
                search_status=search.status,
                task_status=task.status,
            )
        try:
            task = await self.tasks.request_cancel(task_id=task.task_id, user_id=user_id)
        except TaskNotCancellableError as exc:
            raise ParameterSearchConflict(str(exc)) from exc
        if task is None:
            raise ParameterSearchConflict("durable task for parameter search is missing")
        if task.status == DomainTaskStatus.CANCELLED and search.status == ParameterSearchStatus.QUEUED:
            search = await self.repository.mark_terminal(
                search_id, user_id=user_id, status=ParameterSearchStatus.CANCELLED
            )
        return ParameterSearchCancelResult(
            search_id=search_id,
            task_id=task.task_id,
            search_status=search.status,
            task_status=task.status,
        )


class ChildBacktestExecutor(Protocol):
    async def __call__(
        self,
        *,
        run_id: str,
        user_id: str,
        task_id: str,
        report_progress: ProgressCallback,
        is_cancelled: CancellationChecker,
    ) -> BacktestRunRecord: ...


class SharedReadOnlyInputCache:
    """Keep one immutable point-in-time bundle per durable search checksum.

    A candidate loader may still need to build its parameter-dependent policy,
    but every child engine receives the same frozen bundle object. A changed
    bundle checksum is rejected, preventing retries or data refreshes from
    silently changing the experiment's historical inputs.
    """

    def __init__(self) -> None:
        self._bundles: dict[str, BacktestInputBundle] = {}

    def share(
        self, shared_input_checksum: str, candidate: BacktestInputBundle
    ) -> BacktestInputBundle:
        current = self._bundles.get(shared_input_checksum)
        if current is None:
            self._bundles[shared_input_checksum] = candidate
            return candidate
        if current.bundle_checksum != candidate.bundle_checksum:
            raise ParameterSearchConflict(
                "child run resolved different point-in-time inputs for one search"
            )
        return current


class ParameterSearchRunner:
    """Execute retry-safe child runs and persist research evidence."""

    def __init__(
        self,
        *,
        repository: ParameterSearchRepository,
        backtests: BacktestRepository,
        engine: BacktestEngine | None = None,
        child_executor: ChildBacktestExecutor | None = None,
        planner: ParameterSearchPlanner | None = None,
    ) -> None:
        if (engine is None) == (child_executor is None):
            raise ValueError("provide exactly one of engine or child_executor")
        self.repository = repository
        self.backtests = backtests
        if engine is not None:
            shared_cache = SharedReadOnlyInputCache()
            original_loader = engine.plan_loader

            async def cached_plan_loader(run: BacktestRunRecord):
                plan = await original_loader(run)
                checksums = run.input_versions.get("parameter_search_shared_input", ())
                if len(checksums) != 1:
                    raise ParameterSearchConflict(
                        "parameter-search child is missing its shared input identity"
                    )
                return replace(
                    plan,
                    bundle=shared_cache.share(checksums[0], plan.bundle),
                )

            cached_engine = BacktestEngine(
                backtests,
                plan_loader=cached_plan_loader,
                broker=engine.broker,
                market_rules=engine.market_rules,
            )
            self.child_executor = cached_engine.run
        else:
            assert child_executor is not None
            self.child_executor = child_executor
        self.planner = planner or ParameterSearchPlanner()

    async def run(
        self,
        *,
        search_id: str,
        user_id: str,
        task_id: str,
        report_progress: ProgressCallback,
        is_cancelled: CancellationChecker,
    ) -> ParameterSearchRecord:
        search = await self.repository.get(search_id, user_id=user_id)
        if search is None:
            raise ParameterSearchNotFound("parameter search does not exist")
        if search.task_id != task_id:
            raise ParameterSearchConflict("parameter search belongs to another durable task")
        if search.status == ParameterSearchStatus.SUCCEEDED:
            return search
        search = await self.repository.mark_running(search_id, user_id=user_id)
        request = ParameterSearchRequest.model_validate(search.request)
        if not search.windows:
            raise ParameterSearchConflict("stored evaluation windows are empty")
        existing = {item.combination_index: item for item in await self.repository.all_results(search_id=search_id, user_id=user_id)}
        for combination in self.planner._combinations(request.axes):
            if await is_cancelled():
                await self.repository.mark_terminal(
                    search_id, user_id=user_id, status=ParameterSearchStatus.CANCELLED
                )
                raise TaskCancellationRequested("parameter search was cancelled")
            prior = existing.get(combination.index)
            if prior is not None and prior.status == BacktestRunStatus.SUCCEEDED:
                continue
            child_run_id = str(uuid5(NAMESPACE_URL, f"parameter-search:{search_id}:{combination.checksum}"))
            child_request = request.base_request.model_copy(
                update={
                    "parameter_overrides": {
                        **request.base_request.parameter_overrides,
                        **combination.values,
                    },
                    "notes": f"parameter-search:{search_id}:{combination.index}",
                }
            )
            child = await self.backtests.create_run(
                BacktestRunRecord(
                    run_id=child_run_id,
                    task_id=task_id,
                    user_id=user_id,
                    strategy_version_id=child_request.strategy_version_id,
                    market=child_request.market,
                    request=child_request.model_dump(mode="json"),
                    input_versions={
                        **search.input_versions,
                        "parameter_search_shared_input": (search.shared_input_checksum,),
                    },
                )
            )
            if child.input_versions.get("parameter_search_shared_input") != (
                search.shared_input_checksum,
            ):
                raise ParameterSearchConflict(
                    "existing child run has a different shared input identity"
                )

            async def child_progress(value: float, stage: str, message: str | None = None) -> None:
                overall = (combination.index + min(max(value, 0.0), 1.0)) / search.total_combinations
                await report_progress(
                    overall,
                    f"parameter_search_{stage}"[:120],
                    message or f"Combination {combination.index + 1}/{search.total_combinations}",
                )

            try:
                if child.status != BacktestRunStatus.SUCCEEDED:
                    child = await self.child_executor(
                        run_id=child_run_id,
                        user_id=user_id,
                        task_id=task_id,
                        report_progress=child_progress,
                        is_cancelled=is_cancelled,
                    )
                result = await self._successful_result(search, combination, child)
            except TaskCancellationRequested:
                await self.repository.mark_terminal(
                    search_id, user_id=user_id, status=ParameterSearchStatus.CANCELLED
                )
                raise
            except (BacktestPersistenceConflict, ParameterSearchError):
                raise
            except PyMongoError:
                raise
            except Exception as exc:
                current = await self.backtests.get_run(child_run_id, user_id=user_id)
                if current is not None and current.status == BacktestRunStatus.RUNNING:
                    current = await self.backtests.mark_run_failed(
                        child_run_id,
                        user_id=user_id,
                        error={"code": "PARAMETER_COMBINATION_FAILED", "message": str(exc), "exception_type": type(exc).__name__},
                    )
                result = ParameterCombinationResult(
                    search_id=search_id,
                    user_id=user_id,
                    combination_index=combination.index,
                    parameters=combination.values,
                    child_run_id=child_run_id,
                    status=current.status if current is not None else BacktestRunStatus.FAILED,
                    error={"code": "PARAMETER_COMBINATION_FAILED", "message": str(exc), "exception_type": type(exc).__name__},
                    completed_at=_utc_now(),
                )
            await self.repository.upsert_result(result)
            existing[combination.index] = result
            completed = sum(item.status in {BacktestRunStatus.SUCCEEDED, BacktestRunStatus.FAILED, BacktestRunStatus.CANCELLED} for item in existing.values())
            successful = sum(item.status == BacktestRunStatus.SUCCEEDED for item in existing.values())
            await self.repository.update_progress(
                search_id, user_id=user_id, completed=completed, successful=successful
            )
            await report_progress(
                completed / search.total_combinations,
                "parameter_search_running",
                f"Completed {completed}/{search.total_combinations} combinations",
            )
        persisted_results = await self.repository.all_results(
            search_id=search_id, user_id=user_id
        )
        await self.repository.update_progress(
            search_id,
            user_id=user_id,
            completed=sum(
                item.status
                in {
                    BacktestRunStatus.SUCCEEDED,
                    BacktestRunStatus.FAILED,
                    BacktestRunStatus.CANCELLED,
                }
                for item in persisted_results
            ),
            successful=sum(
                item.status == BacktestRunStatus.SUCCEEDED
                for item in persisted_results
            ),
        )
        final_results = apply_stability_and_ranking(persisted_results, request.axes)
        for result in final_results:
            await self.repository.upsert_result(result)
        selected = next(
            (item.combination_index for item in final_results if item.selected_candidate), None
        )
        if selected is None:
            await self.repository.mark_terminal(
                search_id,
                user_id=user_id,
                status=ParameterSearchStatus.FAILED,
                error={"code": "PARAMETER_SEARCH_NO_SUCCESSFUL_COMBINATION", "message": "No combination produced validation evidence"},
            )
            raise ParameterSearchValidationError(
                "no combination produced validation evidence"
            )
        await report_progress(1.0, "parameter_search_succeeded", RESEARCH_ONLY_NOTICE)
        return await self.repository.mark_terminal(
            search_id,
            user_id=user_id,
            status=ParameterSearchStatus.SUCCEEDED,
            selected_combination_index=selected,
        )

    async def _successful_result(
        self,
        search: ParameterSearchRecord,
        combination: ParameterCombination,
        child: BacktestRunRecord,
    ) -> ParameterCombinationResult:
        if child.status != BacktestRunStatus.SUCCEEDED:
            raise ParameterSearchConflict("child executor returned a non-succeeded run")
        documents = await self.backtests.get_db()[self.backtests.EQUITY_COLLECTION].find(
            {"run_id": child.run_id, "user_id": search.user_id}
        ).sort([("trade_date", ASCENDING)]).to_list(length=None)
        equity = tuple(
            BacktestEquityDailyRecord.model_validate(
                {key: value for key, value in document.items() if key not in {"_id", "record_checksum"}}
            )
            for document in documents
        )
        base = BacktestRequest.model_validate(search.request["base_request"])
        windows = calculate_window_performance(
            equity, search.windows, initial_equity=base.initial_cash
        )
        return ParameterCombinationResult(
            search_id=search.search_id,
            user_id=search.user_id,
            combination_index=combination.index,
            parameters=combination.values,
            child_run_id=child.run_id,
            status=child.status,
            train_mean_return=summarize_window_returns(windows, EvaluationSegment.TRAIN),
            validation_mean_return=summarize_window_returns(windows, EvaluationSegment.VALIDATION),
            test_mean_return=summarize_window_returns(windows, EvaluationSegment.TEST),
            windows=windows,
            completed_at=_utc_now(),
        )

ParameterSearchExecutor = Callable[..., Awaitable[ParameterSearchRecord]]


def result_ref(search: ParameterSearchRecord) -> DomainTaskResultRef:
    return DomainTaskResultRef(
        collection=ParameterSearchRepository.SEARCHES_COLLECTION,
        id=search.search_id,
    )
