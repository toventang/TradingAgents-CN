"""Causal implementations of the 18 momentum and oscillator factors."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.services.factors.calculators.common import (
    FactorOutput,
    calculate_per_symbol,
    ema,
    numeric,
    previous_close,
    safe_divide,
    sma,
)


def calculate_momentum_factors(
    frame: pd.DataFrame,
    *,
    rsi_method: str = "wilder",
) -> FactorOutput:
    if rsi_method != "wilder":
        raise ValueError("unsupported RSI method; expected 'wilder'")
    return calculate_per_symbol(
        frame, lambda group: _calculate_one_symbol(group, rsi_method=rsi_method)
    )


def _calculate_one_symbol(frame: pd.DataFrame, *, rsi_method: str) -> FactorOutput:
    output = FactorOutput(frame)
    close = numeric(frame, "close")
    high = numeric(frame, "high")
    low = numeric(frame, "low")

    for window in (6, 12, 14, 24):
        values = _wilder_rsi(close, window)
        output.add(
            f"rsi_{window}", values, min_history=window + 1,
            input_columns=("close",),
            provenance={"formula": "Wilder RSI", "method": rsi_method, "window": window},
        )

    for window in (5, 10, 20, 60):
        denominator = close.shift(window)
        values, zero = safe_divide(close, denominator)
        output.add(
            f"roc_{window}", values - 1.0, min_history=window + 1,
            input_columns=("close",), zero_denominator=zero,
            provenance={"formula": "close / close.shift(window) - 1", "window": window, "unit": "decimal"},
        )

    k, d, j, kdj_zero = _kdj(high, low, close, window=9)
    for factor_id, values in (("kdj_k", k), ("kdj_d", d), ("kdj_j", j)):
        output.add(
            factor_id, values, min_history=9,
            input_columns=("high", "low", "close"), zero_denominator=kdj_zero,
            provenance={"formula": "classic recursive KDJ", "window": 9, "k_smoothing": 3, "d_smoothing": 3, "seed": 50.0},
        )

    typical_price = (high + low + close) / 3.0
    typical_mean = sma(typical_price, 14)
    mean_deviation = typical_price.rolling(14, min_periods=14).apply(
        lambda sample: float(np.mean(np.abs(sample - np.mean(sample)))), raw=True
    )
    cci, cci_zero = safe_divide(typical_price - typical_mean, 0.015 * mean_deviation)
    output.add(
        "cci_14", cci, min_history=14,
        input_columns=("high", "low", "close"), zero_denominator=cci_zero,
        provenance={"formula": "(typical_price-SMA14)/(0.015*mean_deviation14)", "window": 14},
    )

    highest = high.rolling(14, min_periods=14).max()
    lowest = low.rolling(14, min_periods=14).min()
    williams, williams_zero = safe_divide(-100.0 * (highest - close), highest - lowest)
    output.add(
        "williams_r_14", williams, min_history=14,
        input_columns=("high", "low", "close"), zero_denominator=williams_zero,
        provenance={"formula": "-100*(HH14-close)/(HH14-LL14)", "window": 14},
    )

    output.add(
        "momentum_10", close - close.shift(10), min_history=11,
        input_columns=("close",),
        provenance={"formula": "close - close.shift(10)", "window": 10},
    )

    ema_12 = ema(close, 12)
    ema_26 = ema(close, 26)
    ppo, ppo_zero = safe_divide(ema_12 - ema_26, ema_26)
    output.add(
        "ppo_12_26", ppo, min_history=26,
        input_columns=("close",), zero_denominator=ppo_zero,
        provenance={"formula": "(EMA12-EMA26)/EMA26", "fast": 12, "slow": 26, "unit": "decimal"},
    )

    ema_1 = ema(close, 15, min_periods=1)
    ema_2 = ema(ema_1, 15, min_periods=1)
    ema_3 = ema(ema_2, 15, min_periods=1)
    trix, trix_zero = safe_divide(ema_3, ema_3.shift(1))
    output.add(
        "trix_15", trix - 1.0, min_history=16,
        input_columns=("close",), zero_denominator=trix_zero,
        provenance={
            "formula": "one-day decimal return of triple EMA15",
            "window": 15, "unit": "decimal", "ema_seed": "first_observation",
        },
    )

    previous, previous_columns, previous_source = previous_close(frame)
    lower = pd.concat((low, previous), axis=1).min(axis=1, skipna=False)
    upper = pd.concat((high, previous), axis=1).max(axis=1, skipna=False)
    buying_pressure = close - lower
    true_range = upper - lower
    averages: dict[int, pd.Series] = {}
    zero_total = pd.Series(False, index=frame.index)
    for window in (7, 14, 28):
        average, zero = safe_divide(
            buying_pressure.rolling(window, min_periods=window).sum(),
            true_range.rolling(window, min_periods=window).sum(),
        )
        averages[window] = average
        zero_total |= zero
    ultimate = 100.0 * (4.0 * averages[7] + 2.0 * averages[14] + averages[28]) / 7.0
    output.add(
        "ultimate_osc_7_14_28", ultimate, min_history=28,
        input_columns=("high", "low", "close", *previous_columns),
        zero_denominator=zero_total,
        provenance={
            "formula": "100*(4*BP7/TR7+2*BP14/TR14+BP28/TR28)/7",
            "windows": (7, 14, 28), "previous_close": previous_source,
        },
    )

    window = 20
    displacement = window // 2 + 1
    dpo = close.shift(displacement) - sma(close, window)
    output.add(
        "dpo_20", dpo, min_history=20,
        input_columns=("close",),
        provenance={"formula": "close.shift(window//2+1) - SMA(window)", "window": window, "displacement": displacement},
    )
    return output


def _wilder_rsi(close: pd.Series, window: int) -> pd.Series:
    result = pd.Series(np.nan, index=close.index, dtype=float)
    delta = close.diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)
    average_gain: float | None = None
    average_loss: float | None = None
    contiguous: list[tuple[float, float]] = []

    for position in range(1, len(close)):
        gain = gains.iloc[position]
        loss = losses.iloc[position]
        if not np.isfinite(gain) or not np.isfinite(loss):
            contiguous.clear()
            average_gain = average_loss = None
            continue
        if average_gain is None or average_loss is None:
            contiguous.append((float(gain), float(loss)))
            if len(contiguous) < window:
                continue
            average_gain = float(np.mean([item[0] for item in contiguous[-window:]]))
            average_loss = float(np.mean([item[1] for item in contiguous[-window:]]))
        else:
            average_gain = (average_gain * (window - 1) + float(gain)) / window
            average_loss = (average_loss * (window - 1) + float(loss)) / window

        if average_gain == 0 and average_loss == 0:
            result.iloc[position] = 50.0
        elif average_loss == 0:
            result.iloc[position] = 100.0
        elif average_gain == 0:
            result.iloc[position] = 0.0
        else:
            relative_strength = average_gain / average_loss
            result.iloc[position] = 100.0 - 100.0 / (1.0 + relative_strength)
    return result


def _kdj(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    *,
    window: int,
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    lowest = low.rolling(window, min_periods=window).min()
    highest = high.rolling(window, min_periods=window).max()
    rsv, zero = safe_divide(100.0 * (close - lowest), highest - lowest)
    k = pd.Series(np.nan, index=close.index, dtype=float)
    d = pd.Series(np.nan, index=close.index, dtype=float)
    previous_k = previous_d = 50.0
    for position, value in enumerate(rsv):
        if not np.isfinite(value):
            previous_k = previous_d = 50.0
            continue
        previous_k = 2.0 / 3.0 * previous_k + 1.0 / 3.0 * float(value)
        previous_d = 2.0 / 3.0 * previous_d + 1.0 / 3.0 * previous_k
        k.iloc[position] = previous_k
        d.iloc[position] = previous_d
    return k, d, 3.0 * k - 2.0 * d, zero
