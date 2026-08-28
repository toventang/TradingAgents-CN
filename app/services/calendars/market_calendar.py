"""Deterministic market-session calendar contract.

The service supplies exchange-local sessions and accepts an explicit holiday
set.  It never guesses holidays from current wall-clock state or an external
API, making historical calculations reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterable
from zoneinfo import ZoneInfo

from app.models.symbol import Market


DateLike = str | date | datetime


@dataclass(frozen=True)
class TradingSession:
    opens_at: datetime
    closes_at: datetime

    def __post_init__(self) -> None:
        if self.opens_at.tzinfo is None or self.closes_at.tzinfo is None:
            raise ValueError("session timestamps must be timezone-aware")
        if self.closes_at <= self.opens_at:
            raise ValueError("session close must be after open")


class MarketCalendarService:
    TIMEZONES = {
        Market.CN: ZoneInfo("Asia/Shanghai"),
        Market.HK: ZoneInfo("Asia/Hong_Kong"),
        Market.US: ZoneInfo("America/New_York"),
    }
    SESSION_TIMES = {
        Market.CN: ((time(9, 30), time(11, 30)), (time(13, 0), time(15, 0))),
        Market.HK: ((time(9, 30), time(12, 0)), (time(13, 0), time(16, 0))),
        Market.US: ((time(9, 30), time(16, 0)),),
    }

    @classmethod
    def timezone(cls, market: Market | str) -> ZoneInfo:
        return cls.TIMEZONES[Market(market)]

    @classmethod
    def is_trade_day(
        cls,
        market: Market | str,
        value: DateLike,
        *,
        holidays: Iterable[DateLike] = (),
    ) -> bool:
        day = cls._to_date(value, market)
        holiday_dates = {cls._to_date(item, market) for item in holidays}
        return day.weekday() < 5 and day not in holiday_dates

    @classmethod
    def get_trading_days(
        cls,
        market: Market | str,
        start_date: DateLike,
        end_date: DateLike,
        *,
        holidays: Iterable[DateLike] = (),
    ) -> list[str]:
        current = cls._to_date(start_date, market)
        end = cls._to_date(end_date, market)
        if end < current:
            raise ValueError("end_date must not precede start_date")
        result: list[str] = []
        while current <= end:
            if cls.is_trade_day(market, current, holidays=holidays):
                result.append(current.isoformat())
            current += timedelta(days=1)
        return result

    @classmethod
    def get_next_trade_day(
        cls, market: Market | str, value: DateLike, *, holidays: Iterable[DateLike] = ()
    ) -> str:
        return cls._shift_trade_day(market, value, 1, holidays=holidays).isoformat()

    @classmethod
    def get_prev_trade_day(
        cls, market: Market | str, value: DateLike, *, holidays: Iterable[DateLike] = ()
    ) -> str:
        return cls._shift_trade_day(market, value, -1, holidays=holidays).isoformat()

    @classmethod
    def sessions(
        cls, market: Market | str, value: DateLike, *, holidays: Iterable[DateLike] = ()
    ) -> list[TradingSession]:
        normalized_market = Market(market)
        day = cls._to_date(value, normalized_market)
        if not cls.is_trade_day(normalized_market, day, holidays=holidays):
            return []
        zone = cls.timezone(normalized_market)
        return [
            TradingSession(
                opens_at=datetime.combine(day, opens, zone),
                closes_at=datetime.combine(day, closes, zone),
            )
            for opens, closes in cls.SESSION_TIMES[normalized_market]
        ]

    get_sessions = sessions

    @classmethod
    def next_legal_point(
        cls, market: Market | str, requested_at: datetime, *, holidays: Iterable[DateLike] = ()
    ) -> datetime:
        local = cls._aware_local(requested_at, market)
        day_sessions = cls.sessions(market, local, holidays=holidays)
        for session in day_sessions:
            if local < session.opens_at:
                return session.opens_at
            if session.opens_at <= local <= session.closes_at:
                return local
        next_day = cls._shift_trade_day(market, local, 1, holidays=holidays)
        return cls.sessions(market, next_day, holidays=holidays)[0].opens_at

    @classmethod
    def previous_legal_point(
        cls, market: Market | str, requested_at: datetime, *, holidays: Iterable[DateLike] = ()
    ) -> datetime:
        local = cls._aware_local(requested_at, market)
        for session in reversed(cls.sessions(market, local, holidays=holidays)):
            if local > session.closes_at:
                return session.closes_at
            if session.opens_at <= local <= session.closes_at:
                return local
        previous_day = cls._shift_trade_day(market, local, -1, holidays=holidays)
        return cls.sessions(market, previous_day, holidays=holidays)[-1].closes_at

    @classmethod
    def next_execution_time(cls, market: Market | str, requested_at: datetime) -> datetime:
        """Compatibility with the paper-trading calendar protocol."""
        return cls.next_legal_point(market, requested_at)

    @classmethod
    def daily_as_of(
        cls, market: Market | str, value: DateLike, *, holidays: Iterable[DateLike] = ()
    ) -> datetime:
        sessions = cls.sessions(market, value, holidays=holidays)
        if not sessions:
            raise ValueError("daily as_of is undefined for a non-trading day")
        return sessions[-1].closes_at

    @classmethod
    def _shift_trade_day(cls, market, value, direction, *, holidays) -> date:
        current = cls._to_date(value, market) + timedelta(days=direction)
        while not cls.is_trade_day(market, current, holidays=holidays):
            current += timedelta(days=direction)
        return current

    @classmethod
    def _to_date(cls, value: DateLike, market: Market | str) -> date:
        if isinstance(value, datetime):
            if value.tzinfo is not None and value.utcoffset() is not None:
                return value.astimezone(cls.timezone(market)).date()
            return value.date()
        if isinstance(value, date):
            return value
        return date.fromisoformat(str(value)[:10])

    @classmethod
    def _aware_local(cls, value: datetime, market: Market | str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("calendar timestamps must be timezone-aware")
        return value.astimezone(cls.timezone(market))
