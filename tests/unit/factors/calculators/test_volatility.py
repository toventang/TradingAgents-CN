import pytest
import pandas as pd
import numpy as np
from app.services.factors.calculators.volatility import calculate_volatility_factors

def test_volatility_factors_calculation():
    dates = pd.date_range("2025-01-01", periods=250, freq="B")
    close = pd.Series([10.0 + np.sin(i / 10.0) for i in range(250)], index=dates)
    high = close + 0.3
    low = close - 0.3

    df = pd.DataFrame({"high": high, "low": low, "close": close})
    factors = calculate_volatility_factors(df)

    assert len(factors) == 20

    # Max drawdown over 60d must be between 0 and 1
    mdd = factors["max_drawdown_60d"].dropna()
    assert (mdd >= 0.0).all() and (mdd <= 1.0).all()

    # VaR 95% positive loss convention
    assert "var_95_20d" in factors
    assert "cvar_95_20d" in factors
    assert "bbands_bandwidth" in factors
