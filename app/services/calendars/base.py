"""Protocol consumed by execution and research services."""

from datetime import datetime
from typing import Protocol
from zoneinfo import ZoneInfo

from app.models.symbol import Market
from app.services.calendars.market_calendar import DateLike, TradingSession


class MarketCalendar(Protocol):
    def timezone(self, market: Market | str) -> ZoneInfo: ...

    def is_trade_day(self, market: Market | str, value: DateLike, **kwargs) -> bool: ...

    def sessions(self, market: Market | str, value: DateLike, **kwargs) -> list[TradingSession]: ...

    def next_legal_point(self, market: Market | str, requested_at: datetime, **kwargs) -> datetime: ...

    def previous_legal_point(self, market: Market | str, requested_at: datetime, **kwargs) -> datetime: ...
