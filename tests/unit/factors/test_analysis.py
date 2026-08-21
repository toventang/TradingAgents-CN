import pytest
import pandas as pd
import numpy as np
from app.services.factors.analysis import FactorAnalysisService

def test_forward_returns_prevents_future_leakage():
    dates = pd.date_range("2025-01-01", periods=10, freq="B")
    close = pd.Series([10, 11, 12, 13, 14, 15, 16, 17, 18, 19], index=dates)
    price_df = pd.DataFrame({"AAPL": close})

    fwd_rets = FactorAnalysisService.compute_forward_returns(price_df, periods=[1])
    fwd_1d = fwd_rets[1]["AAPL"]

    # At day 0 (close=10), forward 1d return is (11 - 10) / 10 = 0.1
    assert abs(fwd_1d.iloc[0] - 0.1) < 1e-5

    # At last day (close=19), forward 1d return is NaN (cannot see future)
    assert np.isnan(fwd_1d.iloc[-1])

def test_factor_analysis_ic_and_quantiles():
    dates = pd.date_range("2025-01-01", periods=20, freq="B")
    symbols = [f"stock_{i}" for i in range(25)]

    # Create factor matrix and price matrix for 25 stocks
    factor_data = {}
    price_data = {}
    for i, sym in enumerate(symbols):
        factor_data[sym] = pd.Series([i * 1.0] * 20, index=dates)
        price_data[sym] = pd.Series([10.0 + i * 0.5 + j * 0.1 for j in range(20)], index=dates)

    factor_df = pd.DataFrame(factor_data)
    price_df = pd.DataFrame(price_data)

    results = FactorAnalysisService.analyze_factor(
        factor_matrix=factor_df,
        price_matrix=price_df,
        periods=[1, 5],
        quantiles=5,
        min_symbols=20
    )

    assert "period_1d" in results
    assert "ic_mean" in results["period_1d"]
    assert "quantile_returns" in results["period_1d"]
    assert "Q1" in results["period_1d"]["quantile_returns"]
