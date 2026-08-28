import numpy as np
import pandas as pd
import pytest

from app.models.factor import FactorCategory
from app.services.factors.calculators.common import ZERO_DENOMINATOR
from app.services.factors.calculators.volatility import calculate_volatility_factors
from app.services.factors.registry import global_factor_registry


def _prices_from_returns(returns, start=100.0):
    return np.r_[start, start * np.cumprod(1.0 + np.asarray(returns, dtype=float))]


def _risk_frame(close, *, market="US"):
    close = np.asarray(close, dtype=float)
    return pd.DataFrame(
        {
            "market": market,
            "symbol": "AAA",
            "trade_date": pd.date_range("2025-01-01", periods=len(close), freq="B"),
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "pre_close": np.r_[np.nan, close[:-1]],
        },
        index=[f"row-{index}" for index in range(len(close))],
    )


def test_all_20_outputs_match_registry_and_hand_calculated_atr_drawdown_var():
    returns = np.r_[-0.20, -0.10, np.repeat(0.01, 18)]
    frame = _risk_frame(_prices_from_returns(returns))
    frame["high"] = frame["close"] + 1.0
    frame["low"] = frame["close"] - 1.0
    frame.loc[:, "pre_close"] = frame["close"]
    frame["benchmark_close"] = frame["close"]
    output = calculate_volatility_factors(frame)

    assert len(output) == 20
    assert set(output) == {
        item.factor_id
        for item in global_factor_registry.get_by_category(FactorCategory.VOLATILITY)
    }
    assert output["atr_14"].iloc[-1] == pytest.approx(2.0)
    assert output["var_95_20"].iloc[-1] == pytest.approx(0.105)

    drawdown_close = np.r_[50.0, 100.0, 120.0, 90.0, np.repeat(90.0, 17)]
    drawdown_frame = _risk_frame(drawdown_close)
    drawdown_frame["benchmark_close"] = drawdown_frame["close"]
    drawdown = calculate_volatility_factors(drawdown_frame)
    assert drawdown["max_drawdown_20"].iloc[-1] == pytest.approx(0.25)


def test_beta_alpha_and_idiosyncratic_vol_use_trade_date_alignment():
    benchmark_returns = np.linspace(-0.02, 0.02, 60)
    symbol_returns = 0.001 + 2.0 * benchmark_returns
    symbol_close = _prices_from_returns(symbol_returns)
    benchmark_close = _prices_from_returns(benchmark_returns)
    frame = _risk_frame(symbol_close)
    benchmark = pd.DataFrame(
        {
            "market": "US",
            "trade_date": frame["trade_date"].to_numpy(),
            "close": benchmark_close,
        }
    ).sample(frac=1.0, random_state=7)

    output = calculate_volatility_factors(frame, benchmark=benchmark)

    assert output["beta_60"].iloc[-1] == pytest.approx(2.0)
    assert output["alpha_60"].iloc[-1] == pytest.approx(0.252)
    assert output["idio_vol_60"].iloc[-1] == pytest.approx(0.0, abs=1e-8)
    assert output.provenance["beta_60"]["alignment"] == "market and trade_date"


def test_annualization_is_market_parameterized_and_cvar_is_positive_loss():
    returns = np.resize(np.array([-0.03, -0.01, 0.02, 0.01]), 120)
    frame = _risk_frame(_prices_from_returns(returns))
    frame["benchmark_close"] = frame["close"]
    output = calculate_volatility_factors(
        frame, market_trading_days={"US": 100, "CN": 244, "HK": 250}
    )
    expected = pd.Series(np.log1p(returns[:5])).std(ddof=1) * 10.0
    assert output["hist_vol_5"].iloc[5] == pytest.approx(expected)
    assert output["cvar_95_60"].iloc[-1] > 0
    assert output.provenance["hist_vol_5"]["annual_trading_days"] == 100


def test_zero_benchmark_variance_and_duplicate_benchmark_dates_are_rejected_safely():
    frame = _risk_frame(_prices_from_returns(np.repeat(0.01, 60)))
    frame["benchmark_close"] = 100.0
    output = calculate_volatility_factors(frame)
    assert np.isnan(output["beta_60"].iloc[-1])
    assert output.quality_reasons["beta_60"].iloc[-1] == ZERO_DENOMINATOR

    duplicate = pd.DataFrame(
        {"trade_date": [frame["trade_date"].iloc[0]] * 2, "close": [100.0, 101.0]}
    )
    with pytest.raises(ValueError, match="duplicate"):
        calculate_volatility_factors(frame, benchmark=duplicate)


def test_appending_future_rows_does_not_change_historical_risk_values():
    returns = np.resize(np.array([-0.01, 0.02, 0.005]), 300)
    short = _risk_frame(_prices_from_returns(returns[:260]))
    long = _risk_frame(_prices_from_returns(returns))
    short["benchmark_close"] = _prices_from_returns(returns[:260] * 0.5)
    long["benchmark_close"] = _prices_from_returns(returns * 0.5)
    baseline = calculate_volatility_factors(short)
    extended = calculate_volatility_factors(long)
    for factor_id in baseline:
        pd.testing.assert_series_equal(
            baseline[factor_id],
            extended[factor_id].iloc[: len(short)].set_axis(short.index),
        )
