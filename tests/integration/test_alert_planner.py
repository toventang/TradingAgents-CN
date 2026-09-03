from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.models.alert import AlertRule, ConditionState, stable_checksum
from app.repositories.alert_repository import AlertRepository
from app.repositories.domain_task_repository import DomainTaskRepository
from app.services.alerts.evaluator import (
    AlertEvaluationBatchService,
    AlertObservation,
    AlertSnapshotRequest,
    MongoAlertSnapshotLoader,
    PureAlertEvaluator,
    ScopeResolution,
)
from app.services.alerts.planner import RedisAlertBatchLock
from app.services.alerts.planner import AlertDataDependency
from app.services.alerts.state_machine import AlertEvaluation
from app.services.alerts.state_repository import (
    AlertEventEvidence,
    AlertStateRepository,
    EvaluationRunStatus,
)
from app.services.scheduler_service import (
    ALERT_EVALUATION_BATCH_JOB_ID,
    AlertEvaluationBatchEnqueuer,
    register_alert_evaluation_batch_job,
)
from tests.unit.alerts.test_rule_validator import AlertFakeCollection


EVALUATED_AT = datetime(2024, 1, 2, 1, 31, tzinfo=timezone.utc)


def make_rule(rule_id: int = 141) -> AlertRule:
    return AlertRule.model_validate(
        {
            "rule_id": str(UUID(f"00000000-0000-0000-0000-{rule_id:012d}")),
            "user_id": "owner",
            "name": "价格突破",
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
            "frequency_seconds": 60,
            "active_schedule": {"schedule_type": "market_hours"},
            "cooldown_seconds": 0,
            "created_at": EVALUATED_AT - timedelta(days=1),
            "updated_at": EVALUATED_AT - timedelta(days=1),
        }
    )


class HybridCollection(AlertFakeCollection):
    def find(self, query, projection=None):
        return super().find(query)


class FakeDatabase:
    def __init__(self):
        self.collections = {}

    def __getitem__(self, name):
        return self.collections.setdefault(name, HybridCollection(name))


class FakeRedis:
    def __init__(self):
        self.values = {}

    async def set(self, key, value, *, nx, ex):
        if key in self.values:
            return False
        self.values[key] = value
        return True

    async def eval(self, script, count, key, token):
        if self.values.get(key) != token:
            return 0
        del self.values[key]
        return 1


class FixedScopeResolver:
    calls = 0

    async def resolve(self, rule, *, evaluated_at):
        self.calls += 1
        symbols = (rule.scope.symbol,)
        return ScopeResolution(
            targets=symbols,
            universe_snapshot_id=None,
            symbols_checksum=stable_checksum(symbols),
        )


class SlowSnapshotLoader:
    def __init__(self):
        self.calls = 0
        self.requests: list[AlertSnapshotRequest] = []

    async def load(self, request):
        self.calls += 1
        self.requests.append(request)
        await asyncio.sleep(0.05)
        return {
            target: AlertObservation(
                current_value=Decimal("11"),
                previous_value=Decimal("9"),
                quote_time=request.evaluated_at - timedelta(seconds=1),
                ingested_at=request.evaluated_at,
                source="fixture",
                quality_status="valid",
            )
            for target in request.targets
        }


@pytest.mark.asyncio
async def test_two_concurrent_batch_evaluators_create_one_event_and_one_run():
    database = FakeDatabase()
    alerts = AlertRepository(database)
    await alerts.create_rule(make_rule())
    states = AlertStateRepository(database, alerts=alerts)
    snapshots = SlowSnapshotLoader()
    service = AlertEvaluationBatchService(
        states=states,
        lock=RedisAlertBatchLock(FakeRedis(), ttl_seconds=30),
        scopes=FixedScopeResolver(),
        snapshots=snapshots,
    )

    first, second = await asyncio.gather(
        service.execute(
            task_id="task-one",
            market="CN",
            frequency_seconds=60,
            evaluated_at=EVALUATED_AT,
        ),
        service.execute(
            task_id="task-two",
            market="CN",
            frequency_seconds=60,
            evaluated_at=EVALUATED_AT,
        ),
    )

    assert {first.status, second.status} == {
        EvaluationRunStatus.COMPLETED,
        EvaluationRunStatus.SKIPPED_LOCKED,
    }
    assert first.run_id == second.run_id
    assert snapshots.calls == 1
    assert len(database[alerts.EVENTS_COLLECTION].documents) == 1
    assert len(database[alerts.STATES_COLLECTION].documents) == 1
    assert len(database[states.RUNS_COLLECTION].documents) == 1
    completed = first if first.status == EvaluationRunStatus.COMPLETED else second
    assert completed.group_count == 1
    assert completed.rule_count == completed.target_count == 1
    assert completed.evaluated_count == completed.event_count == 1


