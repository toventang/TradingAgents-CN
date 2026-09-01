"""Point-in-time input contracts for deterministic daily backtests.

This module intentionally contains no order, fill, ledger, or performance
logic.  J30 freezes the historical inputs consumed by those later layers.
Raw market prices remain unadjusted; adjustment data is carried separately.
"""

from __future__ import annotations

import hashlib
import json
import math
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
