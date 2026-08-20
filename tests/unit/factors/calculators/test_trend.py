import pytest
import pandas as pd
import numpy as np
from app.services.factors.calculators.trend import calculate_trend_factors

def test_trend_factors_calculation():
    dates = pd.date_range("2025-01-01", periods=250, freq="B")
    close = pd.Series([10.0 + i * 0.1 for i in range(250)], index=dates)
    high = close + 0.2
    low = close - 0.2

    df = pd.DataFrame({"high": high, "low": low, "close": close})
    factors = calculate_trend_factors(df)

    assert len(factors) == 23

    # Check unmultiplied MACD
    assert "macd_hist" in factors
    assert "kdj_j" in factors
    assert not np.isnan(factors["sma_20"].iloc[-1])