@pytest.mark.asyncio
async def test_atomic_state_cas_and_event_fingerprint_are_idempotent_without_batch_lock():
    database = FakeDatabase()
    alerts = AlertRepository(database)
    rule = await alerts.create_rule(make_rule())
    states = AlertStateRepository(database, alerts=alerts)
    evaluation = AlertEvaluation(
        condition_state=ConditionState.TRUE,
        value=Decimal("11"),
        evaluated_at=EVALUATED_AT,
        market_date=EVALUATED_AT.date(),
    )
    evidence = AlertEventEvidence(
        quote_time=EVALUATED_AT - timedelta(seconds=1),
        ingested_at=EVALUATED_AT,
        source="fixture",
        quality_status="valid",
        actual_symbols=("600000",),
    )

    results = await asyncio.gather(
        *(
            states.apply(
                rule,
                scope_key="CN:600000",
                symbol="600000",
                evaluation=evaluation,
                evidence=evidence,
            )
            for _ in range(2)
        )
    )
    assert sum(item.created_event_count for item in results) == 1
    assert len(database[alerts.EVENTS_COLLECTION].documents) == 1
    assert len(database[alerts.STATES_COLLECTION].documents) == 1


@pytest.mark.asyncio
async def test_scheduler_creates_one_durable_task_per_market_frequency_bucket():
    database = FakeDatabase()
    alerts = AlertRepository(database)
    await alerts.create_rule(make_rule(151))
    await alerts.create_rule(make_rule(152))
    tasks = DomainTaskRepository(database)
    await tasks.ensure_indexes()
    enqueuer = AlertEvaluationBatchEnqueuer(database, tasks)

    first = await enqueuer.enqueue_due_batches(evaluated_at=EVALUATED_AT)
    replay = await enqueuer.enqueue_due_batches(
        evaluated_at=EVALUATED_AT + timedelta(seconds=20)
    )
    assert len(first) == len(replay) == 1
    assert first[0].task_id == replay[0].task_id
    assert len(database[tasks.TASKS_COLLECTION].documents) == 1
    assert first[0].payload["market"] == "CN"
    assert first[0].payload["frequency_seconds"] == 60
    assert first[0].payload["evaluated_at"] == replay[0].payload["evaluated_at"]


@pytest.mark.asyncio
async def test_daily_factor_batch_is_created_at_close_confirmation_not_utc_midnight():
    database = FakeDatabase()
    alerts = AlertRepository(database)
    base = make_rule(153)
    factor_rule = AlertRule.model_validate(
        {
            **base.model_dump(mode="python"),
            "alert_type": "factor_above",
            "frequency_seconds": 86_400,
            "trigger": {
                "condition": {
                    "type": "compare",
                    "left": {"kind": "factor", "factor_id": "roe"},
                    "operator": "gt",
                    "right": {"kind": "constant", "value": "0.10"},
                }
            },
        }
    )
    await alerts.create_rule(factor_rule)
    tasks = DomainTaskRepository(database)
    await tasks.ensure_indexes()
    enqueuer = AlertEvaluationBatchEnqueuer(database, tasks)

    midnight = datetime(2024, 1, 2, 0, 0, tzinfo=timezone.utc)
    assert await enqueuer.enqueue_due_batches(evaluated_at=midnight) == []
    confirmed_close = datetime(2024, 1, 2, 7, 15, tzinfo=timezone.utc)
    created = await enqueuer.enqueue_due_batches(evaluated_at=confirmed_close)
    assert len(created) == 1
    assert created[0].payload["evaluated_at"] == confirmed_close.isoformat()


