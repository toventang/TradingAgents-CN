from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import pytest

from app.models.alert import AlertRule, ConditionState
from app.services.alerts.evaluator import AlertObservation, PureAlertEvaluator
from app.services.alerts.evaluator import AlertBatchExecutionResult
from app.services.alerts.planner import (
    AlertDataDependency,
    BatchPlanner,
    RedisAlertBatchLock,
    alert_time_bucket,
    rule_dependencies,
)
from app.services.alerts.state_repository import EvaluationRunStatus
from app.services.domain_tasks import DomainTaskContext, TerminalTaskError
from app.models.domain_task import DomainTaskType
from app.workers.handlers.alert_evaluation import AlertEvaluationTaskHandler


CN_SESSION = datetime(2024, 1, 2, 1, 31, tzinfo=timezone.utc)


def make_rule(**updates) -> AlertRule:
    values = {
        "rule_id": str(UUID("00000000-0000-0000-0000-000000000141")),
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
        "created_at": CN_SESSION - timedelta(days=1),
        "updated_at": CN_SESSION - timedelta(days=1),
    }
    values.update(updates)
    return AlertRule.model_validate(values)


def observation(**updates) -> AlertObservation:
    values = {
        "current_value": Decimal("11"),
        "previous_value": Decimal("9"),
        "quote_time": CN_SESSION - timedelta(seconds=1),
        "ingested_at": CN_SESSION,
        "source": "fixture",
        "quality_status": "valid",
    }
    values.update(updates)
    return AlertObservation.model_validate(values)


def evaluate(rule, observed):
    return PureAlertEvaluator().evaluate(
        rule,
        observed,
        evaluated_at=CN_SESSION,
        market_date=CN_SESSION.date(),
    )


def test_pure_evaluator_handles_compare_boolean_tree_and_missing_values():
    tree = {
        "type": "all",
        "children": [
            make_rule().trigger.condition.model_dump(mode="json"),
            {
                "type": "not",
                "child": {
                    "type": "compare",
                    "left": {"kind": "previous_value"},
                    "operator": "gte",
                    "right": {"kind": "constant", "value": "10"},
                },
            },
        ],
    }
    rule = make_rule(trigger={"condition": tree})
    assert evaluate(rule, observation()).condition_state == ConditionState.TRUE
    assert (
        evaluate(rule, observation(previous_value=None)).condition_state
        == ConditionState.UNKNOWN
    )


def test_cross_uses_previous_and_current_values_without_lookahead():
    rule = make_rule(
        trigger={
            "condition": {
                "type": "cross_up",
                "left": {"kind": "current_value"},
                "right": {"kind": "constant", "value": "10"},
            }
        }
    )
    assert evaluate(rule, observation()).condition_state == ConditionState.TRUE
    assert (
        evaluate(rule, observation(previous_value="10.5")).condition_state
        == ConditionState.FALSE
    )
    assert (
        evaluate(rule, observation(previous_value=None)).condition_state
        == ConditionState.UNKNOWN
    )


@pytest.mark.parametrize("quality", ("stale", "missing", "error"))
def test_stale_missing_and_error_data_are_unknown(quality):
    result = evaluate(make_rule(), observation(quality_status=quality))
    assert result.condition_state == ConditionState.UNKNOWN


def test_future_observations_are_unknown_and_cannot_leak_into_evaluation():
    future = CN_SESSION + timedelta(seconds=1)
    result = evaluate(
        make_rule(),
        observation(quote_time=future, ingested_at=future),
    )
    assert result.condition_state == ConditionState.UNKNOWN


def test_factor_operands_add_a_factor_dependency_and_evaluate_snapshot_values():
    rule = make_rule(
        alert_type="factor_above",
        trigger={
            "condition": {
                "type": "compare",
                "left": {"kind": "factor", "factor_id": "roe", "version": 2},
                "operator": "gt",
                "right": {"kind": "constant", "value": "0.15"},
            }
        },
    )
    assert rule_dependencies(rule) == (AlertDataDependency.FACTOR,)
    result = evaluate(rule, observation(factors={"roe": "0.20"}))
    assert result.condition_state == ConditionState.TRUE


