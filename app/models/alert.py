"""Closed, versioned contracts for realtime alert rules and evaluation state.

Rules are declarative data.  No model in this module accepts source code,
expressions, import paths, or executable callbacks.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time, timezone
from decimal import Decimal
from enum import Enum
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator


SYSTEM_USER_ID = "system"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_alert_id() -> str:
    return str(uuid4())


def stable_checksum(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _aware_utc(value: datetime | None, field_name: str) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


class AlertMarket(str, Enum):
    CN = "CN"
    HK = "HK"
    US = "US"
    SYSTEM = "system"


class AlertScopeType(str, Enum):
    SYMBOL = "symbol"
    WATCHLIST = "watchlist"
    STRATEGY_UNIVERSE = "strategy_universe"
    PAPER_POSITION = "paper_position"
    PAPER_ACCOUNT = "paper_account"
    SYSTEM = "system"


class AlertType(str, Enum):
    PRICE_ABOVE = "price_above"
    PRICE_BELOW = "price_below"
    PCT_CHANGE_ABOVE = "pct_change_above"
    PCT_CHANGE_BELOW = "pct_change_below"
    GAP_UP = "gap_up"
    GAP_DOWN = "gap_down"
    NEW_HIGH = "new_high"
    NEW_LOW = "new_low"
    LIMIT_UP = "limit_up"
    LIMIT_DOWN = "limit_down"
    VOLUME_RATIO_ABOVE = "volume_ratio_above"
    AMOUNT_ABOVE = "amount_above"
    TURNOVER_ABOVE = "turnover_above"
    LIQUIDITY_BELOW = "liquidity_below"
    NO_QUOTE = "no_quote"
    STALE_QUOTE = "stale_quote"
    FACTOR_ABOVE = "factor_above"
    FACTOR_BELOW = "factor_below"
    FACTOR_BETWEEN = "factor_between"
    FACTOR_CROSS_UP = "factor_cross_up"
    FACTOR_CROSS_DOWN = "factor_cross_down"
    FACTOR_RANK_ENTER = "factor_rank_enter"
    FACTOR_RANK_EXIT = "factor_rank_exit"
    COMPOSITE_SCORE_ABOVE = "composite_score_above"
    COMPOSITE_SCORE_BELOW = "composite_score_below"
    DATA_QUALITY_CHANGED = "data_quality_changed"
    NEGATIVE_NEWS_DETECTED = "negative_news_detected"
    POSITIVE_NEWS_DETECTED = "positive_news_detected"
    NEWS_VOLUME_SPIKE = "news_volume_spike"
    SENTIMENT_CROSS_THRESHOLD = "sentiment_cross_threshold"
    HIGH_SEVERITY_EVENT = "high_severity_event"
    STOP_LOSS_NEAR = "stop_loss_near"
    STOP_LOSS_TRIGGERED = "stop_loss_triggered"
    TAKE_PROFIT_NEAR = "take_profit_near"
    TAKE_PROFIT_TRIGGERED = "take_profit_triggered"
    TRAILING_STOP_TRIGGERED = "trailing_stop_triggered"
    POSITION_DRAWDOWN = "position_drawdown"
    ACCOUNT_DRAWDOWN = "account_drawdown"
    POSITION_WEIGHT_EXCEEDED = "position_weight_exceeded"
    INDUSTRY_WEIGHT_EXCEEDED = "industry_weight_exceeded"
    CASH_BELOW = "cash_below"
    DATASOURCE_DOWN = "datasource_down"
    DATASOURCE_LATENCY = "datasource_latency"
    FACTOR_JOB_FAILED = "factor_job_failed"
    SCHEDULER_JOB_FAILED = "scheduler_job_failed"
    WORKER_HEARTBEAT_LOST = "worker_heartbeat_lost"
    NOTIFICATION_DELIVERY_FAILED = "notification_delivery_failed"


class AlertEvaluationMode(str, Enum):
    EDGE = "edge"
    LEVEL = "level"
    ONCE = "once"


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertChannel(str, Enum):
    IN_APP = "in_app"
    WEBSOCKET = "websocket"


class AlertAction(str, Enum):
    NOTIFY_ONLY = "notify_only"
    PAPER_TRADE = "paper_trade"


class AlertRuleOrigin(str, Enum):
    USER = "user"
    AUTOMATION = "automation"
    SYSTEM = "system"


class ConditionState(str, Enum):
    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"


class AlertEventKind(str, Enum):
    TRIGGERED = "triggered"
    RECOVERED = "recovered"
    RULE_HEALTH = "rule_health"


class AlertQualityStatus(str, Enum):
    VALID = "valid"
    PARTIAL = "partial"
    STALE = "stale"
    MISSING = "missing"
    ERROR = "error"


class NewsEventCategory(str, Enum):
    EARNINGS = "earnings"
    REGULATORY = "regulatory"
    LITIGATION = "litigation"
    SUSPENSION = "suspension"
    DIVIDEND = "dividend"
    BUYBACK = "buyback"
    REDUCTION = "reduction"
    MAJOR_CONTRACT = "major_contract"


class SymbolScope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scope_type: Literal[AlertScopeType.SYMBOL] = AlertScopeType.SYMBOL
    symbol: str = Field(min_length=1, max_length=32)


class WatchlistScope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scope_type: Literal[AlertScopeType.WATCHLIST] = AlertScopeType.WATCHLIST
    watchlist_id: str | None = Field(default=None, min_length=1, max_length=128)
    symbols: tuple[str, ...] = Field(default=(), max_length=5000)

    @model_validator(mode="after")
    def require_one_frozen_or_referenced_scope(self) -> "WatchlistScope":
        if (self.watchlist_id is None) == (not self.symbols):
            raise ValueError("watchlist scope requires exactly one of watchlist_id or symbols")
        if len(self.symbols) != len(set(self.symbols)):
            raise ValueError("watchlist symbols must be unique")
        return self


class StrategyUniverseScope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scope_type: Literal[AlertScopeType.STRATEGY_UNIVERSE] = AlertScopeType.STRATEGY_UNIVERSE
    strategy_version_id: str = Field(min_length=1, max_length=128)


class PaperPositionScope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scope_type: Literal[AlertScopeType.PAPER_POSITION] = AlertScopeType.PAPER_POSITION
    account_id: str = Field(min_length=1, max_length=128)


class PaperAccountScope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scope_type: Literal[AlertScopeType.PAPER_ACCOUNT] = AlertScopeType.PAPER_ACCOUNT
    account_id: str = Field(min_length=1, max_length=128)


class SystemScope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scope_type: Literal[AlertScopeType.SYSTEM] = AlertScopeType.SYSTEM
    component: str = Field(min_length=1, max_length=128)


AlertScope = Annotated[
    SymbolScope
    | WatchlistScope
    | StrategyUniverseScope
    | PaperPositionScope
    | PaperAccountScope
    | SystemScope,
    Field(discriminator="scope_type"),
]


class FactorOperand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["factor"] = "factor"
    factor_id: str = Field(pattern=r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
    version: StrictInt = Field(default=1, ge=1)
    lag: StrictInt = Field(default=0, ge=0, le=252)


class CurrentValueOperand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["current_value"] = "current_value"


class PreviousValueOperand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["previous_value"] = "previous_value"


class ConstantOperand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["constant"] = "constant"
    value: Decimal

    @field_validator("value")
    @classmethod
    def finite_constant(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("constant value must be finite")
        return value


class ChangeRateOperand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["change_rate"] = "change_rate"
    window_seconds: StrictInt = Field(ge=30, le=604800)


AlertOperand = Annotated[
    FactorOperand
    | CurrentValueOperand
    | PreviousValueOperand
    | ConstantOperand
    | ChangeRateOperand,
    Field(discriminator="kind"),
]


class AlertCompareOperator(str, Enum):
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    EQ = "eq"
    NEQ = "neq"
    BETWEEN = "between"


class AllAlertCondition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["all"] = "all"
    children: tuple["AlertCondition", ...] = Field(min_length=1)


class AnyAlertCondition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["any"] = "any"
    children: tuple["AlertCondition", ...] = Field(min_length=1)


class NotAlertCondition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["not"] = "not"
    child: "AlertCondition"


class CompareAlertCondition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["compare"] = "compare"
    left: AlertOperand
    operator: AlertCompareOperator
    right: AlertOperand
    upper: AlertOperand | None = None

    @model_validator(mode="after")
    def validate_between(self) -> "CompareAlertCondition":
        if self.operator == AlertCompareOperator.BETWEEN and self.upper is None:
            raise ValueError("between comparison requires upper operand")
        if self.operator != AlertCompareOperator.BETWEEN and self.upper is not None:
            raise ValueError("upper operand is only allowed for between")
        if (
            self.operator == AlertCompareOperator.BETWEEN
            and isinstance(self.right, ConstantOperand)
            and isinstance(self.upper, ConstantOperand)
            and self.right.value > self.upper.value
        ):
            raise ValueError("between lower bound cannot exceed upper bound")
        return self


class CrossAlertCondition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["cross_up", "cross_down"]
    left: AlertOperand
    right: AlertOperand


AlertCondition = Annotated[
    AllAlertCondition
    | AnyAlertCondition
    | NotAlertCondition
    | CompareAlertCondition
    | CrossAlertCondition,
    Field(discriminator="type"),
]


class AlertTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    condition: AlertCondition
    for_seconds: StrictInt | None = Field(default=None, ge=1, le=604800)
    for_evaluations: StrictInt | None = Field(default=None, ge=1, le=10000)

    @model_validator(mode="after")
    def one_duration_constraint(self) -> "AlertTrigger":
        if self.for_seconds is not None and self.for_evaluations is not None:
            raise ValueError("trigger accepts only one duration constraint")
        return self


class MarketHoursSchedule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schedule_type: Literal["market_hours"] = "market_hours"


class AllDaySchedule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schedule_type: Literal["all_day"] = "all_day"


class CustomSchedule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schedule_type: Literal["custom"] = "custom"
    timezone_name: str = Field(min_length=1, max_length=128)
    weekdays: tuple[StrictInt, ...] = Field(min_length=1, max_length=7)
    start_time: time
    end_time: time

    @field_validator("timezone_name")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("unknown IANA timezone") from exc
        return value

    @field_validator("weekdays")
    @classmethod
    def valid_weekdays(cls, values: tuple[int, ...]) -> tuple[int, ...]:
        if any(value < 1 or value > 7 for value in values):
            raise ValueError("weekdays use ISO values 1 through 7")
        if len(values) != len(set(values)):
            raise ValueError("weekdays must be unique")
        return tuple(sorted(values))

    @model_validator(mode="after")
    def ordered_intraday_window(self) -> "CustomSchedule":
        if self.end_time <= self.start_time:
            raise ValueError("custom schedule cannot cross midnight")
        return self


ActiveSchedule = Annotated[
    MarketHoursSchedule | AllDaySchedule | CustomSchedule,
    Field(discriminator="schedule_type"),
]


class AlertRuleStateSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evaluated_scope_count: StrictInt = Field(default=0, ge=0)
    triggered_scope_count: StrictInt = Field(default=0, ge=0)
    last_evaluated_at: datetime | None = None

    @field_validator("last_evaluated_at")
    @classmethod
    def normalize_last_evaluated(cls, value: datetime | None) -> datetime | None:
        return _aware_utc(value, "last_evaluated_at")


class AlertRule(BaseModel):
    # A rule instance is one immutable version. Updates create a validated copy
    # with an incremented optimistic-lock version and are persisted as a new
    # revision by the repository.
    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str = Field(default_factory=new_alert_id)
    user_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    enabled: bool = True
    alert_type: AlertType
    scope: AlertScope
    market: AlertMarket
    trigger: AlertTrigger
    evaluation_mode: AlertEvaluationMode = AlertEvaluationMode.EDGE
    frequency_seconds: StrictInt = Field(ge=30, le=86400)
    active_schedule: ActiveSchedule
    cooldown_seconds: StrictInt = Field(default=300, ge=0, le=604800)
    recovery_enabled: bool = True
    severity: AlertSeverity = AlertSeverity.WARNING
    channels: tuple[AlertChannel, ...] = Field(
        default=(AlertChannel.IN_APP, AlertChannel.WEBSOCKET), min_length=1
    )
    action: AlertAction = AlertAction.NOTIFY_ONLY
    origin: AlertRuleOrigin = AlertRuleOrigin.USER
    automation_id: str | None = Field(default=None, min_length=1, max_length=128)
    paper_account_id: str | None = Field(default=None, min_length=1, max_length=128)
    lookback_window: StrictInt | None = Field(default=None, ge=5, le=250)
    event_categories: tuple[NewsEventCategory, ...] = ()
    max_events_per_day: StrictInt = Field(default=100, ge=1, le=1000)
    expires_at: datetime | None = None
    state: AlertRuleStateSummary = Field(default_factory=AlertRuleStateSummary)
    version: StrictInt = Field(default=1, ge=1)
    condition_version: StrictInt = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("rule_id")
    @classmethod
    def valid_rule_uuid(cls, value: str) -> str:
        try:
            return str(UUID(value))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("rule_id must be a UUID string") from exc

    @field_validator("user_id", "name", "description")
    @classmethod
    def trimmed_text(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("alert text fields must be trimmed")
        return value

    @field_validator("channels")
    @classmethod
    def unique_channels(
        cls, values: tuple[AlertChannel, ...]
    ) -> tuple[AlertChannel, ...]:
        if len(values) != len(set(values)):
            raise ValueError("alert channels must be unique")
        return values

    @field_validator("expires_at", "created_at", "updated_at")
    @classmethod
    def normalize_rule_times(
        cls, value: datetime | None, info
    ) -> datetime | None:
        return _aware_utc(value, info.field_name)

    @model_validator(mode="after")
    def validate_rule_invariants(self) -> "AlertRule":
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        if self.expires_at is not None and self.expires_at <= self.created_at:
            raise ValueError("expires_at must be after created_at")
        if self.condition_version > self.version:
            raise ValueError("condition_version cannot exceed rule version")
        return self


AlertStateValue = Decimal | str | bool | None


class AlertRuleState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    user_id: str = Field(min_length=1, max_length=128)
    scope_key: str = Field(min_length=1, max_length=256)
    symbol: str | None = Field(default=None, min_length=1, max_length=32)
    last_value: AlertStateValue = None
    last_condition_state: ConditionState = ConditionState.UNKNOWN
    last_determined_state: ConditionState | None = None
    true_since: datetime | None = None
    false_since: datetime | None = None
    unknown_since: datetime | None = None
    consecutive_true: StrictInt = Field(default=0, ge=0)
    consecutive_false: StrictInt = Field(default=0, ge=0)
    consecutive_unknown: StrictInt = Field(default=0, ge=0)
    last_evaluated_at: datetime | None = None
    last_triggered_at: datetime | None = None
    cooldown_until: datetime | None = None
    events_today: StrictInt = Field(default=0, ge=0, le=1000)
    market_date: date | None = None
    last_event_fingerprint: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    active_event_open: bool = False
    edge_pending: bool = False
    health_unknown_reported: bool = False
    rule_version: StrictInt = Field(ge=1)
    condition_version: StrictInt = Field(ge=1)
    state_revision: StrictInt = Field(default=0, ge=0)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("rule_id")
    @classmethod
    def valid_state_rule_uuid(cls, value: str) -> str:
        try:
            return str(UUID(value))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("rule_id must be a UUID string") from exc

    @field_validator(
        "true_since",
        "false_since",
        "unknown_since",
        "last_evaluated_at",
        "last_triggered_at",
        "cooldown_until",
        "updated_at",
    )
    @classmethod
    def normalize_state_times(cls, value: datetime | None, info) -> datetime | None:
        return _aware_utc(value, info.field_name)

    @model_validator(mode="after")
    def validate_state_counters(self) -> "AlertRuleState":
        active_counts = sum(
            value > 0
            for value in (
                self.consecutive_true,
                self.consecutive_false,
                self.consecutive_unknown,
            )
        )
        if active_counts > 1:
            raise ValueError("only the current condition counter may be positive")
        expected_count = {
            ConditionState.TRUE: self.consecutive_true,
            ConditionState.FALSE: self.consecutive_false,
            ConditionState.UNKNOWN: self.consecutive_unknown,
        }[self.last_condition_state]
        if self.last_evaluated_at is not None and expected_count < 1:
            raise ValueError("evaluated state requires a positive current counter")
        if self.last_determined_state == ConditionState.UNKNOWN:
            raise ValueError("last_determined_state cannot be unknown")
        return self


class AlertEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(default_factory=new_alert_id)
    rule_id: str
    rule_version: StrictInt = Field(ge=1)
    condition_version: StrictInt = Field(ge=1)
    user_id: str = Field(min_length=1, max_length=128)
    scope_key: str = Field(min_length=1, max_length=256)
    symbol: str | None = Field(default=None, min_length=1, max_length=32)
    kind: AlertEventKind
    severity: AlertSeverity
    direction: str = Field(min_length=1, max_length=64)
    condition_state: ConditionState
    current_value: AlertStateValue = None
    previous_value: AlertStateValue = None
    quote_time: datetime
    ingested_at: datetime
    evaluated_at: datetime
    source: str = Field(min_length=1, max_length=128)
    latency_seconds: Decimal = Field(ge=0)
    quality_status: AlertQualityStatus
    stale: bool = False
    actual_symbol_count: StrictInt = Field(default=0, ge=0)
    actual_symbols_checksum: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    universe_snapshot_id: str | None = Field(default=None, min_length=1, max_length=128)
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    acknowledged_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("event_id", "rule_id")
    @classmethod
    def valid_event_uuid(cls, value: str) -> str:
        try:
            return str(UUID(value))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("event and rule identifiers must be UUID strings") from exc

    @field_validator(
        "quote_time",
        "ingested_at",
        "evaluated_at",
        "acknowledged_at",
        "created_at",
    )
    @classmethod
    def normalize_event_times(cls, value: datetime | None, info) -> datetime | None:
        return _aware_utc(value, info.field_name)

    @model_validator(mode="after")
    def validate_event_evidence(self) -> "AlertEvent":
        if self.ingested_at < self.quote_time:
            raise ValueError("ingested_at cannot precede quote_time")
        if self.evaluated_at < self.ingested_at:
            raise ValueError("evaluated_at cannot precede ingested_at")
        measured = Decimal(str((self.evaluated_at - self.quote_time).total_seconds()))
        if abs(measured - self.latency_seconds) > Decimal("0.001"):
            raise ValueError("latency_seconds must match evaluated_at minus quote_time")
        if self.stale != (self.quality_status == AlertQualityStatus.STALE):
            raise ValueError("stale flag and quality_status must agree")
        if self.actual_symbol_count > 0 and self.actual_symbols_checksum is None:
            raise ValueError("dynamic symbol evidence requires a checksum")
        return self


class AlertRuleRevision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str
    user_id: str
    version: StrictInt = Field(ge=1)
    condition_version: StrictInt = Field(ge=1)
    rule: AlertRule
    checksum: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def freeze_revision(self) -> "AlertRuleRevision":
        if (
            self.rule.rule_id != self.rule_id
            or self.rule.user_id != self.user_id
            or self.rule.version != self.version
            or self.rule.condition_version != self.condition_version
        ):
            raise ValueError("revision identity must match its rule snapshot")
        expected = stable_checksum(self.rule.model_dump(mode="json"))
        if self.checksum is not None and self.checksum != expected:
            raise ValueError("revision checksum does not match rule snapshot")
        object.__setattr__(self, "checksum", expected)
        return self