@pytest.mark.asyncio
async def test_factor_loader_reuses_published_snapshots_and_excludes_future_data():
    database = FakeDatabase()
    rule = make_rule(161).model_copy(
        update={
            "alert_type": "factor_cross_up",
            "trigger": {
                "condition": {
                    "type": "cross_up",
                    "left": {"kind": "factor", "factor_id": "roe"},
                    "right": {"kind": "constant", "value": "0.10"},
                }
            },
        }
    )
    rule = AlertRule.model_validate(
        {field: getattr(rule, field) for field in AlertRule.model_fields}
    )
    snapshots = database["factor_snapshots"].documents
    snapshots.extend(
        [
            {
                "snapshot_id": "future",
                "job_id": "job-future",
                "user_id": "owner",
                "market": "CN",
                "status": "ready",
                "trade_date": "2024-01-02",
                "published_at": (EVALUATED_AT + timedelta(seconds=1)).isoformat(),
            },
            {
                "snapshot_id": "current",
                "job_id": "job-current",
                "user_id": "owner",
                "market": "CN",
                "status": "ready",
                "trade_date": "2024-01-02",
                "published_at": (EVALUATED_AT - timedelta(seconds=1)).isoformat(),
            },
            {
                "snapshot_id": "previous",
                "job_id": "job-previous",
                "user_id": "owner",
                "market": "CN",
                "status": "ready",
                "trade_date": "2024-01-01",
                "published_at": (EVALUATED_AT - timedelta(days=1)).isoformat(),
            },
        ]
    )
    database["factor_jobs"].documents.extend(
        [
            {
                "job_id": job_id,
                "user_id": "owner",
                "request": {"factors": [{"factor_id": "roe", "version": 1}]},
            }
            for job_id in ("job-future", "job-current", "job-previous")
        ]
    )
    database["factor_values"].documents.extend(
        [
            {
                "snapshot_id": "future",
                "user_id": "owner",
                "symbol": "600000",
                "values": {"roe": 99},
            },
            {
                "snapshot_id": "current",
                "user_id": "owner",
                "symbol": "600000",
                "values": {"roe": 0.20},
            },
            {
                "snapshot_id": "previous",
                "user_id": "owner",
                "symbol": "600000",
                "values": {"roe": 0.05},
            },
        ]
    )
    request = AlertSnapshotRequest(
        market="CN",
        evaluated_at=EVALUATED_AT,
        rules=(rule,),
        targets=(("owner", "600000"),),
        dependencies=(AlertDataDependency.FACTOR,),
    )
    loaded = await MongoAlertSnapshotLoader(database).load(request)
    observed = loaded[("owner", "600000")]
    assert observed.factors == {"roe@1": Decimal("0.2")}
    assert observed.previous_factors == {"roe@1": Decimal("0.05")}
    assert observed.source.startswith("factor_snapshots:")
    evaluation = PureAlertEvaluator().evaluate(
        rule,
        observed,
        evaluated_at=EVALUATED_AT,
        market_date=EVALUATED_AT.date(),
    )
    assert evaluation.condition_state == ConditionState.TRUE


def test_scheduler_registration_is_one_batch_job_not_per_rule():
    class FakeScheduler:
        def __init__(self):
            self.calls = []

        def add_job(self, function, trigger, **kwargs):
            self.calls.append((function, trigger, kwargs))

        def get_job(self, job_id):
            return SimpleNamespace(id=job_id)

    scheduler = FakeScheduler()
    enqueuer = SimpleNamespace(enqueue_due_batches=lambda: None)
    job = register_alert_evaluation_batch_job(
        scheduler,
        enqueuer,
        interval_seconds=30,
    )
    assert job.id == ALERT_EVALUATION_BATCH_JOB_ID
    assert len(scheduler.calls) == 1
    _, trigger, options = scheduler.calls[0]
    assert trigger == "interval"
    assert options["id"] == ALERT_EVALUATION_BATCH_JOB_ID
    assert options["max_instances"] == 1
