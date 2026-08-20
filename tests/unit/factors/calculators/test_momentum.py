import pytest
import pandas as pd
import numpy as np
from app.services.factors.calculators.momentum import calculate_momentum_factors

def test_momentum_factors_calculation():
    dates = pd.date_range("2025-01-01", periods=100, freq="B")
    close = pd.Series([10.0 + np.sin(i / 5.0) for i in range(100)], index=dates)
    high = close + 0.5
    low = close - 0.5

    df = pd.DataFrame({"high": high, "low": low, "close": close})
    factors = calculate_momentum_factors(df)

    assert len(factors) == 18

    # RSI should be between 0 and 100
    rsi6 = factors["rsi_6"].dropna()
    assert (rsi6 >= 0).all() and (rsi6 <= 100).all()
    assert "stoch_rsi_k" in factors
    assert "willr_14" in factors
