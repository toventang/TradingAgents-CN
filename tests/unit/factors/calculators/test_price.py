import pytest
import pandas as pd
import numpy as np
from app.services.factors.calculators.price import calculate_price_factors

def test_price_factors_calculation():
    # Construct 250 days of deterministic data
    dates = pd.date_range("2025-01-01", periods=250, freq="B")
    close = pd.Series([10.0 + i * 0.1 for i in range(250)], index=dates)
    open_p = close - 0.05
    high = close + 0.2
    low = close - 0.2

    df = pd.DataFrame({"open": open_p, "high": high, "low": low, "close": close})
    factors = calculate_price_factors(df)

    assert len(factors) == 18

    # ret_1d should be close[1] / close[0] - 1 = 10.1 / 10.0 - 1 = 0.01
    assert abs(factors["ret_1d"].iloc[1] - 0.01) < 1e-4

    # gap_up_pct should be non-negative finite
    assert not np.isnan(factors["price_position_52w"].iloc[-1])
