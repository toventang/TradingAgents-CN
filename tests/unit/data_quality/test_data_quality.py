import pytest
import math
from app.models.market_data import DailyBar, DataQualityStatus
from app.services.data_quality.quality_service import DataQualityService

def test_valid_daily_bar_quality():
    bar = DailyBar(
        symbol="000001",
        market="CN",
        trade_date="2026-08-21",
        open=10.0,
        high=10.5,
        low=9.8,
        close=10.2,
        volume=10000.0,
        amount=101000.0,
        pct_chg=2.0
    )
    qual = DataQualityService.validate_daily_bar(bar)
    assert qual.status == DataQualityStatus.VALID

def test_invalid_ohlc_bounds_quality():
    # High < Open -> Invalid
    bar = DailyBar(
        symbol="000001",
        market="CN",
        trade_date="2026-08-21",
        open=10.0,
        high=9.5,
        low=9.0,
        close=9.2,
        volume=10000.0,
        amount=95000.0,
        pct_chg=-8.0
    )
    qual = DataQualityService.validate_daily_bar(bar)
    assert qual.status == DataQualityStatus.INVALID
    assert qual.reason_code == "INVALID_OHLC_BOUNDS"

def test_negative_volume_quality():
    bar = DailyBar(
        symbol="000001",
        market="CN",
        trade_date="2026-08-21",
        open=10.0,
        high=10.5,
        low=9.8,
        close=10.2,
        volume=-100.0,
        amount=1000.0,
        pct_chg=2.0
    )
    qual = DataQualityService.validate_daily_bar(bar)
    assert qual.status == DataQualityStatus.INVALID
    assert qual.reason_code == "NEGATIVE_VOLUME"
