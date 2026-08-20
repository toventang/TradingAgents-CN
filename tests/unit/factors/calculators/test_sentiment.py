import pytest
import pandas as pd
import numpy as np
from app.services.factors.calculators.sentiment import calculate_sentiment_factors

def test_sentiment_factors_calculation():
    dates = pd.date_range("2025-01-01", periods=30, freq="B")
    close = pd.Series([10.0 + i * 0.1 for i in range(30)], index=dates)
    pct_chg = pd.Series([10.0 if i % 5 == 0 else 0.0 for i in range(30)], index=dates)
    volume = pd.Series([10000.0] * 30, index=dates)

    df = pd.DataFrame({"close": close, "pct_chg": pct_chg, "volume": volume})
    sent_data = {
        "news_sentiment_3d": 0.8,
        "analyst_rating_mean": 2.1,
        "target_price": 15.0
    }

    factors = calculate_sentiment_factors(df, sentiment_data=sent_data)

    assert len(factors) == 12
    assert factors["limit_up_count_20d"].iloc[-1] >= 1
    assert "suspension_flag" in factors
    assert "analyst_target_price_upside" in factors
