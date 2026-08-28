import numpy as np
import pandas as pd
import pytest

from app.services.factors.calculators.common import ZERO_DENOMINATOR
from app.services.factors.calculators.momentum import calculate_momentum_factors
from app.models.factor import FactorCategory
from app.services.factors.registry import global_factor_registry


def _momentum_frame(close, spread=1.0):
    close = pd.Series(close, dtype=float)
    return pd.DataFrame(
        {
            "trade_date": pd.date_range("2024-01-01", periods=len(close), freq="B"),
            "high": close + spread,
            "low": close - spread,
            "close": close,
            "pre_close": close.shift(1),
        }
    )


def test_wilder_rsi_method_is_explicit_for_monotonic_and_constant_inputs():
    increasing = calculate_momentum_factors(_momentum_frame(np.arange(1, 101)))
    decreasing = calculate_momentum_factors(_momentum_frame(np.arange(100, 0, -1)))
    constant = calculate_momentum_factors(_momentum_frame(np.full(100, 10.0)))
    for window in (6, 12, 14, 24):
        assert increasing[f"rsi_{window}"].iloc[-1] == pytest.approx(100.0)
        assert decreasing[f"rsi_{window}"].iloc[-1] == pytest.approx(0.0)
        assert constant[f"rsi_{window}"].iloc[-1] == pytest.approx(50.0)
        assert increasing.provenance[f"rsi_{window}"]["method"] == "wilder"
    with pytest.raises(ValueError, match="unsupported RSI method"):
        calculate_momentum_factors(_momentum_frame(np.arange(30)), rsi_method="simple")


def test_hand_calculated_roc_cci_williams_momentum_and_dpo():
    output = calculate_momentum_factors(_momentum_frame(np.arange(1, 101)))
    assert len(output) == 18
    assert set(output) == {
        item.factor_id for item in global_factor_registry.get_by_category(FactorCategory.MOMENTUM)
    }
    assert output["roc_5"].iloc[5] == pytest.approx(6 / 1 - 1)
    assert output["cci_14"].iloc[13] == pytest.approx(6.5 / (0.015 * 3.5))
    assert output["williams_r_14"].iloc[13] == pytest.approx(-100 / 15)
    assert output["momentum_10"].iloc[10] == pytest.approx(10.0)
    assert output["dpo_20"].iloc[19] == pytest.approx(-1.5)
    assert output["ppo_12_26"].iloc[-1] > 0
    assert output["trix_15"].iloc[-1] > 0
    assert 0 <= output["ultimate_osc_7_14_28"].iloc[-1] <= 100


def test_zero_range_oscillators_are_missing_with_reason():
    output = calculate_momentum_factors(_momentum_frame(np.full(40, 10.0), spread=0.0))
    for factor_id in ("kdj_k", "kdj_d", "kdj_j", "cci_14", "williams_r_14"):
        assert np.isnan(output[factor_id].iloc[-1])
        assert output.quality_reasons[factor_id].iloc[-1] == ZERO_DENOMINATOR


def test_appending_future_rows_never_changes_historical_momentum_values():
    historical = 10 + np.sin(np.arange(100) / 5)
    baseline = calculate_momentum_factors(_momentum_frame(historical))
    extended = calculate_momentum_factors(
        _momentum_frame(np.concatenate((historical, np.array([1000.0, 1.0, 500.0]))))
    )
    for factor_id in baseline:
        pd.testing.assert_series_equal(baseline[factor_id], extended[factor_id].iloc[:100])
