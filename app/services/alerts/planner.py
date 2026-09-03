"""Deterministic grouping, session gating, and distributed batch locking."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Iterable, Protocol
from uuid import uuid4

from app.models.alert import (
    AlertMarket,
    AlertRule,
    AlertType,
    AllAlertCondition,
    AnyAlertCondition,
    CompareAlertCondition,
    CrossAlertCondition,
    FactorOperand,
    NotAlertCondition,
)
from app.services.calendars.market_calendar import MarketCalendarService


class AlertDataDependency(str, Enum):
    QUOTE = "quote"
    FACTOR = "factor"
    NEWS = "news"
    ACCOUNT = "account"
    SYSTEM = "system"


class AlertRunPolicy(str, Enum):
    INTRADAY = "intraday"
    AFTER_CLOSE = "after_close"
    ALWAYS = "always"


NEWS_TYPES = {
    AlertType.NEGATIVE_NEWS_DETECTED,
    AlertType.POSITIVE_NEWS_DETECTED,
    AlertType.NEWS_VOLUME_SPIKE,
    AlertType.SENTIMENT_CROSS_THRESHOLD,
    AlertType.HIGH_SEVERITY_EVENT,
}
ACCOUNT_TYPES = {
    AlertType.STOP_LOSS_NEAR,
    AlertType.STOP_LOSS_TRIGGERED,
    AlertType.TAKE_PROFIT_NEAR,
    AlertType.TAKE_PROFIT_TRIGGERED,
    AlertType.TRAILING_STOP_TRIGGERED,
    AlertType.POSITION_DRAWDOWN,
    AlertType.ACCOUNT_DRAWDOWN,
    AlertType.POSITION_WEIGHT_EXCEEDED,
    AlertType.INDUSTRY_WEIGHT_EXCEEDED,
    AlertType.CASH_BELOW,
}
SYSTEM_TYPES = {
    AlertType.DATASOURCE_DOWN,
    AlertType.DATASOURCE_LATENCY,
    AlertType.FACTOR_JOB_FAILED,
    AlertType.SCHEDULER_JOB_FAILED,
    AlertType.WORKER_HEARTBEAT_LOST,
    AlertType.NOTIFICATION_DELIVERY_FAILED,
}
FACTOR_TYPES = {
    AlertType.FACTOR_ABOVE,
    AlertType.FACTOR_BELOW,
    AlertType.FACTOR_BETWEEN,
    AlertType.FACTOR_CROSS_UP,
    AlertType.FACTOR_CROSS_DOWN,
    AlertType.FACTOR_RANK_ENTER,
    AlertType.FACTOR_RANK_EXIT,
    AlertType.COMPOSITE_SCORE_ABOVE,
    AlertType.COMPOSITE_SCORE_BELOW,
    AlertType.DATA_QUALITY_CHANGED,
}


@dataclass(frozen=True)
class AlertRuleGroup:
    market: AlertMarket
    frequency_seconds: int
    dependencies: tuple[AlertDataDependency, ...]
    rules: tuple[AlertRule, ...]

    @property
    def group_key(self) -> str:
        dependency_key = "+".join(item.value for item in self.dependencies)
        return f"{self.market.value}:{self.frequency_seconds}:{dependency_key}"


@dataclass(frozen=True)
class AlertBatchPlan:
    market: AlertMarket
    frequency_seconds: int
    time_bucket: int
    evaluated_at: datetime
    groups: tuple[AlertRuleGroup, ...]
    skipped_rule_ids: tuple[str, ...] = ()

    @property
    def batch_key(self) -> str:
        return (
            f"alert-eval:{self.market.value}:{self.frequency_seconds}:"
            f"{self.time_bucket}"
        )


def alert_time_bucket(evaluated_at: datetime, frequency_seconds: int) -> int:
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("evaluated_at must be timezone-aware")
    if frequency_seconds < 30 or frequency_seconds > 86_400:
        raise ValueError("frequency_seconds must be in 30..86400")
    return int(evaluated_at.astimezone(timezone.utc).timestamp()) // frequency_seconds


def rule_dependencies(rule: AlertRule) -> tuple[AlertDataDependency, ...]:
    dependencies: set[AlertDataDependency]
    if rule.alert_type in SYSTEM_TYPES:
        dependencies = {AlertDataDependency.SYSTEM}
    elif rule.alert_type in ACCOUNT_TYPES:
        dependencies = {AlertDataDependency.ACCOUNT}
    elif rule.alert_type in NEWS_TYPES:
        dependencies = {AlertDataDependency.NEWS}
    elif rule.alert_type in FACTOR_TYPES:
        dependencies = {AlertDataDependency.FACTOR}
    else:
        dependencies = {AlertDataDependency.QUOTE}

    for operand in _condition_operands(rule.trigger.condition):
        if isinstance(operand, FactorOperand):
            dependencies.add(AlertDataDependency.FACTOR)
    return tuple(sorted(dependencies, key=lambda item: item.value))


def rule_run_policy(rule: AlertRule) -> AlertRunPolicy:
    if rule.alert_type in SYSTEM_TYPES | NEWS_TYPES | ACCOUNT_TYPES:
        return AlertRunPolicy.ALWAYS
    if rule.alert_type in FACTOR_TYPES:
        return AlertRunPolicy.AFTER_CLOSE
    return AlertRunPolicy.INTRADAY


class BatchPlanner:
    def __init__(
        self,
        calendar: Any = MarketCalendarService,
        *,
        close_confirmation_delay: timedelta = timedelta(minutes=15),
    ):
        self.calendar = calendar
        self.close_confirmation_delay = close_confirmation_delay

    def plan(
        self,
        rules: Iterable[AlertRule],
        *,
        market: AlertMarket | str,
        frequency_seconds: int,
        evaluated_at: datetime,
        holidays: Iterable[str] = (),
    ) -> AlertBatchPlan:
        normalized_market = AlertMarket(market)
        timestamp = _aware_utc(evaluated_at)
        grouped: dict[tuple[AlertDataDependency, ...], list[AlertRule]] = {}
        skipped: list[str] = []
        for rule in sorted(rules, key=lambda item: item.rule_id):
            if (
                rule.market != normalized_market
                or rule.frequency_seconds != frequency_seconds
                or not self.is_rule_due(rule, timestamp, holidays=holidays)
            ):
                skipped.append(rule.rule_id)
                continue
            grouped.setdefault(rule_dependencies(rule), []).append(rule)
        groups = tuple(
            AlertRuleGroup(
                market=normalized_market,
                frequency_seconds=frequency_seconds,
                dependencies=dependencies,
                rules=tuple(items),
            )
            for dependencies, items in sorted(
                grouped.items(), key=lambda item: tuple(dep.value for dep in item[0])
            )
        )
        return AlertBatchPlan(
            market=normalized_market,
            frequency_seconds=frequency_seconds,
            time_bucket=alert_time_bucket(timestamp, frequency_seconds),
            evaluated_at=timestamp,
            groups=groups,
            skipped_rule_ids=tuple(skipped),
        )

    def is_rule_due(
        self,
        rule: AlertRule,
        evaluated_at: datetime,
        *,
        holidays: Iterable[str] = (),
    ) -> bool:
        timestamp = _aware_utc(evaluated_at)
        if not rule.enabled or (
            rule.expires_at is not None and timestamp >= rule.expires_at
        ):
            return False
        if rule.market == AlertMarket.SYSTEM:
            return self._schedule_allows(rule, timestamp, sessions=())

        sessions = tuple(
            self.calendar.sessions(
                rule.market.value,
                timestamp,
                holidays=tuple(holidays),
            )
        )
        policy = rule_run_policy(rule)
        if policy == AlertRunPolicy.INTRADAY:
            policy_allows = any(
                session.opens_at <= timestamp.astimezone(session.opens_at.tzinfo)
                <= session.closes_at
                for session in sessions
            )
        elif policy == AlertRunPolicy.AFTER_CLOSE:
            if not sessions:
                policy_allows = False
            else:
                close = sessions[-1].closes_at.astimezone(timezone.utc)
                starts = close + self.close_confirmation_delay
                policy_allows = starts <= timestamp < starts + timedelta(
                    seconds=rule.frequency_seconds
                )
        else:
            policy_allows = True
        return policy_allows and self._schedule_allows(rule, timestamp, sessions)

    @staticmethod
    def _schedule_allows(rule: AlertRule, timestamp: datetime, sessions) -> bool:
        schedule = rule.active_schedule
        if schedule.schedule_type == "all_day":
            return True
        if schedule.schedule_type == "custom":
            from zoneinfo import ZoneInfo

            local = timestamp.astimezone(ZoneInfo(schedule.timezone_name))
            return (
                local.isoweekday() in schedule.weekdays
                and schedule.start_time <= local.time().replace(tzinfo=None)
                <= schedule.end_time
            )
        if rule_run_policy(rule) == AlertRunPolicy.AFTER_CLOSE:
            return bool(sessions)
        if rule.market == AlertMarket.SYSTEM:
            return True
        return any(
            session.opens_at <= timestamp.astimezone(session.opens_at.tzinfo)
            <= session.closes_at
            for session in sessions
        )


@dataclass(frozen=True)
class AlertBatchLease:
    key: str
    owner_token: str
    ttl_seconds: int


class AlertBatchLock(Protocol):
    async def acquire(
        self,
        market: AlertMarket | str,
        frequency_seconds: int,
        time_bucket: int,
    ) -> AlertBatchLease | None: ...

    async def release(self, lease: AlertBatchLease) -> bool: ...


class RedisAlertBatchLock:
    """Redis SET-NX lease whose Lua release verifies the random owner token."""

    RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
""".strip()

    def __init__(self, redis, *, key_prefix: str = "locks:alert-eval", ttl_seconds: int = 120):
        if ttl_seconds < 10:
            raise ValueError("alert batch lock TTL must be at least 10 seconds")
        self.redis = redis
        self.key_prefix = key_prefix.rstrip(":")
        self.ttl_seconds = ttl_seconds

    async def acquire(
        self,
        market: AlertMarket | str,
        frequency_seconds: int,
        time_bucket: int,
    ) -> AlertBatchLease | None:
        normalized = AlertMarket(market)
        key = (
            f"{self.key_prefix}:{normalized.value}:{frequency_seconds}:"
            f"{time_bucket}"
        )
        token = uuid4().hex
        acquired = await self.redis.set(
            key,
            token,
            nx=True,
            ex=self.ttl_seconds,
        )
        if not acquired:
            return None
        return AlertBatchLease(key=key, owner_token=token, ttl_seconds=self.ttl_seconds)

    async def release(self, lease: AlertBatchLease) -> bool:
        result = await self.redis.eval(
            self.RELEASE_SCRIPT,
            1,
            lease.key,
            lease.owner_token,
        )
        return bool(result)


def _condition_operands(condition) -> Iterable[Any]:
    if isinstance(condition, (AllAlertCondition, AnyAlertCondition)):
        for child in condition.children:
            yield from _condition_operands(child)
    elif isinstance(condition, NotAlertCondition):
        yield from _condition_operands(condition.child)
    elif isinstance(condition, (CompareAlertCondition, CrossAlertCondition)):
        yield condition.left
        yield condition.right
        if isinstance(condition, CompareAlertCondition) and condition.upper is not None:
            yield condition.upper


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc)
