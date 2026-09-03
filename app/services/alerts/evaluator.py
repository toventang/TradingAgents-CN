"""Shared snapshot loading and pure condition evaluation for alert batches."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping, Protocol
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.alert import (
    AlertCompareOperator,
    AlertMarket,
    AlertQualityStatus,
    AlertRule,
    AlertStateValue,
    AllAlertCondition,
    AnyAlertCondition,
    ChangeRateOperand,
    CompareAlertCondition,
    ConditionState,
    ConstantOperand,
    CurrentValueOperand,
    FactorOperand,
    NotAlertCondition,
    PaperAccountScope,
    PaperPositionScope,
    PreviousValueOperand,
    StrategyUniverseScope,
    SymbolScope,
    SystemScope,
    WatchlistScope,
    CrossAlertCondition,
    stable_checksum,
)
from app.services.alerts.planner import (
    AlertBatchLock,
    AlertDataDependency,
    BatchPlanner,
    alert_time_bucket,
)
from app.services.alerts.state_machine import AlertEvaluation
from app.services.alerts.state_repository import (
    AlertEvaluationRun,
    AlertEventEvidence,
    AlertStateRepository,
    EvaluationRunStatus,
)
from app.services.calendars.market_calendar import MarketCalendarService


class AlertObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    current_value: AlertStateValue = None
    previous_value: AlertStateValue = None
    factors: dict[str, AlertStateValue] = Field(default_factory=dict)
    previous_factors: dict[str, AlertStateValue] = Field(default_factory=dict)
    change_rates: dict[int, Decimal] = Field(default_factory=dict)
    previous_change_rates: dict[int, Decimal] = Field(default_factory=dict)
    quote_time: datetime
    ingested_at: datetime
    source: str = Field(min_length=1, max_length=128)
    quality_status: AlertQualityStatus

    @field_validator("quote_time", "ingested_at")
    @classmethod
    def utc_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observation timestamps must be timezone-aware")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def ordered_evidence_times(self) -> "AlertObservation":
        if self.ingested_at < self.quote_time:
            raise ValueError("ingested_at cannot precede quote_time")
        return self


@dataclass(frozen=True)
class ScopeResolution:
    targets: tuple[str | None, ...]
    universe_snapshot_id: str | None
    symbols_checksum: str

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(item for item in self.targets if item is not None)


class AlertScopeResolver(Protocol):
    async def resolve(
        self,
        rule: AlertRule,
        *,
        evaluated_at: datetime,
    ) -> ScopeResolution: ...


@dataclass(frozen=True)
class AlertSnapshotRequest:
    market: AlertMarket
    evaluated_at: datetime
    rules: tuple[AlertRule, ...]
    targets: tuple[tuple[str, str | None], ...]
    dependencies: tuple[AlertDataDependency, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "market", AlertMarket(self.market))
        object.__setattr__(self, "evaluated_at", _aware_utc(self.evaluated_at))
        object.__setattr__(
            self,
            "dependencies",
            tuple(AlertDataDependency(item) for item in self.dependencies),
        )
        if len(set(self.targets)) != len(self.targets):
            raise ValueError("snapshot targets must be unique")


class AlertSnapshotLoader(Protocol):
    async def load(
        self,
        request: AlertSnapshotRequest,
    ) -> Mapping[tuple[str, str | None], AlertObservation]: ...


@dataclass(frozen=True)
class _FactorWindow:
    current: Mapping[str, AlertStateValue]
    previous: Mapping[str, AlertStateValue]
    observed_at: datetime
    source: str


class MongoAlertScopeResolver:
    """Resolve owner-scoped static and dynamic scopes to a frozen batch view."""

    def __init__(self, database):
        self.database = database

    async def resolve(
        self,
        rule: AlertRule,
        *,
        evaluated_at: datetime,
    ) -> ScopeResolution:
        timestamp = _aware_utc(evaluated_at)
        scope = rule.scope
        snapshot_id: str | None = None
        if isinstance(scope, SymbolScope):
            targets: tuple[str | None, ...] = (scope.symbol,)
        elif isinstance(scope, WatchlistScope) and scope.symbols:
            targets = tuple(sorted(scope.symbols))
        elif isinstance(scope, WatchlistScope):
            document = await self.database["watchlists"].find_one(
                {"watchlist_id": scope.watchlist_id, "user_id": rule.user_id}
            )
            symbols = tuple(sorted(set((document or {}).get("symbols", ()))))
            targets = symbols
            snapshot_id = stable_checksum(
                {
                    "scope": "watchlist",
                    "watchlist_id": scope.watchlist_id,
                    "symbols": symbols,
                    "time_bucket": alert_time_bucket(
                        timestamp, rule.frequency_seconds
                    ),
                }
            )
        elif isinstance(scope, StrategyUniverseScope):
            query = {
                "user_id": rule.user_id,
                "market": rule.market.value,
                "selection_definition.strategy_version_id": scope.strategy_version_id,
                "as_of": {"$lte": timestamp.isoformat()},
            }
            document = await self.database["universe_snapshots"].find_one(
                query,
                sort=[("trade_date", -1), ("universe_snapshot_id", -1)],
            )
            members = (document or {}).get("members", ())
            targets = tuple(
                sorted(
                    {
                        str(item["symbol"])
                        for item in members
                        if str(item.get("market")) == rule.market.value
                    }
                )
            )
            snapshot_id = (document or {}).get("universe_snapshot_id")
        elif isinstance(scope, PaperPositionScope):
            cursor = self.database["paper_positions"].find(
                {
                    "user_id": rule.user_id,
                    "market": rule.market.value,
                    "quantity": {"$gt": 0},
                }
            )
            documents = await cursor.to_list(length=None)
            targets = tuple(
                sorted(
                    {
                        str(item.get("symbol") or item.get("code"))
                        for item in documents
                        if item.get("symbol") or item.get("code")
                    }
                )
            )
            snapshot_id = stable_checksum(
                {
                    "scope": "paper_position",
                    "account_id": scope.account_id,
                    "symbols": targets,
                    "time_bucket": alert_time_bucket(
                        timestamp, rule.frequency_seconds
                    ),
                }
            )
        elif isinstance(scope, (PaperAccountScope, SystemScope)):
            targets = (None,)
        else:
            raise ValueError(f"unsupported alert scope: {scope.scope_type}")
        return ScopeResolution(
            targets=targets,
            universe_snapshot_id=snapshot_id,
            symbols_checksum=stable_checksum(
                tuple(item for item in targets if item is not None)
            ),
        )


class MongoAlertSnapshotLoader:
    """Load a batch's quote rows once and only already-published factor rows."""

    DEFAULT_STALE_AFTER_SECONDS = {
        AlertMarket.CN: 120,
        AlertMarket.HK: 240,
        AlertMarket.US: 240,
        AlertMarket.SYSTEM: 300,
    }

    def __init__(
        self,
        database,
        *,
        stale_after_seconds: Mapping[AlertMarket, int] | None = None,
    ):
        self.database = database
        self.stale_after_seconds = {
            **self.DEFAULT_STALE_AFTER_SECONDS,
            **dict(stale_after_seconds or {}),
        }

    async def load(
        self,
        request: AlertSnapshotRequest,
    ) -> Mapping[tuple[str, str | None], AlertObservation]:
        symbols = tuple(
            sorted({symbol for _, symbol in request.targets if symbol is not None})
        )
        quote_documents: list[dict[str, Any]] = []
        if symbols and AlertDataDependency.QUOTE in request.dependencies:
            cursor = self.database["market_quotes"].find(
                {
                    **(
                        {}
                        if request.market == AlertMarket.CN
                        else {"market": request.market.value}
                    ),
                    "$or": [
                        {"symbol": {"$in": symbols}},
                        {"code": {"$in": symbols}},
                    ],
                }
            )
            quote_documents = await cursor.to_list(length=None)
        quotes = {
            str(item.get("symbol") or item.get("code")): item
            for item in quote_documents
            if item.get("symbol") or item.get("code")
        }
        factor_values = await self._load_factor_values(request, symbols)
        result: dict[tuple[str, str | None], AlertObservation] = {}
        for owner, symbol in request.targets:
            quote = quotes.get(str(symbol)) if symbol is not None else None
            result[(owner, symbol)] = self._observation(
                request,
                quote,
                factor_values.get((owner, symbol)),
            )
        return result

    async def _load_factor_values(
        self,
        request: AlertSnapshotRequest,
        symbols: tuple[str, ...],
    ) -> dict[tuple[str, str | None], _FactorWindow]:
        if AlertDataDependency.FACTOR not in request.dependencies or not symbols:
            return {}
        requirements: dict[str, set[tuple[str, int]]] = {}
        for rule in request.rules:
            requirements.setdefault(rule.user_id, set()).update(_factor_refs(rule))
        owners = sorted(requirements)
        result: dict[tuple[str, str | None], _FactorWindow] = {}
        cutoff = request.evaluated_at.isoformat()
        for owner in owners:
            cursor = self.database["factor_snapshots"].find(
                {
                    "user_id": owner,
                    "market": request.market.value,
                    "status": "ready",
                    "published_at": {"$lte": cutoff},
                }
            ).sort(
                [("trade_date", -1), ("published_at", -1)]
            ).limit(20)
            candidates = await cursor.to_list(length=20)
            snapshots_by_requirement: dict[
                tuple[str, int], list[dict[str, Any]]
            ] = {item: [] for item in requirements[owner]}
            for snapshot in candidates:
                job = await self.database["factor_jobs"].find_one(
                    {"job_id": snapshot.get("job_id"), "user_id": owner}
                )
                references = {
                    (str(item.get("factor_id")), int(item.get("version", 1)))
                    for item in ((job or {}).get("request") or {}).get("factors", ())
                    if item.get("factor_id")
                }
                for requirement in snapshots_by_requirement:
                    if (
                        requirement in references
                        and len(snapshots_by_requirement[requirement]) < 2
                    ):
                        snapshots_by_requirement[requirement].append(snapshot)
                if all(len(items) >= 2 for items in snapshots_by_requirement.values()):
                    break
            selected = {
                str(snapshot["snapshot_id"]): snapshot
                for snapshots in snapshots_by_requirement.values()
                for snapshot in snapshots
            }
            if not selected:
                continue
            rows = self.database["factor_values"].find(
                {
                    "snapshot_id": {"$in": tuple(selected)},
                    "user_id": owner,
                    "symbol": {"$in": symbols},
                }
            )
            rows_by_snapshot: dict[str, dict[str, Mapping[str, AlertStateValue]]] = {}
            for row in await rows.to_list(length=None):
                rows_by_snapshot.setdefault(str(row["snapshot_id"]), {})[
                    str(row["symbol"])
                ] = dict(row.get("values", {}))
            for symbol in symbols:
                current_values: dict[str, AlertStateValue] = {}
                previous_values: dict[str, AlertStateValue] = {}
                observed_times: list[datetime] = []
                source_ids: list[str] = []
                for requirement, snapshots in snapshots_by_requirement.items():
                    factor_id, version = requirement
                    key = f"{factor_id}@{version}"
                    for index, snapshot in enumerate(snapshots[:2]):
                        snapshot_id = str(snapshot["snapshot_id"])
                        values = rows_by_snapshot.get(snapshot_id, {}).get(symbol, {})
                        if factor_id in values:
                            target = current_values if index == 0 else previous_values
                            target[key] = values[factor_id]
                        if index == 0:
                            observed_times.append(
                                _document_time(
                                    snapshot.get("published_at") or snapshot.get("as_of"),
                                    request.market,
                                )
                                or request.evaluated_at
                            )
                            source_ids.append(snapshot_id)
                if not current_values:
                    continue
                result[(owner, symbol)] = _FactorWindow(
                    current=current_values,
                    previous=previous_values,
                    observed_at=max(observed_times),
                    source=f"factor_snapshots:{stable_checksum(sorted(set(source_ids)))}",
                )
        return result

    def _observation(
        self,
        request: AlertSnapshotRequest,
        quote: Mapping[str, Any] | None,
        factors: _FactorWindow | None,
    ) -> AlertObservation:
        if quote is None:
            if factors is not None:
                return AlertObservation(
                    factors=dict(factors.current),
                    previous_factors=dict(factors.previous),
                    quote_time=factors.observed_at,
                    ingested_at=factors.observed_at,
                    source=factors.source,
                    quality_status=AlertQualityStatus.VALID,
                )
            return AlertObservation(
                quote_time=request.evaluated_at,
                ingested_at=request.evaluated_at,
                source="unavailable",
                quality_status=AlertQualityStatus.MISSING,
            )
        quote_time = _document_time(
            quote.get("quote_time")
            or quote.get("updated_at")
            or quote.get("trade_time"),
            request.market,
        )
        ingested_at = _document_time(
            quote.get("ingested_at") or quote.get("updated_at"),
            request.market,
        )
        if (
            quote_time is None
            or ingested_at is None
            or quote_time > request.evaluated_at
            or ingested_at > request.evaluated_at
        ):
            return AlertObservation(
                quote_time=request.evaluated_at,
                ingested_at=request.evaluated_at,
                source="invalid-timestamp",
                quality_status=AlertQualityStatus.ERROR,
                factors=dict(factors.current) if factors is not None else {},
                previous_factors=(
                    dict(factors.previous) if factors is not None else {}
                ),
            )
        stale = (
            request.evaluated_at - quote_time
        ).total_seconds() > self.stale_after_seconds[request.market]
        return AlertObservation(
            current_value=_first_present(quote, "close", "price"),
            previous_value=_first_present(quote, "pre_close", "previous_close"),
            factors=dict(factors.current) if factors is not None else {},
            previous_factors=dict(factors.previous) if factors is not None else {},
            quote_time=quote_time,
            ingested_at=max(quote_time, ingested_at),
            source=str(quote.get("source") or quote.get("data_source") or "market_quotes"),
            quality_status=(
                AlertQualityStatus.STALE if stale else AlertQualityStatus.VALID
            ),
        )


