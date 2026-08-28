import numpy as np
import pandas as pd
import pytest

from app.services.factors.calculators.common import (
    INSUFFICIENT_HISTORY,
    ZERO_DENOMINATOR,
    adapt_macd_hist_for_legacy_ui,
)
from app.services.factors.calculators.trend import calculate_trend_factors
from app.models.factor import FactorCategory
from app.services.factors.registry import global_factor_registry


def _trend_frame(close, market="US"):
    close = pd.Series(close, dtype=float)
    return pd.DataFrame(
        {
            "market": market,
            "trade_date": pd.date_range("2024-01-01", periods=len(close), freq="B"),
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "pre_close": close.shift(1),
        }
    )


def test_constant_fixture_has_zero_ratios_unmultiplied_macd_and_explicit_zero_r2():
    output = calculate_trend_factors(_trend_frame(np.full(300, 10.0)))
    assert len(output) == 23
    assert set(output) == {
        item.factor_id for item in global_factor_registry.get_by_category(FactorCategory.TREND)
    }
    assert output["ma_ratio_20"].iloc[-1] == pytest.approx(0.0)
    assert output["ema_ratio_20"].iloc[-1] == pytest.approx(0.0)
    assert output["macd_dif"].iloc[-1] == pytest.approx(0.0)
    assert output["macd_dea"].iloc[-1] == pytest.approx(0.0)
    assert output["macd_hist"].iloc[-1] == pytest.approx(
        output["macd_dif"].iloc[-1] - output["macd_dea"].iloc[-1]
    )
    assert output.provenance["macd_hist"]["hist_multiplier"] == 1
    assert adapt_macd_hist_for_legacy_ui(output["macd_hist"]).iloc[-1] == pytest.approx(
        output["macd_hist"].iloc[-1] * 2
    )
    assert np.isnan(output["trend_r2_60"].iloc[-1])
    assert output.quality_reasons["trend_r2_60"].iloc[-1] == ZERO_DENOMINATOR


def test_log_linear_fixture_has_hand_calculated_annual_slope_and_unit_r_squared():
    daily_log_slope = 0.001
    close = np.exp(daily_log_slope * np.arange(100))
    output = calculate_trend_factors(_trend_frame(close, market="US"))
    assert output["linear_slope_20"].iloc[-1] == pytest.approx(daily_log_slope * 252)
    assert output["linear_slope_60"].iloc[-1] == pytest.approx(daily_log_slope * 252)
    assert output["trend_r2_60"].iloc[-1] == pytest.approx(1.0)


def test_monotonic_and_short_history_trend_boundaries():
    monotonic = calculate_trend_factors(_trend_frame(np.arange(1, 301)))
    assert monotonic["aroon_up_25"].iloc[-1] == pytest.approx(100.0)
    assert monotonic["aroon_down_25"].iloc[-1] == pytest.approx(0.0)
    assert monotonic["adx_14"].iloc[-1] == pytest.approx(100.0)

    short = calculate_trend_factors(_trend_frame(np.arange(1, 10)))
    assert short["ma_ratio_20"].isna().all()
    assert short.quality_reasons["ma_ratio_20"].iloc[-1] == INSUFFICIENT_HISTORY


def test_appending_future_rows_never_changes_historical_trend_values():
    baseline_frame = _trend_frame(np.linspace(10, 30, 100))
    extended_frame = _trend_frame(np.linspace(10, 30, 100).tolist() + [500, 1, 900])
    baseline = calculate_trend_factors(baseline_frame)
    extended = calculate_trend_factors(extended_frame)
    for factor_id in baseline:
        pd.testing.assert_series_equal(baseline[factor_id], extended[factor_id].iloc[:100])
