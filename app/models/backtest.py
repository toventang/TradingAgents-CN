"""Point-in-time, execution, and performance contracts for backtests.

J30 freezes historical inputs and J31 defines transient order/fill contracts.
J33 defines deterministic metric outputs. Raw market prices remain unadjusted;
adjustment data is carried separately.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from app.models.market_data import DailyBar, NewsSocialInput, PointInTimeFact
from app.models.symbol import Currency, Market


def _stable_checksum(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _aware_utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


class BiasWarningCode(str, Enum):
    MISSING_POINT_IN_TIME = "missing_point_in_time"
    MISSING_UNIVERSE_HISTORY = "missing_universe_history"
    MISSING_PUBLICATION_TIME = "missing_publication_time"
    MISSING_INGESTION_TIME = "missing_ingestion_time"
    MISSING_MARKET_RULE = "missing_market_rule"
    MISSING_BENCHMARK = "missing_benchmark"
    MISSING_DAILY_BAR = "missing_daily_bar"
    UNSAFE_DATA_QUALITY = "unsafe_data_quality"
    NON_POINT_IN_TIME_OVERRIDE = "non_point_in_time_override"


class BiasWarning(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: BiasWarningCode
    message: str = Field(min_length=1, max_length=1000)
    trade_date: date | None = None
    market: Market | None = None
    symbol: str | None = None
    source: str | None = None
    blocks_automatic_learning: bool = True


class BacktestRequest(BaseModel):
    """Validated user intent before durable execution is created.

    Permission checks, historical coverage, concurrency, and minimum-order
    affordability require repositories and therefore remain service-level
    validations.  This contract rejects internally inconsistent requests.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy_version_id: str = Field(min_length=1, max_length=128)
    market: Market
    start_date: date
    end_date: date
    initial_cash: Decimal = Field(gt=0)
    benchmark: str = Field(min_length=1, max_length=128)
    execution_model_id: str = Field(min_length=1, max_length=128)
    base_currency: Currency | None = None
    parameter_overrides: dict[str, Any] = Field(default_factory=dict)
    universe_override: str | None = Field(default=None, min_length=1, max_length=128)
    seed: StrictInt = 0
    save_daily_positions: bool = True
    notes: str = Field(default="", max_length=4000)

    @field_validator(
        "strategy_version_id", "benchmark", "execution_model_id", "universe_override", "notes"
    )
    @classmethod
    def require_trimmed_request_text(cls, value: str | None) -> str | None:
        if value is not None and value != value.strip():
            raise ValueError("backtest request text fields must be trimmed")
        return value

    @model_validator(mode="after")
    def validate_request(self) -> "BacktestRequest":
        if self.end_date < self.start_date:
            raise ValueError("end_date cannot precede start_date")
        expected_currency = {
            Market.CN: Currency.CNY,
            Market.HK: Currency.HKD,
            Market.US: Currency.USD,
        }[self.market]
        if self.base_currency is not None and self.base_currency != expected_currency:
            raise ValueError("base_currency must match the single backtest market")
        object.__setattr__(self, "base_currency", expected_currency)
        try:
            json.dumps(
                self.parameter_overrides,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("parameter_overrides must contain finite JSON values") from exc
        return self


class UniverseMembership(BaseModel):
    """One historically versioned membership interval.

    ``effective_from``/``effective_to`` describe when the security belonged to
    the universe. ``known_at`` describes when that interval was available to
    the system.  The latter prevents corrected history from leaking backward.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    universe_id: str = Field(min_length=1, max_length=128)
    market: Market
    symbol: str = Field(min_length=1, max_length=64)
    effective_from: date
    effective_to: date | None = None
    known_at: datetime
    listing_date: date | None = None
    delisting_date: date | None = None
    is_st: bool = False
    source: str = Field(min_length=1, max_length=128)
    source_version: str = Field(min_length=1, max_length=128)

    @field_validator("known_at")
    @classmethod
    def normalize_known_at(cls, value: datetime) -> datetime:
        return _aware_utc(value, "known_at")

    @model_validator(mode="after")
    def validate_interval(self) -> "UniverseMembership":
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("effective_to cannot precede effective_from")
        if self.delisting_date is not None and self.listing_date is not None:
            if self.delisting_date < self.listing_date:
                raise ValueError("delisting_date cannot precede listing_date")
        return self

    def applies_on(self, trade_date: date, as_of: datetime) -> bool:
        cutoff = _aware_utc(as_of, "as_of")
        return (
            self.known_at <= cutoff
            and self.effective_from <= trade_date
            and (self.effective_to is None or trade_date <= self.effective_to)
            and (self.listing_date is None or self.listing_date <= trade_date)
            and (self.delisting_date is None or trade_date <= self.delisting_date)
        )


class CorporateActionType(str, Enum):
    CASH_DIVIDEND = "cash_dividend"
    SPLIT = "split"
    REVERSE_SPLIT = "reverse_split"
    BONUS_SHARE = "bonus_share"


class CorporateAction(BaseModel):
    """A dated company action expressed per pre-action share."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action_id: str = Field(min_length=1, max_length=128)
    market: Market
    symbol: str = Field(min_length=1, max_length=64)
    action_type: CorporateActionType
    ex_date: date
    announced_at: datetime
    ingested_at: datetime
    cash_per_share: Decimal = Field(default=Decimal("0"), ge=0)
    share_multiplier: Decimal = Field(default=Decimal("1"), gt=0)
    currency: Currency
    source: str = Field(min_length=1, max_length=128)
    source_version: str = Field(min_length=1, max_length=128)

    @field_validator("announced_at", "ingested_at")
    @classmethod
    def normalize_action_time(cls, value: datetime) -> datetime:
        return _aware_utc(value, "corporate-action timestamp")

    @model_validator(mode="after")
    def validate_action_values(self) -> "CorporateAction":
        expected_currency = {
            Market.CN: Currency.CNY,
            Market.HK: Currency.HKD,
            Market.US: Currency.USD,
        }[self.market]
        if self.currency != expected_currency:
            raise ValueError("corporate-action currency does not match market")
        if self.action_type == CorporateActionType.CASH_DIVIDEND:
            if self.cash_per_share <= 0 or self.share_multiplier != Decimal("1"):
                raise ValueError("cash dividend requires positive cash and multiplier 1")
        elif self.action_type in {
            CorporateActionType.SPLIT,
            CorporateActionType.BONUS_SHARE,
        }:
            if self.share_multiplier <= 1 or self.cash_per_share != 0:
                raise ValueError("split/bonus action requires multiplier > 1 and no cash")
        elif self.action_type == CorporateActionType.REVERSE_SPLIT:
            if self.share_multiplier >= 1 or self.cash_per_share != 0:
                raise ValueError("reverse split requires multiplier < 1 and no cash")
        return self

    @property
    def visible_at(self) -> datetime:
        return max(self.announced_at, self.ingested_at)


class BenchmarkBar(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    benchmark_id: str = Field(min_length=1, max_length=128)
    market: Market
    symbol: str = Field(min_length=1, max_length=64)
    trade_date: date
    close: Decimal = Field(gt=0)
    source: str = Field(min_length=1, max_length=128)
    source_version: str = Field(min_length=1, max_length=128)
    ingested_at: datetime

    @field_validator("ingested_at")
    @classmethod
    def normalize_benchmark_time(cls, value: datetime) -> datetime:
        return _aware_utc(value, "ingested_at")


class MarketRuleVersion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_version_id: str = Field(min_length=1, max_length=128)
    market: Market
    effective_from: date
    effective_to: date | None = None
    published_at: datetime
    rules: dict[str, Any]
    checksum: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("published_at")
    @classmethod
    def normalize_rule_time(cls, value: datetime) -> datetime:
        return _aware_utc(value, "published_at")

    @model_validator(mode="after")
    def validate_rule_version(self) -> "MarketRuleVersion":
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("effective_to cannot precede effective_from")
        expected = _stable_checksum(
            {
                "rule_version_id": self.rule_version_id,
                "market": self.market.value,
                "effective_from": self.effective_from.isoformat(),
                "effective_to": self.effective_to.isoformat() if self.effective_to else None,
                "published_at": self.published_at.isoformat(),
                "rules": self.rules,
            }
        )
        if self.checksum is not None and self.checksum != expected:
            raise ValueError("market-rule checksum does not match content")
        object.__setattr__(self, "checksum", expected)
        return self

    def applies_on(self, trade_date: date, as_of: datetime) -> bool:
        cutoff = _aware_utc(as_of, "as_of")
        return (
            self.published_at <= cutoff
            and self.effective_from <= trade_date
            and (self.effective_to is None or trade_date <= self.effective_to)
        )


class AdjustedReturnPoint(BaseModel):
    """Continuous-return observation; it is never an executable price."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    market: Market
    symbol: str
    trade_date: date
    raw_close: Decimal = Field(gt=0)
    adjusted_return: Decimal | None = None
    continuous_index: Decimal = Field(gt=0)
    applied_action_ids: tuple[str, ...] = ()


class DailyBacktestInput(BaseModel):
    """Immutable, reproducible input slice for one market close."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    market: Market
    trade_date: date
    signal_as_of: datetime
    universe_id: str
    universe: tuple[UniverseMembership, ...]
    bars: tuple[DailyBar, ...]
    financial_facts: tuple[PointInTimeFact, ...] = ()
    news: tuple[NewsSocialInput, ...] = ()
    social: tuple[NewsSocialInput, ...] = ()
    corporate_actions: tuple[CorporateAction, ...] = ()
    benchmark: BenchmarkBar | None = None
    market_rule: MarketRuleVersion | None = None
    source_versions: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    bias_warnings: tuple[BiasWarning, ...] = ()
    automatic_learning_allowed: bool = True
    input_checksum: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("signal_as_of")
    @classmethod
    def normalize_signal_time(cls, value: datetime) -> datetime:
        return _aware_utc(value, "signal_as_of")

    @model_validator(mode="after")
    def freeze_identity_and_learning_gate(self) -> "DailyBacktestInput":
        symbols = tuple(item.symbol for item in self.universe)
        if len(symbols) != len(set(symbols)):
            raise ValueError("daily universe contains duplicate symbols")
        if any(item.market != self.market for item in self.universe):
            raise ValueError("universe market does not match daily input")
        if any(bar.market != self.market or bar.trade_date != self.trade_date for bar in self.bars):
            raise ValueError("daily bars must match input market and trade_date")
        should_allow = not any(item.blocks_automatic_learning for item in self.bias_warnings)
        object.__setattr__(self, "automatic_learning_allowed", should_allow)
        payload = self.model_dump(mode="json", exclude={"input_checksum"})
        expected = _stable_checksum(payload)
        if self.input_checksum is not None and self.input_checksum != expected:
            raise ValueError("input_checksum does not match daily input")
        object.__setattr__(self, "input_checksum", expected)
        return self


class BacktestInputBundle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    market: Market
    start_date: date
    end_date: date
    days: tuple[DailyBacktestInput, ...]
    bias_warnings: tuple[BiasWarning, ...] = ()
    automatic_learning_allowed: bool = True
    bundle_checksum: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_bundle(self) -> "BacktestInputBundle":
        dates = tuple(item.trade_date for item in self.days)
        if dates != tuple(sorted(dates)) or len(dates) != len(set(dates)):
            raise ValueError("bundle days must be unique and sorted")
        if any(item.market != self.market for item in self.days):
            raise ValueError("bundle days must use one market")
        all_warnings = tuple(self.bias_warnings) + tuple(
            warning for item in self.days for warning in item.bias_warnings
        )
        object.__setattr__(
            self,
            "automatic_learning_allowed",
            not any(item.blocks_automatic_learning for item in all_warnings),
        )
        expected = _stable_checksum(
            self.model_dump(mode="json", exclude={"bundle_checksum"})
        )
        if self.bundle_checksum is not None and self.bundle_checksum != expected:
            raise ValueError("bundle_checksum does not match inputs")
        object.__setattr__(self, "bundle_checksum", expected)
        return self


def finite_decimal(value: float | Decimal) -> Decimal:
    result = Decimal(str(value))
    if not result.is_finite() or result <= 0:
        raise ValueError("price must be finite and positive")
    return result


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class BrokerOrderStatus(str, Enum):
    PENDING = "pending"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ExecutionPriceModel(str, Enum):
    NEXT_OPEN = "next_open"
    NEXT_VWAP_PROXY = "next_vwap_proxy"
    NEXT_CLOSE = "next_close"


class SlippageModel(str, Enum):
    FIXED_BPS = "fixed_bps"
    VOLUME_IMPACT = "volume_impact"


class SameBarConflictMode(str, Enum):
    CONSERVATIVE = "conservative"
    OPTIMISTIC = "optimistic"
    OPEN_PATH = "open_path"


class ExitReason(str, Enum):
    FIXED_STOP_LOSS = "fixed_stop_loss"
    FIXED_TAKE_PROFIT = "fixed_take_profit"
    ATR_STOP = "atr_stop"
    TRAILING_STOP = "trailing_stop"
    TIME_EXIT = "time_exit"
    SIGNAL_EXIT = "signal_exit"
    PORTFOLIO_DRAWDOWN = "portfolio_drawdown"


class SlippageConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model: SlippageModel = SlippageModel.FIXED_BPS
    fixed_bps: Decimal = Field(default=Decimal("0"), ge=0, le=1000)
    base_bps: Decimal = Field(default=Decimal("0"), ge=0, le=1000)
    impact_coefficient: Decimal = Field(default=Decimal("0"), ge=0, le=10000)

    @model_validator(mode="after")
    def validate_selected_slippage(self) -> "SlippageConfig":
        if self.model == SlippageModel.FIXED_BPS:
            if self.base_bps != 0 or self.impact_coefficient != 0:
                raise ValueError("fixed_bps slippage does not accept impact parameters")
        elif self.fixed_bps != 0:
            raise ValueError("volume_impact slippage does not accept fixed_bps")
        return self


class FeeSchedule(BaseModel):
    """Date-versioned rates; decimal fractions, not percentage points."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    commission_rate: Decimal = Field(default=Decimal("0"), ge=0, le=1)
    commission_per_share: Decimal = Field(default=Decimal("0"), ge=0)
    minimum_commission: Decimal = Field(default=Decimal("0"), ge=0)
    stamp_duty_rate: Decimal = Field(default=Decimal("0"), ge=0, le=1)
    transfer_fee_rate: Decimal = Field(default=Decimal("0"), ge=0, le=1)
    transaction_levy_rate: Decimal = Field(default=Decimal("0"), ge=0, le=1)
    trading_fee_rate: Decimal = Field(default=Decimal("0"), ge=0, le=1)
    settlement_fee_rate: Decimal = Field(default=Decimal("0"), ge=0, le=1)
    sec_fee_rate: Decimal = Field(default=Decimal("0"), ge=0, le=1)
    minimum_sec_fee: Decimal = Field(default=Decimal("0"), ge=0)
    other_rate: Decimal = Field(default=Decimal("0"), ge=0, le=1)


class SecurityRuleContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    market: Market
    symbol: str = Field(min_length=1, max_length=64)
    board: str | None = Field(default=None, min_length=1, max_length=64)
    is_st: bool = False
    lot_size: StrictInt | None = Field(default=None, ge=1)
    upper_limit_price: Decimal | None = Field(default=None, gt=0)
    lower_limit_price: Decimal | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_explicit_limits(self) -> "SecurityRuleContext":
        if (self.upper_limit_price is None) != (self.lower_limit_price is None):
            raise ValueError("upper and lower limit prices must be supplied together")
        if (
            self.upper_limit_price is not None
            and self.lower_limit_price is not None
            and self.upper_limit_price <= self.lower_limit_price
        ):
            raise ValueError("upper_limit_price must exceed lower_limit_price")
        return self


class ResolvedMarketRules(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_version_id: str = Field(min_length=1, max_length=128)
    market: Market
    symbol: str = Field(min_length=1, max_length=64)
    trade_date: date
    lot_size: StrictInt = Field(ge=1)
    integer_shares: bool = True
    t_plus_days: StrictInt = Field(default=0, ge=0, le=1)
    participation_rate: Decimal = Field(default=Decimal("0.10"), gt=0, le=Decimal("0.10"))
    price_tick: Decimal = Field(default=Decimal("0.01"), gt=0)
    price_limit_pct: Decimal | None = Field(default=None, gt=0, lt=1)
    strict_locked_limit: bool = True
    fee_schedule: FeeSchedule = Field(default_factory=FeeSchedule)


class BrokerOrder(BaseModel):
    """Transient immutable order state; persistence is introduced in J32."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    order_id: str = Field(min_length=1, max_length=128)
    market: Market
    symbol: str = Field(min_length=1, max_length=64)
    side: OrderSide
    requested_quantity: StrictInt = Field(gt=0)
    filled_quantity: StrictInt = Field(default=0, ge=0)
    created_trade_date: date
    expires_on: date
    execution_model: ExecutionPriceModel = ExecutionPriceModel.NEXT_OPEN
    slippage: SlippageConfig = Field(default_factory=SlippageConfig)
    status: BrokerOrderStatus = BrokerOrderStatus.PENDING
    execution_attempts: StrictInt = Field(default=0, ge=0, le=3)
    maximum_execution_days: StrictInt = Field(default=3, ge=1, le=3)

    @model_validator(mode="after")
    def validate_order_state(self) -> "BrokerOrder":
        if self.expires_on < self.created_trade_date:
            raise ValueError("expires_on cannot precede created_trade_date")
        if self.filled_quantity > self.requested_quantity:
            raise ValueError("filled_quantity cannot exceed requested_quantity")
        if self.execution_attempts > self.maximum_execution_days:
            raise ValueError("execution_attempts cannot exceed maximum_execution_days")
        remaining = self.requested_quantity - self.filled_quantity
        if self.status == BrokerOrderStatus.FILLED and remaining != 0:
            raise ValueError("filled order cannot have remaining quantity")
        if remaining == 0 and self.status != BrokerOrderStatus.FILLED:
            raise ValueError("zero-remaining order must have filled status")
        if (
            self.status == BrokerOrderStatus.PENDING
            and self.filled_quantity != 0
        ):
            raise ValueError("pending order cannot contain an earlier fill")
        if self.status == BrokerOrderStatus.PARTIALLY_FILLED and not (
            0 < self.filled_quantity < self.requested_quantity
        ):
            raise ValueError("partially filled order requires partial cumulative fill")
        return self

    @property
    def remaining_quantity(self) -> int:
        return self.requested_quantity - self.filled_quantity


class PositionLot(BaseModel):
    """Settlement-aware lot used only to calculate sell availability."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    lot_id: str = Field(min_length=1, max_length=128)
    market: Market
    symbol: str = Field(min_length=1, max_length=64)
    quantity: StrictInt = Field(gt=0)
    remaining_quantity: StrictInt = Field(gt=0)
    acquired_trade_date: date
    available_trade_date: date
    unit_cost: Decimal = Field(gt=0)

    @model_validator(mode="after")
    def validate_lot(self) -> "PositionLot":
        if self.remaining_quantity > self.quantity:
            raise ValueError("remaining lot quantity cannot exceed original quantity")
        if self.available_trade_date < self.acquired_trade_date:
            raise ValueError("available_trade_date cannot precede acquisition")
        return self


class FeeBreakdown(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    commission: Decimal = Field(default=Decimal("0"), ge=0)
    stamp_duty: Decimal = Field(default=Decimal("0"), ge=0)
    transfer_fee: Decimal = Field(default=Decimal("0"), ge=0)
    transaction_levy: Decimal = Field(default=Decimal("0"), ge=0)
    trading_fee: Decimal = Field(default=Decimal("0"), ge=0)
    settlement_fee: Decimal = Field(default=Decimal("0"), ge=0)
    sec_fee: Decimal = Field(default=Decimal("0"), ge=0)
    other: Decimal = Field(default=Decimal("0"), ge=0)
    total: Decimal = Field(default=Decimal("0"), ge=0)

    @model_validator(mode="after")
    def calculate_total(self) -> "FeeBreakdown":
        expected = sum(
            (
                self.commission,
                self.stamp_duty,
                self.transfer_fee,
                self.transaction_levy,
                self.trading_fee,
                self.settlement_fee,
                self.sec_fee,
                self.other,
            ),
            Decimal("0"),
        )
        if self.total not in (Decimal("0"), expected):
            raise ValueError("fee total does not match components")
        object.__setattr__(self, "total", expected)
        return self


class BrokerFill(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    order_id: str
    market: Market
    symbol: str
    side: OrderSide
    trade_date: date
    quantity: StrictInt = Field(gt=0)
    raw_price: Decimal = Field(gt=0)
    slippage_per_share: Decimal
    fill_price: Decimal = Field(gt=0)
    notional: Decimal = Field(gt=0)
    fees: FeeBreakdown
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def reconcile_fill(self) -> "BrokerFill":
        if self.notional != self.fill_price * self.quantity:
            raise ValueError("fill notional must equal fill price times quantity")
        if self.slippage_per_share != self.fill_price - self.raw_price:
            raise ValueError("slippage_per_share does not reconcile")
        return self


class BrokerExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    order_id: str
    trade_date: date
    status: BrokerOrderStatus
    requested_quantity: StrictInt = Field(gt=0)
    cumulative_filled_quantity: StrictInt = Field(ge=0)
    remaining_quantity: StrictInt = Field(ge=0)
    execution_attempts: StrictInt = Field(ge=0, le=3)
    fill: BrokerFill | None = None
    reason: str | None = None
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_execution_result(self) -> "BrokerExecutionResult":
        if (
            self.cumulative_filled_quantity + self.remaining_quantity
            != self.requested_quantity
        ):
            raise ValueError("execution quantities do not reconcile to requested quantity")
        if self.status == BrokerOrderStatus.FILLED and self.remaining_quantity != 0:
            raise ValueError("filled result cannot have remaining quantity")
        if self.fill is None and self.status == BrokerOrderStatus.FILLED:
            raise ValueError("fill status requires a fill record")
        if self.status == BrokerOrderStatus.PARTIALLY_FILLED and not (
            self.cumulative_filled_quantity > 0 and self.remaining_quantity > 0
        ):
            raise ValueError("partially-filled result requires filled and remaining quantity")
        return self


class ExitRuleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fixed_stop_loss_pct: Decimal | None = Field(default=None, gt=0, lt=1)
    fixed_take_profit_pct: Decimal | None = Field(default=None, gt=0)
    atr_stop_multiple: Decimal | None = Field(default=None, gt=0)
    trailing_stop_pct: Decimal | None = Field(default=None, gt=0, lt=1)
    trailing_atr_multiple: Decimal | None = Field(default=None, gt=0)
    maximum_holding_days: StrictInt | None = Field(default=None, ge=1)
    conflict_mode: SameBarConflictMode = SameBarConflictMode.CONSERVATIVE


class ExitDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    triggered: bool
    reason: ExitReason | None = None
    trigger_price: Decimal | None = Field(default=None, gt=0)
    same_bar_conflict: bool = False
    assumption_warning: str | None = None
    research_only_assumption: bool = False

    @model_validator(mode="after")
    def validate_exit_decision(self) -> "ExitDecision":
        if self.triggered != (self.reason is not None):
            raise ValueError("triggered exit must include exactly one reason")
        if not self.triggered and self.trigger_price is not None:
            raise ValueError("non-triggered exit cannot include a trigger price")
        return self


class SignalConflictDecision(BaseModel):
    """Exit-before-entry and cooldown decision for one symbol and signal day."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    exit_selected: bool
    buy_allowed: bool
    reason: str

    @model_validator(mode="after")
    def prevent_exit_and_buy(self) -> "SignalConflictDecision":
        if self.exit_selected and self.buy_allowed:
            raise ValueError("exit and buy cannot both be selected for one symbol/day")
        return self


class BacktestPerformanceConfig(BaseModel):
    """Published calculation conventions for one performance report."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    annualization_periods: StrictInt = Field(default=252, ge=1, le=366)
    annual_risk_free_rate: Decimal = Field(default=Decimal("0"), gt=-1)
    minimum_return_observations: StrictInt = Field(default=30, ge=1)
    minimum_trade_count: StrictInt = Field(default=10, ge=1)


class BacktestClosedLot(BaseModel):
    """One fee-inclusive FIFO match between a buy lot and a sell fill."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    closed_lot_id: str
    symbol: str
    buy_trade_id: str
    sell_trade_id: str
    buy_order_id: str
    sell_order_id: str
    quantity: StrictInt = Field(gt=0)
    entry_trade_date: date
    exit_trade_date: date
    entry_cost: Decimal = Field(gt=0)
    exit_proceeds: Decimal
    pnl: Decimal
    return_rate: Decimal
    holding_sessions: StrictInt = Field(ge=0)
    exit_reason: str

    @model_validator(mode="after")
    def reconcile_closed_lot(self) -> "BacktestClosedLot":
        if self.exit_trade_date < self.entry_trade_date:
            raise ValueError("closed lot exit cannot precede entry")
        if self.exit_proceeds - self.entry_cost != self.pnl:
            raise ValueError("closed lot PnL does not reconcile")
        if abs(self.pnl / self.entry_cost - self.return_rate) > Decimal("1e-24"):
            raise ValueError("closed lot return does not reconcile")
        return self


class BacktestPeriodReturn(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    period: str = Field(min_length=4, max_length=7)
    start_date: date
    end_date: date
    return_rate: Decimal


class BacktestPerformanceReport(BaseModel):
    """Complete deterministic metric set; undefined ratios are represented by None."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    initial_equity: Decimal = Field(gt=0)
    final_equity: Decimal = Field(gt=0)
    return_observations: StrictInt = Field(ge=1)
    total_return: Decimal
    cagr: Decimal
    mean_daily_return: Decimal
    annualized_volatility: Decimal = Field(ge=0)
    annual_risk_free_rate: Decimal
    daily_risk_free_rate: Decimal
    sharpe_ratio: Decimal | None = None
    annualized_downside_deviation: Decimal = Field(ge=0)
    sortino_ratio: Decimal | None = None
    max_drawdown: Decimal = Field(le=0)
    max_drawdown_start_date: date | None = None
    max_drawdown_end_date: date | None = None
    max_drawdown_recovery_date: date | None = None
    calmar_ratio: Decimal | None = None

    benchmark_observations: StrictInt = Field(ge=0)
    benchmark_total_return: Decimal | None = None
    relative_total_return: Decimal | None = None
    beta: Decimal | None = None
    annualized_alpha: Decimal | None = None
    tracking_error: Decimal | None = Field(default=None, ge=0)
    information_ratio: Decimal | None = None

    closed_lot_count: StrictInt = Field(ge=0)
    winning_lot_count: StrictInt = Field(ge=0)
    losing_lot_count: StrictInt = Field(ge=0)
    breakeven_lot_count: StrictInt = Field(ge=0)
    win_rate: Decimal | None = None
    loss_rate: Decimal | None = None
    profit_loss_ratio: Decimal | None = None
    profit_factor: Decimal | None = None
    gross_winning_pnl: Decimal = Field(ge=0)
    gross_losing_pnl: Decimal = Field(le=0)
    net_closed_pnl: Decimal
    average_closed_lot_pnl: Decimal | None = None
    median_closed_lot_pnl: Decimal | None = None
    average_closed_lot_return: Decimal | None = None
    median_closed_lot_return: Decimal | None = None
    maximum_winning_pnl: Decimal | None = None
    maximum_losing_pnl: Decimal | None = None
    average_holding_sessions: Decimal | None = None
    median_holding_sessions: Decimal | None = None

    total_turnover: Decimal = Field(ge=0)
    average_daily_turnover: Decimal = Field(ge=0)
    total_fees: Decimal = Field(ge=0)
    total_slippage_cost: Decimal
    fee_to_gross_profit_ratio: Decimal | None = None
    average_gross_exposure: Decimal = Field(ge=0)
    maximum_gross_exposure: Decimal = Field(ge=0)
    average_net_exposure: Decimal = Field(ge=0)
    maximum_net_exposure: Decimal = Field(ge=0)
    average_cash_ratio: Decimal = Field(ge=0)
    minimum_cash_ratio: Decimal = Field(ge=0)
    maximum_cash_ratio: Decimal = Field(ge=0)
    final_cash_ratio: Decimal = Field(ge=0)
    maximum_stock_concentration: Decimal = Field(ge=0, le=1)
    maximum_industry_concentration: Decimal | None = Field(default=None, ge=0, le=1)

    trade_count: StrictInt = Field(ge=0)
    rejected_order_count: StrictInt = Field(ge=0)
    partially_filled_order_count: StrictInt = Field(ge=0)
    monthly_returns: tuple[BacktestPeriodReturn, ...]
    yearly_returns: tuple[BacktestPeriodReturn, ...]
    exit_reason_distribution: dict[str, StrictInt]
    closed_lots: tuple[BacktestClosedLot, ...]
    warnings: tuple[str, ...]
    formulas: dict[str, str]

    @model_validator(mode="after")
    def reconcile_performance_report(self) -> "BacktestPerformanceReport":
        if (
            self.winning_lot_count
            + self.losing_lot_count
            + self.breakeven_lot_count
            != self.closed_lot_count
            or len(self.closed_lots) != self.closed_lot_count
        ):
            raise ValueError("closed lot counts do not reconcile")
        if self.gross_winning_pnl + self.gross_losing_pnl != self.net_closed_pnl:
            raise ValueError("closed lot PnL aggregates do not reconcile")
        if abs(
            self.final_equity / self.initial_equity - 1 - self.total_return
        ) > Decimal("1e-24"):
            raise ValueError("total return does not reconcile")
        if self.max_drawdown == 0 and any(
            value is not None
            for value in (
                self.max_drawdown_start_date,
                self.max_drawdown_end_date,
                self.max_drawdown_recovery_date,
            )
        ):
            raise ValueError("zero drawdown cannot have drawdown dates")
        if self.max_drawdown < 0 and self.max_drawdown_end_date is None:
            raise ValueError("non-zero drawdown requires a trough date")
        return self