class PureAlertEvaluator:
    """Evaluate the closed condition tree without I/O or arbitrary expressions."""

    UNKNOWN_QUALITY = {
        AlertQualityStatus.STALE,
        AlertQualityStatus.MISSING,
        AlertQualityStatus.ERROR,
    }

    def evaluate(
        self,
        rule: AlertRule,
        observation: AlertObservation,
        *,
        evaluated_at: datetime,
        market_date: date,
    ) -> AlertEvaluation:
        timestamp = _aware_utc(evaluated_at)
        if (
            observation.quote_time > timestamp
            or observation.ingested_at > timestamp
            or observation.quality_status in self.UNKNOWN_QUALITY
        ):
            state = ConditionState.UNKNOWN
        else:
            state = self._condition(rule.trigger.condition, observation)
        return AlertEvaluation(
            condition_state=state,
            value=observation.current_value,
            evaluated_at=timestamp,
            market_date=market_date,
        )

    def _condition(self, condition, observation: AlertObservation) -> ConditionState:
        if isinstance(condition, AllAlertCondition):
            values = [self._condition(item, observation) for item in condition.children]
            if ConditionState.FALSE in values:
                return ConditionState.FALSE
            return ConditionState.UNKNOWN if ConditionState.UNKNOWN in values else ConditionState.TRUE
        if isinstance(condition, AnyAlertCondition):
            values = [self._condition(item, observation) for item in condition.children]
            if ConditionState.TRUE in values:
                return ConditionState.TRUE
            return ConditionState.UNKNOWN if ConditionState.UNKNOWN in values else ConditionState.FALSE
        if isinstance(condition, NotAlertCondition):
            value = self._condition(condition.child, observation)
            return {
                ConditionState.TRUE: ConditionState.FALSE,
                ConditionState.FALSE: ConditionState.TRUE,
                ConditionState.UNKNOWN: ConditionState.UNKNOWN,
            }[value]
        if isinstance(condition, CompareAlertCondition):
            left = self._operand(condition.left, observation, previous=False)
            right = self._operand(condition.right, observation, previous=False)
            upper = (
                self._operand(condition.upper, observation, previous=False)
                if condition.upper is not None
                else None
            )
            return _compare(left, condition.operator, right, upper)
        if isinstance(condition, CrossAlertCondition):
            current_left = self._operand(condition.left, observation, previous=False)
            current_right = self._operand(condition.right, observation, previous=False)
            previous_left = self._operand(condition.left, observation, previous=True)
            previous_right = self._operand(condition.right, observation, previous=True)
            if None in (current_left, current_right, previous_left, previous_right):
                return ConditionState.UNKNOWN
            before_operator = (
                AlertCompareOperator.LTE
                if condition.type == "cross_up"
                else AlertCompareOperator.GTE
            )
            after_operator = (
                AlertCompareOperator.GT
                if condition.type == "cross_up"
                else AlertCompareOperator.LT
            )
            before = _compare(previous_left, before_operator, previous_right, None)
            after = _compare(current_left, after_operator, current_right, None)
            if ConditionState.UNKNOWN in (before, after):
                return ConditionState.UNKNOWN
            return (
                ConditionState.TRUE
                if before == ConditionState.TRUE and after == ConditionState.TRUE
                else ConditionState.FALSE
            )
        raise TypeError(f"unsupported condition node: {type(condition).__name__}")

    @staticmethod
    def _operand(operand, observation: AlertObservation, *, previous: bool):
        if operand is None:
            return None
        if isinstance(operand, ConstantOperand):
            return operand.value
        if isinstance(operand, CurrentValueOperand):
            return observation.previous_value if previous else observation.current_value
        if isinstance(operand, PreviousValueOperand):
            return None if previous else observation.previous_value
        if isinstance(operand, FactorOperand):
            source = observation.previous_factors if previous else observation.factors
            if operand.lag > 1 or (previous and operand.lag > 0):
                return None
            if operand.lag == 1:
                source = observation.previous_factors
            versioned_key = f"{operand.factor_id}@{operand.version}"
            return source.get(versioned_key, source.get(operand.factor_id))
        if isinstance(operand, ChangeRateOperand):
            source = (
                observation.previous_change_rates
                if previous
                else observation.change_rates
            )
            return source.get(operand.window_seconds)
        return None


class AlertBatchExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str | None = None
    status: EvaluationRunStatus
    group_count: int = 0
    rule_count: int = 0
    target_count: int = 0
    evaluated_count: int = 0
    unknown_count: int = 0
    event_count: int = 0
    skipped_count: int = 0


class AlertEvaluationBatchService:
    def __init__(
        self,
        *,
        states: AlertStateRepository,
        lock: AlertBatchLock,
        scopes: AlertScopeResolver,
        snapshots: AlertSnapshotLoader,
        planner: BatchPlanner | None = None,
        evaluator: PureAlertEvaluator | None = None,
        calendar: Any = MarketCalendarService,
        clock=None,
    ):
        self.states = states
        self.lock = lock
        self.scopes = scopes
        self.snapshots = snapshots
        self.planner = planner or BatchPlanner(calendar)
        self.evaluator = evaluator or PureAlertEvaluator()
        self.calendar = calendar
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    async def execute(
        self,
        *,
        task_id: str,
        market: AlertMarket | str,
        frequency_seconds: int,
        evaluated_at: datetime,
        holidays: Iterable[str] = (),
        report_progress=None,
        is_cancelled=None,
    ) -> AlertBatchExecutionResult:
        normalized_market = AlertMarket(market)
        timestamp = _aware_utc(evaluated_at)
        bucket = alert_time_bucket(timestamp, frequency_seconds)
        run_id = str(
            uuid5(
                NAMESPACE_URL,
                f"alert-eval:{normalized_market.value}:{frequency_seconds}:{bucket}",
            )
        )
        lease = await self.lock.acquire(normalized_market, frequency_seconds, bucket)
        if lease is None:
            return AlertBatchExecutionResult(
                run_id=run_id,
                status=EvaluationRunStatus.SKIPPED_LOCKED,
            )
        run: AlertEvaluationRun | None = None
        group_count = rule_count = target_count = 0
        evaluated_count = unknown_count = event_count = skipped_count = 0
        try:
            candidate = AlertEvaluationRun(
                run_id=run_id,
                task_id=task_id,
                market=normalized_market.value,
                frequency_seconds=frequency_seconds,
                time_bucket=bucket,
                owner_token=lease.owner_token,
                started_at=_aware_utc(self.clock()),
            )
            run = await self.states.start_run(candidate)
            if (
                run.run_id != candidate.run_id
                or run.status != EvaluationRunStatus.RUNNING
                or run.owner_token != lease.owner_token
            ):
                return _result_from_run(run)

            rules = await self.states.list_enabled_rules(
                market=normalized_market.value,
                frequency_seconds=frequency_seconds,
                evaluated_at=timestamp,
            )
            plan = self.planner.plan(
                rules,
                market=normalized_market,
                frequency_seconds=frequency_seconds,
                evaluated_at=timestamp,
                holidays=holidays,
            )
            due_rules = tuple(rule for group in plan.groups for rule in group.rules)
            group_count = len(plan.groups)
            rule_count = len(due_rules)
            skipped_count = len(plan.skipped_rule_ids)
            resolutions: dict[str, ScopeResolution] = {}
            targets: set[tuple[str, str | None]] = set()
            for rule in due_rules:
                resolution = await self.scopes.resolve(rule, evaluated_at=timestamp)
                resolutions[rule.rule_id] = resolution
                targets.update((rule.user_id, symbol) for symbol in resolution.targets)
            dependencies = tuple(
                sorted(
                    {item for group in plan.groups for item in group.dependencies},
                    key=lambda item: item.value,
                )
            )
            observations = await self.snapshots.load(
                AlertSnapshotRequest(
                    market=normalized_market,
                    evaluated_at=timestamp,
                    rules=due_rules,
                    targets=tuple(sorted(targets, key=lambda item: (item[0], item[1] or ""))),
                    dependencies=dependencies,
                )
            )
            target_count = sum(len(item.targets) for item in resolutions.values())
            total = max(target_count, 1)
            market_date = _market_date(normalized_market, timestamp, self.calendar)
            for rule in due_rules:
                resolution = resolutions[rule.rule_id]
                for symbol in resolution.targets:
                    if is_cancelled is not None and await is_cancelled():
                        raise AlertBatchCancelled("alert evaluation batch was cancelled")
                    observation = observations.get((rule.user_id, symbol)) or _missing_observation(timestamp)
                    evaluation = self.evaluator.evaluate(
                        rule,
                        observation,
                        evaluated_at=timestamp,
                        market_date=market_date,
                    )
                    persisted = await self.states.apply(
                        rule,
                        scope_key=scope_key_for(rule, symbol),
                        symbol=symbol,
                        evaluation=evaluation,
                        evidence=AlertEventEvidence(
                            quote_time=observation.quote_time,
                            ingested_at=observation.ingested_at,
                            source=observation.source,
                            quality_status=observation.quality_status,
                            actual_symbols=resolution.symbols,
                            universe_snapshot_id=resolution.universe_snapshot_id,
                        ),
                    )
                    evaluated_count += 1
                    unknown_count += int(evaluation.condition_state == ConditionState.UNKNOWN)
                    event_count += persisted.created_event_count
                    if report_progress is not None:
                        await report_progress(
                            min(evaluated_count / total, 1.0),
                            "evaluating_alerts",
                            f"evaluated {evaluated_count}/{target_count} targets",
                        )
            completed = await self.states.finish_run(
                run.run_id,
                status=EvaluationRunStatus.COMPLETED,
                completed_at=_aware_utc(self.clock()),
                group_count=group_count,
                rule_count=rule_count,
                target_count=target_count,
                evaluated_count=evaluated_count,
                unknown_count=unknown_count,
                event_count=event_count,
                skipped_count=skipped_count,
            )
            return _result_from_run(completed)
        except AlertBatchCancelled:
            if run is not None:
                await self.states.finish_run(
                    run.run_id,
                    status=EvaluationRunStatus.CANCELLED,
                    completed_at=_aware_utc(self.clock()),
                    group_count=group_count,
                    rule_count=rule_count,
                    target_count=target_count,
                    evaluated_count=evaluated_count,
                    unknown_count=unknown_count,
                    event_count=event_count,
                    skipped_count=skipped_count,
                    error_code="CANCELLED",
                )
            raise
        except Exception as exc:
            if run is not None:
                await self.states.finish_run(
                    run.run_id,
                    status=EvaluationRunStatus.FAILED,
                    completed_at=_aware_utc(self.clock()),
                    group_count=group_count,
                    rule_count=rule_count,
                    target_count=target_count,
                    evaluated_count=evaluated_count,
                    unknown_count=unknown_count,
                    event_count=event_count,
                    skipped_count=skipped_count,
                    error_code=type(exc).__name__,
                )
            raise
        finally:
            await self.lock.release(lease)