def test_planner_groups_by_market_frequency_dependencies_and_sessions():
    quote = make_rule()
    factor = make_rule(
        rule_id=str(UUID("00000000-0000-0000-0000-000000000142")),
        alert_type="factor_above",
        trigger={
            "condition": {
                "type": "compare",
                "left": {"kind": "factor", "factor_id": "roe"},
                "operator": "gt",
                "right": {"kind": "constant", "value": "0.1"},
            }
        },
    )
    planner = BatchPlanner()
    intraday = planner.plan(
        (quote, factor),
        market="CN",
        frequency_seconds=60,
        evaluated_at=CN_SESSION,
    )
    assert len(intraday.groups) == 1
    assert intraday.groups[0].dependencies == (AlertDataDependency.QUOTE,)
    assert intraday.skipped_rule_ids == (factor.rule_id,)

    close_confirmed = datetime(2024, 1, 2, 7, 15, tzinfo=timezone.utc)
    close_plan = planner.plan(
        (quote, factor),
        market="CN",
        frequency_seconds=60,
        evaluated_at=close_confirmed,
    )
    assert len(close_plan.groups) == 1
    assert close_plan.groups[0].rules == (factor,)


def test_weekends_run_all_day_news_but_not_price_rules():
    saturday = datetime(2024, 1, 6, 2, 0, tzinfo=timezone.utc)
    price = make_rule(active_schedule={"schedule_type": "all_day"})
    news = make_rule(
        rule_id=str(UUID("00000000-0000-0000-0000-000000000143")),
        alert_type="news_volume_spike",
        active_schedule={"schedule_type": "all_day"},
    )
    plan = BatchPlanner().plan(
        (price, news),
        market="CN",
        frequency_seconds=60,
        evaluated_at=saturday,
    )
    assert tuple(rule.rule_id for group in plan.groups for rule in group.rules) == (
        news.rule_id,
    )
    assert plan.groups[0].dependencies == (AlertDataDependency.NEWS,)


def test_holiday_and_cn_lunch_break_block_intraday_price_evaluation():
    rule = make_rule(active_schedule={"schedule_type": "all_day"})
    planner = BatchPlanner()
    assert not planner.is_rule_due(rule, CN_SESSION, holidays=("2024-01-02",))
    lunch_break = datetime(2024, 1, 2, 4, 0, tzinfo=timezone.utc)
    assert not planner.is_rule_due(rule, lunch_break)


def test_us_sessions_use_timezone_database_for_summer_and_winter():
    rule = make_rule(
        scope={"scope_type": "symbol", "symbol": "AAPL"},
        market="US",
    )
    planner = BatchPlanner()
    summer = datetime(2024, 7, 1, 13, 31, tzinfo=timezone.utc)
    winter = datetime(2024, 1, 2, 14, 31, tzinfo=timezone.utc)
    assert planner.is_rule_due(rule, summer)
    assert planner.is_rule_due(rule, winter)
    assert not planner.is_rule_due(rule, datetime(2024, 7, 1, 12, 31, tzinfo=timezone.utc))


class FakeRedis:
    def __init__(self):
        self.values = {}

    async def set(self, key, value, *, nx, ex):
        assert nx is True and ex == 30
        if key in self.values:
            return False
        self.values[key] = value
        return True

    async def eval(self, script, key_count, key, token):
        assert "redis.call('get'" in script and key_count == 1
        if self.values.get(key) != token:
            return 0
        del self.values[key]
        return 1


@pytest.mark.asyncio
async def test_redis_lock_has_ttl_and_owner_checked_release():
    redis = FakeRedis()
    lock = RedisAlertBatchLock(redis, ttl_seconds=30)
    bucket = alert_time_bucket(CN_SESSION, 60)
    first = await lock.acquire("CN", 60, bucket)
    assert first is not None
    assert await lock.acquire("CN", 60, bucket) is None
    forged = first.__class__(first.key, "not-the-owner", first.ttl_seconds)
    assert await lock.release(forged) is False
    assert await lock.release(first) is True
    assert await lock.acquire("CN", 60, bucket) is not None


@pytest.mark.asyncio
async def test_durable_handler_validates_payload_and_returns_evaluation_run_reference():
    class StubService:
        async def execute(self, **kwargs):
            assert kwargs["market"].value == "CN"
            return AlertBatchExecutionResult(
                run_id="00000000-0000-0000-0000-000000000141",
                status=EvaluationRunStatus.COMPLETED,
            )

    async def progress(value, stage, message):
        return None

    async def active():
        return False

    context = DomainTaskContext(
        task_id="00000000-0000-0000-0000-000000000241",
        user_id="system",
        task_type=DomainTaskType.ALERT_EVAL,
        attempt=1,
        max_attempts=3,
    )
    handler = AlertEvaluationTaskHandler(StubService())
    result = await handler(
        {
            "market": "CN",
            "frequency_seconds": 60,
            "evaluated_at": CN_SESSION.isoformat(),
        },
        context,
        progress,
        active,
    )
    assert result.collection == "alert_evaluation_runs"
    with pytest.raises(TerminalTaskError):
        await handler(
            {"market": "CN", "frequency_seconds": 1, "evaluated_at": "invalid"},
            context,
            progress,
            active,
        )
