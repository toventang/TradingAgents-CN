from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.services.calendars.market_calendar import MarketCalendarService


def test_trade_days_holidays_and_session_breaks():
    calendar = MarketCalendarService
    assert calendar.is_trade_day("CN", "2026-08-22") is False
    assert calendar.is_trade_day("CN", "2026-08-24") is True
    assert calendar.is_trade_day("CN", "2026-08-24", holidays=["2026-08-24"]) is False
    assert calendar.get_next_trade_day("CN", "2026-08-21") == "2026-08-24"
    assert calendar.get_prev_trade_day("CN", "2026-08-24") == "2026-08-21"

    lunch = datetime(2026, 8, 24, 12, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert calendar.next_legal_point("CN", lunch).hour == 13
    assert calendar.previous_legal_point("CN", lunch).hour == 11
    assert calendar.previous_legal_point("CN", lunch).minute == 30


def test_us_sessions_observe_dst_and_naive_time_is_rejected():
    winter = MarketCalendarService.sessions("US", "2026-01-05")[0]
    summer = MarketCalendarService.sessions("US", "2026-07-06")[0]
    assert winter.opens_at.utcoffset().total_seconds() == -5 * 3600
    assert summer.opens_at.utcoffset().total_seconds() == -4 * 3600
    with pytest.raises(ValueError, match="timezone-aware"):
        MarketCalendarService.next_legal_point("US", datetime(2026, 1, 5, 10))


def test_after_close_moves_to_next_legal_session():
    after_close = datetime(2026, 8, 21, 16, tzinfo=ZoneInfo("Asia/Shanghai"))
    next_point = MarketCalendarService.next_legal_point("CN", after_close)
    assert next_point.isoformat() == "2026-08-24T09:30:00+08:00"
