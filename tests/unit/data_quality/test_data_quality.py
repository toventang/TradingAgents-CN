from datetime import datetime, timedelta, timezone

from app.models.market_data import DailyBar, DataQualityStatus
from app.services.data_quality.quality_service import DataQualityService


def _bar(**changes):
    values = dict(
        symbol="000001", market="CN", trade_date="2026-08-21",
        open=10.0, high=10.5, low=9.8, close=10.2, pre_close=10.0,
        volume=10_000, amount=101_000, adj_factor=1.0, pct_chg=0.02,
        source="fixture", source_version="fixture-v1",
    )
    values.update(changes)
    return DailyBar(**values)


def test_valid_and_invalid_ohlcv_are_classified_deterministically():
    assert DataQualityService.validate_daily_bar(_bar()).status == DataQualityStatus.VALID

    invalid_bounds = DataQualityService.validate_daily_bar(_bar(high=9.5))
    assert invalid_bounds.status == DataQualityStatus.INVALID
    assert invalid_bounds.reason_code == "INVALID_OHLC_BOUNDS"

    negative_volume = DataQualityService.validate_daily_bar(_bar(volume=-1))
    assert negative_volume.reason_code == "NEGATIVE_VOLUME"


def test_missing_nonfinite_stale_and_suspended_states():
    assert DataQualityService.validate_daily_bar(_bar(open=None)).status == DataQualityStatus.PARTIAL
    assert DataQualityService.validate_daily_bar(_bar(close=float("nan"))).reason_code == "NON_FINITE_VALUE"
    assert DataQualityService.validate_daily_bar(_bar(suspended=True)).status == DataQualityStatus.SUSPENDED

    as_of = datetime(2026, 8, 28, tzinfo=timezone.utc)
    stale = DataQualityService.classify_batch(
        [_bar(trade_date="2026-08-21")], as_of=as_of,
        source_version="fixture-v1", stale_after=timedelta(days=3),
    )
    assert stale.status == DataQualityStatus.STALE
    assert stale.usable_for_automated_buy is False


def test_duplicate_batch_is_partial_with_reason():
    as_of = datetime(2026, 8, 21, 12, tzinfo=timezone.utc)
    quality = DataQualityService.classify_batch(
        [_bar()], as_of=as_of, source_version="fixture-v1", duplicate_count=1
    )
    assert quality.status == DataQualityStatus.PARTIAL
    assert "DUPLICATE_BAR" in quality.reason_codes
