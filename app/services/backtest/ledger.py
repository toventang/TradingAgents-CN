"""Immutable daily backtest ledger records and reconciliation boundary."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from app.models.backtest import BrokerOrderStatus, FeeBreakdown, OrderSide
from app.models.symbol import Market


MONEY_TOLERANCE = Decimal("0.01")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("ledger timestamp must be timezone-aware")
    return value.astimezone(timezone.utc)


def stable_checksum(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class BacktestRunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    CANCELLED = "cancelled"
    FAILED = "failed"


class BacktestRunRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1, max_length=128)
    task_id: str = Field(min_length=1, max_length=128)
    user_id: str = Field(min_length=1, max_length=128)
    strategy_version_id: str = Field(min_length=1, max_length=128)
    market: Market
    request: dict[str, Any]
    input_versions: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    bias_warnings: tuple[dict[str, Any], ...] = ()
    status: BacktestRunStatus = BacktestRunStatus.QUEUED
    summary: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] | None = None
    last_completed_trade_date: date | None = None
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    updated_at: datetime = Field(default_factory=utc_now)

    _timestamps = field_validator(
        "created_at", "started_at", "finished_at", "updated_at"
    )(_aware_utc)

    @model_validator(mode="after")
    def validate_run_state(self) -> "BacktestRunRecord":
        if self.status == BacktestRunStatus.RUNNING and self.started_at is None:
            raise ValueError("running backtest requires started_at")
        if self.status in {
            BacktestRunStatus.SUCCEEDED,
            BacktestRunStatus.CANCELLED,
            BacktestRunStatus.FAILED,
        } and self.finished_at is None:
            raise ValueError("terminal backtest requires finished_at")
        return self


class BacktestOrderRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    order_id: str
    run_id: str
    user_id: str
    signal_id: str
    market: Market
    symbol: str
    side: OrderSide
    requested_qty: StrictInt = Field(gt=0)
    filled_qty: StrictInt = Field(ge=0)
    remaining_qty: StrictInt = Field(ge=0)
    order_type: str
    created_trade_date: date
    expire_date: date
    status: BrokerOrderStatus
    execution_attempts: StrictInt = Field(ge=0, le=3)
    reject_reason: str | None = None

    @model_validator(mode="after")
    def reconcile_quantities(self) -> "BacktestOrderRecord":
        if self.filled_qty + self.remaining_qty != self.requested_qty:
            raise ValueError("order quantities do not reconcile")
        return self


class BacktestTradeRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    trade_id: str
    order_id: str
    run_id: str
    user_id: str
    market: Market
    symbol: str
    side: OrderSide
    quantity: StrictInt = Field(gt=0)
    raw_price: Decimal = Field(gt=0)
    slippage: Decimal
    fill_price: Decimal = Field(gt=0)
    notional: Decimal = Field(gt=0)
    fees: FeeBreakdown
    trade_date: date
    realized_pnl: Decimal | None = None

    @model_validator(mode="after")
    def reconcile_trade(self) -> "BacktestTradeRecord":
        if self.fill_price * self.quantity != self.notional:
            raise ValueError("trade notional does not reconcile")
        return self


class BacktestPositionDailyRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    user_id: str
    trade_date: date
    market: Market
    symbol: str
    quantity: StrictInt = Field(gt=0)
    available_qty: StrictInt = Field(ge=0)
    avg_cost: Decimal = Field(gt=0)
    close: Decimal = Field(gt=0)
    market_value: Decimal = Field(ge=0)
    unrealized_pnl: Decimal
    weight: Decimal = Field(ge=0, le=1)
    holding_days: StrictInt = Field(ge=1)

    @model_validator(mode="after")
    def reconcile_position(self) -> "BacktestPositionDailyRecord":
        if self.available_qty > self.quantity:
            raise ValueError("available quantity cannot exceed position quantity")
        if abs(self.market_value - self.close * self.quantity) > MONEY_TOLERANCE:
            raise ValueError("position market value does not reconcile")
        return self


class BacktestEquityDailyRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    user_id: str
    trade_date: date
    cash: Decimal = Field(ge=0)
    market_value: Decimal = Field(ge=0)
    equity: Decimal = Field(gt=0)
    daily_return: Decimal | None = None
    cumulative_return: Decimal
    drawdown: Decimal = Field(le=0)
    benchmark_equity: Decimal | None = Field(default=None, gt=0)
    turnover: Decimal = Field(default=Decimal("0"), ge=0)
    gross_exposure: Decimal = Field(default=Decimal("0"), ge=0)
    net_exposure: Decimal = Field(default=Decimal("0"), ge=0)

    @model_validator(mode="after")
    def reconcile_equity(self) -> "BacktestEquityDailyRecord":
        if abs(self.cash + self.market_value - self.equity) > MONEY_TOLERANCE:
            raise ValueError("cash + market value must equal equity")
        return self


class BacktestEventRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    run_id: str
    user_id: str
    trade_date: date
    sequence: StrictInt = Field(ge=1)
    step: StrictInt = Field(ge=1, le=12)
    event_type: str = Field(min_length=1, max_length=128)
    symbol: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class BacktestCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    user_id: str
    trade_date: date
    portfolio_state: dict[str, Any]
    pending_orders: tuple[dict[str, Any], ...]
    signal_ids: dict[str, str]
    cooldown_until: dict[str, date]
    last_prices: dict[str, Decimal]
    previous_equity: Decimal | None = None
    peak_equity: Decimal
    benchmark_base_close: Decimal | None = None
    completed_days: StrictInt = Field(ge=1)
    order_count: StrictInt = Field(ge=0)
    trade_count: StrictInt = Field(ge=0)
    checkpoint_checksum: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )

    @model_validator(mode="after")
    def validate_checkpoint_checksum(self) -> "BacktestCheckpoint":
        expected = stable_checksum(
            self.model_dump(mode="json", exclude={"checkpoint_checksum"})
        )
        if self.checkpoint_checksum is not None and self.checkpoint_checksum != expected:
            raise ValueError("checkpoint checksum does not match state")
        object.__setattr__(self, "checkpoint_checksum", expected)
        return self


class DailyLedgerBatch(BaseModel):
    """One atomic logical day; checkpoint publication is its commit marker."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    user_id: str
    trade_date: date
    orders: tuple[BacktestOrderRecord, ...] = ()
    trades: tuple[BacktestTradeRecord, ...] = ()
    positions: tuple[BacktestPositionDailyRecord, ...] = ()
    equity: BacktestEquityDailyRecord
    events: tuple[BacktestEventRecord, ...]
    checkpoint: BacktestCheckpoint

    @model_validator(mode="after")
    def reconcile_day(self) -> "DailyLedgerBatch":
        resources = (
            *self.orders,
            *self.trades,
            *self.positions,
            self.equity,
            *self.events,
            self.checkpoint,
        )
        if any(
            item.run_id != self.run_id or item.user_id != self.user_id
            for item in resources
        ):
            raise ValueError("daily ledger resources must share run and owner")
        dated = (*self.trades, *self.positions, self.equity, *self.events, self.checkpoint)
        if any(item.trade_date != self.trade_date for item in dated):
            raise ValueError("daily ledger resources must share trade_date")
        if len({item.trade_id for item in self.trades}) != len(self.trades):
            raise ValueError("daily trades contain duplicate IDs")
        if len({item.symbol for item in self.positions}) != len(self.positions):
            raise ValueError("daily positions contain duplicate symbols")
        if len({item.event_id for item in self.events}) != len(self.events):
            raise ValueError("daily events contain duplicate IDs")
        sequences = tuple(item.sequence for item in self.events)
        if sequences != tuple(range(1, len(sequences) + 1)):
            raise ValueError("daily event sequence must be contiguous and ordered")
        steps = tuple(item.step for item in self.events)
        if steps != tuple(sorted(steps)) or set(steps) != set(range(1, 13)):
            raise ValueError("daily ledger must record every step in 1..12 order")
        position_value = sum(
            (item.market_value for item in self.positions), Decimal("0")
        )
        if abs(position_value - self.equity.market_value) > MONEY_TOLERANCE:
            raise ValueError("position values do not match equity market value")
        return self
