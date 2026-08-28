import numpy as np
import pandas as pd
import pytest

from app.services.factors.calculators.common import (
    INSUFFICIENT_HISTORY,
    NON_FINITE_INPUT,
    ZERO_DENOMINATOR,
)
from app.services.factors.calculators.price import calculate_price_factors
from app.models.factor import FactorCategory
from app.services.factors.registry import global_factor_registry


def _price_frame(length=260):
    index = pd.Index([f"row-{i}" for i in range(length)])
    close = pd.Series(np.arange(1, length + 1, dtype=float), index=index)
    return pd.DataFrame(
        {
            "trade_date": pd.date_range("2025-01-01", periods=length, freq="B"),
            "open": close - 0.25,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "pre_close": close.shift(1),
        },
        index=index,
    )


def test_all_18_price_formulas_use_exact_decimal_semantics():
    frame = _price_frame()
    output = calculate_price_factors(frame)
    assert len(output) == 18
    assert set(output) == {
        item.factor_id for item in global_factor_registry.get_by_category(FactorCategory.PRICE)
    }
    assert output["ret_1d"].loc["row-1"] == pytest.approx(1.0)
    assert output["ret_3d"].loc["row-3"] == pytest.approx(3.0)
    assert output["log_ret_1d"].loc["row-1"] == pytest.approx(np.log(2.0))
    assert output["gap_open_1d"].loc["row-1"] == pytest.approx(0.75)
    assert output["intraday_ret"].loc["row-1"] == pytest.approx(2.0 / 1.75 - 1.0)
    assert output["intraday_range"].loc["row-1"] == pytest.approx(2.0)
    assert output["close_location_value"].loc["row-10"] == pytest.approx(0.0)
    assert output["distance_20d_high"].iloc[-1] == pytest.approx(0.0)
    assert output["distance_20d_low"].iloc[-1] == pytest.approx(260 / 241 - 1)


def test_group_sorting_has_no_cross_symbol_leak_and_restores_original_index():
    frame = pd.DataFrame(
        {
            "symbol": ["A", "B", "A", "B"],
            "market": ["US"] * 4,
            "trade_date": ["2025-01-02", "2025-01-02", "2025-01-01", "2025-01-01"],
            "open": [2, 100, 1, 100], "high": [2, 100, 1, 100],
            "low": [2, 100, 1, 100], "close": [2, 100, 1, 100],
        },
        index=["a2", "b2", "a1", "b1"],
    )
    output = calculate_price_factors(frame)
    assert output["ret_1d"].index.tolist() == frame.index.tolist()
    assert output["ret_1d"].loc["a2"] == pytest.approx(1.0)
    assert output["ret_1d"].loc["b2"] == pytest.approx(0.0)


def test_zero_range_short_history_and_nonfinite_have_quality_reasons():
    frame = _price_frame(5)
    frame.loc["row-2", ["high", "low", "close"]] = 3.0
    frame.loc["row-3", "close"] = np.inf
    output = calculate_price_factors(frame)
    assert np.isnan(output["close_location_value"].loc["row-2"])
    assert output.quality_reasons["close_location_value"].loc["row-2"] == ZERO_DENOMINATOR
    assert output["ret_20d"].isna().all()
    assert output.quality_reasons["ret_20d"].iloc[-1] == INSUFFICIENT_HISTORY
    assert output.quality_reasons["ret_1d"].loc["row-3"] == NON_FINITE_INPUT


def test_appending_future_rows_never_changes_historical_price_values():
    frame = _price_frame(80)
    baseline = calculate_price_factors(frame)
    extended = calculate_price_factors(_price_frame(100))
    for factor_id in baseline:
        pd.testing.assert_series_equal(
            baseline[factor_id], extended[factor_id].iloc[:80].set_axis(frame.index)
        )


def test_empty_input_still_exposes_the_registered_output_contract():
    output = calculate_price_factors(pd.DataFrame())
    assert len(output) == 18
    assert all(series.empty for series in output.values())
