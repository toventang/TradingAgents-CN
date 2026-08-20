import pytest
import pandas as pd
import numpy as np
from app.services.factors.calculators.cross_section import calculate_cross_sectional_factors

def test_cross_sectional_factors_min_symbols_threshold():
    # Fewer than 20 symbols -> returns all NaN
    symbols = [f"00000{i}" for i in range(10)]
    matrix_small = pd.DataFrame({
        "ret_20d": [0.01 * i for i in range(10)],
        "market_cap": [1e10 + i * 1e8 for i in range(10)]
    }, index=symbols)

    factors_small = calculate_cross_sectional_factors(matrix_small, min_universe_symbols=20)
    assert len(factors_small) == 10
    assert np.isnan(factors_small["size_factor"].iloc[0])

def test_cross_sectional_factors_valid_universe():
    # 25 symbols -> valid calculation
    symbols = [f"stock_{i}" for i in range(25)]
    matrix_large = pd.DataFrame({
        "ret_20d": [0.01 * i for i in range(25)],
        "market_cap": [1e10 + i * 1e8 for i in range(25)],
        "book_to_market": [0.5 + i * 0.01 for i in range(25)]
    }, index=symbols)

    factors_large = calculate_cross_sectional_factors(matrix_large, min_universe_symbols=20)
    assert len(factors_large) == 10
    assert not np.isnan(factors_large["size_factor"].iloc[0])
    assert not np.isnan(factors_large["value_composite"].iloc[0])
