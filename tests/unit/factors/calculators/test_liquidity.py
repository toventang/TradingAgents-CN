import pytest
import pandas as pd
import numpy as np
from app.services.factors.calculators.liquidity import calculate_liquidity_factors

def test_liquidity_factors_calculation():
    dates = pd.date_range("2025-01-01", periods=100, freq="B")
    close = pd.Series([10.0 + i * 0.05 for i in range(100)], index=dates)
    high = close + 0.2
    low = close - 0.2
    volume = pd.Series([10000.0 + i * 100 for i in range(100)], index=dates)
    amount = volume * close
    turnover = pd.Series([0.02 + i * 0.0001 for i in range(100)], index=dates)

    df = pd.DataFrame({
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "amount": amount,
        "turnover_rate": turnover
    })

    factors = calculate_liquidity_factors(df)

    assert len(factors) == 19

    # Volume ratio 5/20
    assert not np.isnan(factors["volume_ratio_5_20"].iloc[-1])
    assert "amihud_illiquidity_20d" in factors
    assert "obv" in factors
    assert "cmf_20" in factors
