import pytest
import pandas as pd
import numpy as np
from app.services.factors.calculators.fundamental import calculate_fundamental_factors

def test_fundamental_factors_calculation():
    dates = pd.date_range("2025-01-01", periods=10, freq="B")
    df = pd.DataFrame({"close": [10.0] * 10})

    fin_data = {
        "pe_ttm": 15.0,
        "pb_mrq": 2.0,
        "roe": 0.12,
        "gross_margin": 0.35,
        "netprofit_margin": 0.15,
        "revenue_growth_yoy": 0.20
    }

    factors = calculate_fundamental_factors(df, financial_data=fin_data)

    assert len(factors) == 51

    # Check earnings_yield (1/PE = 1/15)
    ey = factors["earnings_yield"].iloc[-1]
    assert abs(ey - (1.0 / 15.0)) < 1e-4

    # Check book_to_market (1/PB = 1/2)
    bm = factors["book_to_market"].iloc[-1]
    assert abs(bm - 0.5) < 1e-4

    # Negative PE -> earnings_yield should be NaN (non-positive denominator rule)
    fin_negative = {"pe_ttm": -5.0}
    factors_neg = calculate_fundamental_factors(df, financial_data=fin_negative)
    assert np.isnan(factors_neg["earnings_yield"].iloc[-1])
