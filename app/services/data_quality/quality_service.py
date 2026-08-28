"""Deterministic quality classification for normalized market data."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Iterable

from app.models.market_data import DailyBar, DataQualityInfo, DataQualityStatus


class DataQualityService:
    _REQUIRED_PRICES = ("open", "high", "low", "close")

    @staticmethod
    def validate_daily_bar(
        bar: DailyBar,
        *,
        as_of: datetime | None = None,
    ) -> DataQualityInfo:
        checked_at = as_of or datetime.now(timezone.utc)
        missing = [name for name in DataQualityService._REQUIRED_PRICES if getattr(bar, name) is None]
        non_finite = [
            name for name in (*DataQualityService._REQUIRED_PRICES, "pre_close", "volume", "amount", "adj_factor", "pct_chg")
            if (value := getattr(bar, name)) is not None and not math.isfinite(value)
        ]
        if non_finite:
            return DataQualityService._result(
                DataQualityStatus.INVALID, "NON_FINITE_VALUE", bar, checked_at,
                missing_fields=non_finite, message="numeric fields contain NaN or Infinity",
            )
        if bar.suspended:
            return DataQualityService._result(DataQualityStatus.SUSPENDED, "SUSPENDED", bar, checked_at)
        if missing:
            return DataQualityService._result(
                DataQualityStatus.PARTIAL, "MISSING_REQUIRED_FIELD", bar, checked_at,
                missing_fields=missing,
            )
        if any(getattr(bar, name) <= 0 for name in DataQualityService._REQUIRED_PRICES):
            return DataQualityService._result(DataQualityStatus.INVALID, "NON_POSITIVE_PRICE", bar, checked_at)
        if bar.volume is not None and bar.volume < 0:
            return DataQualityService._result(DataQualityStatus.INVALID, "NEGATIVE_VOLUME", bar, checked_at)
        if bar.amount is not None and bar.amount < 0:
            return DataQualityService._result(DataQualityStatus.INVALID, "NEGATIVE_AMOUNT", bar, checked_at)
        if bar.adj_factor is not None and bar.adj_factor <= 0:
            return DataQualityService._result(DataQualityStatus.INVALID, "INVALID_ADJ_FACTOR", bar, checked_at)
        assert bar.high is not None and bar.low is not None
        assert bar.open is not None and bar.close is not None
        if bar.high < max(bar.open, bar.close) or bar.low > min(bar.open, bar.close) or bar.high < bar.low:
            return DataQualityService._result(DataQualityStatus.INVALID, "INVALID_OHLC_BOUNDS", bar, checked_at)
        optional_missing = [name for name in ("pre_close", "volume", "amount", "adj_factor") if getattr(bar, name) is None]
        if optional_missing:
            return DataQualityService._result(
                DataQualityStatus.PARTIAL, "MISSING_OPTIONAL_FIELD", bar, checked_at,
                missing_fields=optional_missing,
            )
        return DataQualityService._result(DataQualityStatus.VALID, "OK", bar, checked_at)

    @staticmethod
    def classify_batch(
        bars: Iterable[DailyBar],
        *,
        as_of: datetime,
        source_version: str,
        duplicate_count: int = 0,
        stale_after: timedelta | None = None,
    ) -> DataQualityInfo:
        bars = list(bars)
        if not bars:
            return DataQualityInfo(
                status=DataQualityStatus.UNAVAILABLE,
                reason_code="NO_DATA",
                as_of=as_of,
                source_version=source_version,
            )
        qualities = [DataQualityService.validate_daily_bar(bar, as_of=as_of) for bar in bars]
        invalid_reasons = [q.reason_code for q in qualities if q.status == DataQualityStatus.INVALID]
        if invalid_reasons:
            return DataQualityInfo(
                status=DataQualityStatus.INVALID,
                reason_code=invalid_reasons[0],
                reason_codes=list(dict.fromkeys(invalid_reasons)),
                as_of=as_of,
                source_version=source_version,
            )
        if all(q.status == DataQualityStatus.SUSPENDED for q in qualities):
            status, reason = DataQualityStatus.SUSPENDED, "SUSPENDED"
        elif stale_after is not None:
            latest = max(bar.trade_date for bar in bars)
            age = as_of.date() - latest
            if age > stale_after:
                status, reason = DataQualityStatus.STALE, "STALE_DATA"
            else:
                status, reason = DataQualityStatus.VALID, "OK"
        else:
            status, reason = DataQualityStatus.VALID, "OK"
        reasons: list[str] = []
        if duplicate_count:
            status = DataQualityStatus.PARTIAL if status == DataQualityStatus.VALID else status
            reason = "DUPLICATE_BAR"
            reasons.append(reason)
        partial_reasons = [q.reason_code for q in qualities if q.status == DataQualityStatus.PARTIAL]
        if partial_reasons and status == DataQualityStatus.VALID:
            status, reason = DataQualityStatus.PARTIAL, partial_reasons[0]
        reasons.extend(partial_reasons)
        return DataQualityInfo(
            status=status,
            reason_code=reason,
            reason_codes=list(dict.fromkeys(reasons)),
            details={"duplicate_count": duplicate_count},
            as_of=as_of,
            source_version=source_version,
        )

    @staticmethod
    def _result(status, reason, bar, as_of, *, missing_fields=None, message=None):
        return DataQualityInfo(
            status=status,
            reason_code=reason,
            message=message,
            missing_fields=missing_fields or [],
            as_of=as_of,
            source_version=bar.source_version,
        )
