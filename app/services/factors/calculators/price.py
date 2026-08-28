"""Causal implementations of the 18 return and price-position factors."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.services.factors.calculators.common import (
    FactorOutput,
    calculate_per_symbol,
    numeric,
    previous_close,
    rolling_extreme,
    safe_divide,
)


RETURN_WINDOWS = (1, 3, 5, 10, 20, 60, 120, 250)


def calculate_price_factors(frame: pd.DataFrame) -> FactorOutput:
    return calculate_per_symbol(frame, _calculate_one_symbol)


def _calculate_one_symbol(frame: pd.DataFrame) -> FactorOutput:
    output = FactorOutput(frame)
    close = numeric(frame, "close")
    open_price = numeric(frame, "open")
    high = numeric(frame, "high")
    low = numeric(frame, "low")
    pre_close, pre_columns, pre_source = previous_close(frame)

    for window in RETURN_WINDOWS:
        denominator = close.shift(window)
        values, zero = safe_divide(close, denominator)
        output.add(
            f"ret_{window}d", values - 1.0, min_history=window + 1,
            input_columns=("close",), zero_denominator=zero,
            provenance={"formula": "close / close.shift(window) - 1", "window": window},
        )

    ratio, zero = safe_divide(close, pre_close)
    output.add(
        "log_ret_1d", np.log(ratio), min_history=2,
        input_columns=("close", *pre_columns), zero_denominator=zero,
        invalid_domain=(close <= 0) | (pre_close <= 0),
        provenance={"formula": "ln(close / previous_close)", "previous_close": pre_source},
    )

    ratio, zero = safe_divide(open_price, pre_close)
    output.add(
        "gap_open_1d", ratio - 1.0, min_history=2,
        input_columns=("open", *pre_columns), zero_denominator=zero,
        provenance={"formula": "open / previous_close - 1", "previous_close": pre_source},
    )

    ratio, zero = safe_divide(close, open_price)
    output.add(
        "intraday_ret", ratio - 1.0, min_history=1,
        input_columns=("close", "open"), zero_denominator=zero,
        provenance={"formula": "close / open - 1"},
    )

    values, zero = safe_divide(high - low, pre_close)
    output.add(
        "intraday_range", values, min_history=1,
        input_columns=("high", "low", *pre_columns), zero_denominator=zero,
        provenance={"formula": "(high - low) / previous_close", "previous_close": pre_source},
    )

    daily_range = high - low
    values, zero = safe_divide((close - low) - (high - close), daily_range)
    output.add(
        "close_location_value", values, min_history=1,
        input_columns=("close", "high", "low"), zero_denominator=zero,
        provenance={"formula": "((close-low)-(high-close))/(high-low)"},
    )

    for window in (20, 60, 250):
        rolling_high = rolling_extreme(close, window, "max")
        values, zero = safe_divide(close, rolling_high)
        output.add(
            f"distance_{window}d_high", values - 1.0, min_history=window,
            input_columns=("close",), zero_denominator=zero,
            provenance={"formula": "close / rolling_max(close, window) - 1", "window": window},
        )

    for window in (20, 60):
        rolling_low = rolling_extreme(close, window, "min")
        values, zero = safe_divide(close, rolling_low)
        output.add(
            f"distance_{window}d_low", values - 1.0, min_history=window,
            input_columns=("close",), zero_denominator=zero,
            provenance={"formula": "close / rolling_min(close, window) - 1", "window": window},
        )
    return output
