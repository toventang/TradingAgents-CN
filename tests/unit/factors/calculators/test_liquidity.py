import numpy as np
import pandas as pd
import pytest

from app.models.factor import FactorCategory
from app.services.factors.calculators.common import SUSPENDED, ZERO_DENOMINATOR
from app.services.factors.calculators.liquidity import calculate_liquidity_factors
from app.services.factors.registry import global_factor_registry


def _liquidity_frame(length=65):
    returns = np.repeat(0.01, length - 1)
    close = np.r_[100.0, 100.0 * np.cumprod(1.0 + returns)]
    volume = np.repeat(1_000.0, length)
    return pd.DataFrame(
        {
            "market": "US",
            "symbol": "AAA",
            "trade_date": pd.date_range("2025-01-01", periods=length, freq="B"),
            "high": close + 1.0,
            "low": close - 3.0,
            "close": close,
            "volume": volume,
            "amount": close * volume,
            "turnover_rate": 0.01 + np.arange(length) * 0.0001,
            "suspended": False,
        },
        index=[f"row-{index}" for index in range(length)],
    )


def test_all_19_outputs_and_hand_calculated_mfi_cmf_and_vwap():
    frame = _liquidity_frame()
    output = calculate_liquidity_factors(frame)

    assert len(output) == 19
    assert set(output) == {
        item.factor_id
        for item in global_factor_registry.get_by_category(FactorCategory.LIQUIDITY)
    }
    assert output["mfi_14"].iloc[-1] == pytest.approx(100.0)
    assert output["cmf_20"].iloc[-1] == pytest.approx(0.5)
    expected_vwap = frame["close"].iloc[-20:].mean()
    assert output["vwap_deviation_20"].iloc[-1] == pytest.approx(
        frame["close"].iloc[-1] / expected_vwap - 1.0
    )


def test_amihud_normalizes_amount_before_hand_calculated_illiquidity():
    base = _liquidity_frame(25)
    millions = base.copy()
    millions["amount"] = millions["amount"] / 1_000_000.0

    base_output = calculate_liquidity_factors(base)
    million_output = calculate_liquidity_factors(millions, amount_unit="million")
    expected = np.mean(
        np.repeat(0.01, 20) / base["amount"].iloc[-20:].to_numpy()
    )
    assert base_output["amihud_illiq_20"].iloc[-1] == pytest.approx(expected)
    assert million_output["amihud_illiq_20"].iloc[-1] == pytest.approx(expected)
    assert million_output["vwap_deviation_20"].iloc[-1] == pytest.approx(
        base_output["vwap_deviation_20"].iloc[-1]
    )


def test_suspension_is_not_counted_as_a_real_zero_volume_day():
    frame = _liquidity_frame(20)
    frame.loc["row-3", ["volume", "amount"]] = 0.0
    frame.loc["row-3", "suspended"] = True
    frame.loc["row-7", ["volume", "amount"]] = 0.0
    output = calculate_liquidity_factors(frame)

    assert output["zero_volume_days_20"].iloc[-1] == pytest.approx(1.0 / 19.0)
    assert np.isnan(output["turnover_rate"].loc["row-3"])
    assert output.quality_reasons["turnover_rate"].loc["row-3"] == SUSPENDED


def test_zero_denominators_and_invalid_amount_units_are_explicit():
    frame = _liquidity_frame(21)
    frame["volume"] = 0.0
    frame["amount"] = 0.0
    output = calculate_liquidity_factors(frame)
    assert np.isnan(output["volume_ratio_20"].iloc[-1])
    assert output.quality_reasons["volume_ratio_20"].iloc[-1] == ZERO_DENOMINATOR
    assert np.isnan(output["cmf_20"].iloc[-1])
    assert output.quality_reasons["cmf_20"].iloc[-1] == ZERO_DENOMINATOR

    with pytest.raises(ValueError, match="unsupported amount unit"):
        calculate_liquidity_factors(_liquidity_frame(), amount_unit="lots")


def test_obv_change_formula_and_future_rows_are_causal():
    short = _liquidity_frame(40)
    long = _liquidity_frame(65)
    short_output = calculate_liquidity_factors(short)
    long_output = calculate_liquidity_factors(long)
    expected_obv_change = (
        short_output["obv"].iloc[-1]
        / abs(short_output["obv"].iloc[-21])
        - 1.0
    )
    assert short_output["obv_change_20"].iloc[-1] == pytest.approx(expected_obv_change)
    for factor_id in short_output:
        pd.testing.assert_series_equal(
            short_output[factor_id],
            long_output[factor_id].iloc[: len(short)].set_axis(short.index),
        )
