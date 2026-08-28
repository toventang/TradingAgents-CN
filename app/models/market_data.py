"""Normalized, point-in-time-safe market-data contracts.

The models in this module are read contracts.  They deliberately do not
mirror any single provider or Mongo collection.  Percentages exposed by these
contracts are decimal fractions (``0.05`` means five percent).
"""

from __future__ import annotations

import math
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.symbol import Currency, Market


class DataQualityStatus(str, Enum):
    VALID = "valid"
    PARTIAL = "partial"
    STALE = "stale"
    SUSPENDED = "suspended"
    INVALID = "invalid"
    UNAVAILABLE = "unavailable"


# Shorter name for new consumers; retain DataQualityStatus for compatibility.
QualityStatus = DataQualityStatus


class DataQualityInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: DataQualityStatus = DataQualityStatus.VALID
    reason_code: str = "OK"
    reason_codes: list[str] = Field(default_factory=list)
    message: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)
    as_of: datetime
    source_version: str = Field(min_length=1)

    @field_validator("as_of")
    @classmethod
    def require_aware_as_of(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        return value

    @model_validator(mode="after")
    def keep_reason_code_in_list(self) -> "DataQualityInfo":
        if self.reason_code != "OK" and self.reason_code not in self.reason_codes:
            self.reason_codes.insert(0, self.reason_code)
        return self

    @property
    def usable_for_automated_buy(self) -> bool:
        return self.status in {DataQualityStatus.VALID, DataQualityStatus.PARTIAL}


class DailyBar(BaseModel):
    """One normalized daily OHLCV observation.

    ``pct_chg`` is a decimal fraction.  Legacy provider values such as ``5``
    must be converted by the adapter before constructing this model.
    """

    model_config = ConfigDict(extra="forbid")

    market: Market
    symbol: str = Field(min_length=1)
    trade_date: date
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    pre_close: float | None = None
    volume: float | None = None
    amount: float | None = None
    adj_factor: float | None = None
    pct_chg: float | None = None
    suspended: bool = False
    source: str = Field(default="unknown", min_length=1)
    source_version: str = Field(default="unknown", min_length=1)


class PointInTimeFact(BaseModel):
    """A financial fact whose visibility starts at its publication time."""

    model_config = ConfigDict(extra="forbid")

    fact_id: str = Field(min_length=1)
    market: Market
    symbol: str = Field(min_length=1)
    report_period: str = Field(min_length=1)
    publish_at: datetime
    ingested_at: datetime | None = None
    fact_type: str = "financial"
    data: dict[str, Any] = Field(default_factory=dict)
    source: str = "unknown"
    source_version: str = "unknown"

    @field_validator("publish_at", "ingested_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("point-in-time timestamps must be timezone-aware")
        return value

    def is_visible_at(self, as_of: datetime) -> bool:
        _require_aware(as_of, "as_of")
        return self.publish_at <= as_of


class NewsSocialInput(BaseModel):
    """News/social input with both event and ingestion visibility boundaries."""

    model_config = ConfigDict(extra="forbid")

    news_id: str = Field(min_length=1)
    market: Market
    symbol: str = Field(min_length=1)
    published_at: datetime
    ingested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    title: str = ""
    content_summary: str | None = None
    sentiment_score: float | None = None
    source: str = "unknown"
    source_version: str = "unknown"

    @field_validator("published_at", "ingested_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        _require_aware(value, "timestamp")
        return value

    def is_visible_at(self, as_of: datetime) -> bool:
        _require_aware(as_of, "as_of")
        return self.published_at <= as_of and self.ingested_at <= as_of


class BenchmarkIdentity(BaseModel):
    """Stable benchmark identity, independent from equity-symbol validation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    benchmark_id: str = Field(min_length=1)
    market: Market
    symbol: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    currency: Currency

    @model_validator(mode="after")
    def currency_matches_market(self) -> "BenchmarkIdentity":
        expected = {Market.CN: Currency.CNY, Market.HK: Currency.HKD, Market.US: Currency.USD}
        if self.currency != expected[self.market]:
            raise ValueError("benchmark currency does not match market")
        return self


class BenchmarkSeries(BaseModel):
    model_config = ConfigDict(extra="forbid")

    benchmark: BenchmarkIdentity
    trade_date: date
    close: float
    pct_chg: float | None = None


class MarketDataBatch(BaseModel):
    """Versioned result envelope shared by normalized read operations."""

    model_config = ConfigDict(extra="forbid")

    items: list[Any] = Field(default_factory=list)
    as_of: datetime
    source_version: str = Field(min_length=1)
    quality: DataQualityInfo

    @field_validator("as_of")
    @classmethod
    def require_aware_as_of(cls, value: datetime) -> datetime:
        _require_aware(value, "as_of")
        return value


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def finite_or_none(value: Any) -> float | None:
    """Return a finite float or ``None`` without raising on provider junk."""
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None
