import pytest
from app.services.calendars.market_calendar import MarketCalendarService

def test_market_calendar_trade_days():
    # 2026-08-22 is Saturday, 2026-08-24 is Monday
    assert MarketCalendarService.is_trade_day("CN", "2026-08-22") is False
    assert MarketCalendarService.is_trade_day("CN", "2026-08-24") is True

    trading_days = MarketCalendarService.get_trading_days("CN", "2026-08-21", "2026-08-25")
    assert "2026-08-22" not in trading_days
    assert "2026-08-23" not in trading_days
    assert "2026-08-21" in trading_days
    assert "2026-08-24" in trading_days

def test_next_prev_trade_day():
    # Friday 2026-08-21 -> Next trade day is Monday 2026-08-24
    next_day = MarketCalendarService.get_next_trade_day("CN", "2026-08-21")
    assert next_day == "2026-08-24"

    # Monday 2026-08-24 -> Prev trade day is Friday 2026-08-21
    prev_day = MarketCalendarService.get_prev_trade_day("CN", "2026-08-24")
    assert prev_day == "2026-08-21"