class AlertBatchCancelled(RuntimeError):
    pass


def scope_key_for(rule: AlertRule, symbol: str | None) -> str:
    if symbol is not None:
        return f"{rule.market.value}:{symbol}"
    if isinstance(rule.scope, PaperAccountScope):
        return f"paper_account:{rule.scope.account_id}"
    if isinstance(rule.scope, SystemScope):
        return f"system:{rule.scope.component}"
    return f"{rule.scope.scope_type.value}:{rule.rule_id}"


def _compare(left, operator: AlertCompareOperator, right, upper) -> ConditionState:
    if left is None or right is None or (
        operator == AlertCompareOperator.BETWEEN and upper is None
    ):
        return ConditionState.UNKNOWN
    try:
        lhs, rhs = _comparable(left, right)
        if operator == AlertCompareOperator.GT:
            result = lhs > rhs
        elif operator == AlertCompareOperator.GTE:
            result = lhs >= rhs
        elif operator == AlertCompareOperator.LT:
            result = lhs < rhs
        elif operator == AlertCompareOperator.LTE:
            result = lhs <= rhs
        elif operator == AlertCompareOperator.EQ:
            result = lhs == rhs
        elif operator == AlertCompareOperator.NEQ:
            result = lhs != rhs
        else:
            low, high = _comparable(right, upper)
            candidate, low = _comparable(left, low)
            candidate, high = _comparable(candidate, high)
            result = low <= candidate <= high
    except (InvalidOperation, TypeError, ValueError):
        return ConditionState.UNKNOWN
    return ConditionState.TRUE if result else ConditionState.FALSE


