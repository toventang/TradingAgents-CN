import pytest
from datetime import datetime, timedelta
from app.models.market_data import DailyBar, PointInTimeFact, NewsSocialInput, DataQualityStatus
from app.utils.timezone import now_tz

def test_point_in_time_fact_visibility():
    now = now_tz()
    past_fact = PointInTimeFact(
        fact_id="f1",
        symbol="000001",
        market="CN",
        report_period="2024Q1",
        publish_at=now - timedelta(days=1),
        fact_type="financial",
        data={"roe": 0.15}
    )
    future_fact = PointInTimeFact(
        fact_id="f2",
        symbol="000001",
        market="CN",
        report_period="2024Q1",
        publish_at=now + timedelta(days=1),
        fact_type="financial",
        data={"roe": 0.18}
    )

    # Past fact is visible as of now
    assert past_fact.is_visible_at(now) is True
    # Future fact is NOT visible as of now (prevents look-ahead bias)
    assert future_fact.is_visible_at(now) is False

def test_news_input_visibility():
    now = now_tz()
    news = NewsSocialInput(
        news_id="n1",
        symbol="AAPL",
        market="US",
        published_at=now + timedelta(hours=2),
        title="Breaking News"
    )
    assert news.is_visible_at(now) is False
    assert news.is_visible_at(now + timedelta(hours=3)) is True