def _comparable(left, right):
    if isinstance(left, bool) or isinstance(right, bool):
        if not isinstance(left, bool) or not isinstance(right, bool):
            raise TypeError("boolean comparison requires two booleans")
        return left, right
    try:
        return Decimal(str(left)), Decimal(str(right))
    except InvalidOperation:
        if isinstance(left, str) and isinstance(right, str):
            return left, right
        raise


def _missing_observation(timestamp: datetime) -> AlertObservation:
    return AlertObservation(
        quote_time=timestamp,
        ingested_at=timestamp,
        source="unavailable",
        quality_status=AlertQualityStatus.MISSING,
    )


def _first_present(document: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        value = document.get(name)
        if value is not None:
            return value
    return None


def _factor_refs(rule: AlertRule) -> set[tuple[str, int]]:
    references: set[tuple[str, int]] = set()
    pending = [rule.trigger.condition]
    while pending:
        condition = pending.pop()
        operands = ()
        if isinstance(condition, (AllAlertCondition, AnyAlertCondition)):
            pending.extend(condition.children)
        elif isinstance(condition, NotAlertCondition):
            pending.append(condition.child)
        elif isinstance(condition, (CompareAlertCondition, CrossAlertCondition)):
            operands = (condition.left, condition.right)
            if isinstance(condition, CompareAlertCondition) and condition.upper is not None:
                operands += (condition.upper,)
        for operand in operands:
            if isinstance(operand, FactorOperand):
                references.add((operand.factor_id, operand.version))
    return references


def _document_time(value: Any, market: AlertMarket) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        if market == AlertMarket.SYSTEM:
            parsed = parsed.replace(tzinfo=timezone.utc)
        else:
            parsed = parsed.replace(tzinfo=MarketCalendarService.timezone(market.value))
    return parsed.astimezone(timezone.utc)


def _market_date(market: AlertMarket, timestamp: datetime, calendar) -> date:
    if market == AlertMarket.SYSTEM:
        return timestamp.date()
    return timestamp.astimezone(calendar.timezone(market.value)).date()


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("evaluated_at must be timezone-aware")
    return value.astimezone(timezone.utc)


def _result_from_run(run: AlertEvaluationRun) -> AlertBatchExecutionResult:
    return AlertBatchExecutionResult(
        run_id=run.run_id,
        status=run.status,
        group_count=run.group_count,
        rule_count=run.rule_count,
        target_count=run.target_count,
        evaluated_count=run.evaluated_count,
        unknown_count=run.unknown_count,
        event_count=run.event_count,
        skipped_count=run.skipped_count,
    )
