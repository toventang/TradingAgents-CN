"""Causal implementations of the 23 trend factors."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.services.factors.calculators.common import (
    FactorOutput,
    annual_trading_days,
    calculate_per_symbol,
    ema,
    numeric,
    previous_close,
    rolling_regression,
    safe_divide,
    sma,
)


def calculate_trend_factors(frame: pd.DataFrame) -> FactorOutput:
    return calculate_per_symbol(frame, _calculate_one_symbol)


def _calculate_one_symbol(frame: pd.DataFrame) -> FactorOutput:
    output = FactorOutput(frame)
    close = numeric(frame, "close")
    high = numeric(frame, "high")
    low = numeric(frame, "low")

    moving_averages: dict[int, pd.Series] = {}
    for window in (5, 10, 20, 60, 120, 250):
        average = moving_averages[window] = sma(close, window)
        values, zero = safe_divide(close, average)
        output.add(
            f"ma_ratio_{window}", values - 1.0, min_history=window,
            input_columns=("close",), zero_denominator=zero,
            provenance={"formula": "close / SMA(close, window) - 1", "window": window},
        )

    for window in (5, 10, 20, 60):
        average = ema(close, window)
        values, zero = safe_divide(close, average)
        output.add(
            f"ema_ratio_{window}", values - 1.0, min_history=window,
            input_columns=("close",), zero_denominator=zero,
            provenance={"formula": "close / EMA(close, span=window) - 1", "window": window, "adjust": False},
        )

    for short, long in ((5, 20), (10, 60), (20, 60), (60, 250)):
        values, zero = safe_divide(moving_averages[short], moving_averages[long])
        output.add(
            f"ma_cross_{short}_{long}", values - 1.0, min_history=long,
            input_columns=("close",), zero_denominator=zero,
            provenance={"formula": "SMA(short) / SMA(long) - 1", "short": short, "long": long},
        )

    ema_12 = ema(close, 12)
    ema_26 = ema(close, 26)
    dif = ema_12 - ema_26
    dea = ema(dif, 9)
    histogram = dif - dea
    output.add(
        "macd_dif", dif, min_history=26, input_columns=("close",),
        provenance={"formula": "EMA12 - EMA26", "fast": 12, "slow": 26, "adjust": False},
    )
    output.add(
        "macd_dea", dea, min_history=34, input_columns=("close",),
        provenance={"formula": "EMA(macd_dif, 9)", "signal": 9, "adjust": False},
    )
    output.add(
        "macd_hist", histogram, min_history=34, input_columns=("close",),
        provenance={"formula": "macd_dif - macd_dea", "hist_multiplier": 1},
    )

    adx, adx_zero, pre_columns, pre_source = _adx(high, low, close, frame, 14)
    output.add(
        "adx_14", adx, min_history=27,
        input_columns=("high", "low", "close", *pre_columns),
        zero_denominator=adx_zero,
        provenance={"formula": "Wilder ADX", "window": 14, "previous_close": pre_source},
    )

    for factor_id, values, source in (
        ("aroon_up_25", _aroon(high, 25, "max"), "high"),
        ("aroon_down_25", _aroon(low, 25, "min"), "low"),
    ):
        output.add(
            factor_id, values, min_history=25, input_columns=(source,),
            provenance={"formula": "100 * normalized recency of rolling extreme", "window": 25, "ties": "most_recent"},
        )

    log_close = np.log(close.where(close > 0))
    annualization = annual_trading_days(frame)
    slopes: dict[int, pd.Series] = {}
    r_squared_60: pd.Series | None = None
    for window in (20, 60):
        slope, r_squared = rolling_regression(log_close, window)
        slopes[window] = slope
        if window == 60:
            r_squared_60 = r_squared
        output.add(
            f"linear_slope_{window}", slope * annualization, min_history=window,
            input_columns=("close",), invalid_domain=close <= 0,
            provenance={
                "formula": "OLS slope(ln(close), 0..window-1) * annual_trading_days",
                "window": window, "annual_trading_days": annualization,
            },
        )
    assert r_squared_60 is not None
    zero_variance = log_close.rolling(60, min_periods=60).var(ddof=0).eq(0)
    output.add(
        "trend_r2_60", r_squared_60, min_history=60,
        input_columns=("close",), zero_denominator=zero_variance,
        invalid_domain=close <= 0,
        provenance={"formula": "R-squared of OLS ln(close) on 0..59", "window": 60},
    )
    return output


def _adx(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    frame: pd.DataFrame,
    window: int,
) -> tuple[pd.Series, pd.Series, tuple[str, ...], str]:
    pre_close, pre_columns, pre_source = previous_close(frame)
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    true_range = pd.concat(
        ((high - low), (high - pre_close).abs(), (low - pre_close).abs()), axis=1
    ).max(axis=1, skipna=True)
    atr = true_range.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    plus_smoothed = plus_dm.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    minus_smoothed = minus_dm.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    plus_di, atr_zero = safe_divide(100.0 * plus_smoothed, atr)
    minus_di, _ = safe_divide(100.0 * minus_smoothed, atr)
    directional_sum = plus_di + minus_di
    dx, directional_zero = safe_divide(100.0 * (plus_di - minus_di).abs(), directional_sum)
    adx = dx.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    return adx, atr_zero | directional_zero, pre_columns, pre_source


def _aroon(values: pd.Series, window: int, kind: str) -> pd.Series:
    def recency(sample: np.ndarray) -> float:
        if not np.isfinite(sample).all():
            return np.nan
        extreme = np.max(sample) if kind == "max" else np.min(sample)
        most_recent = np.flatnonzero(sample == extreme)[-1]
        return float(most_recent / (window - 1) * 100.0)

    return values.rolling(window, min_periods=window).apply(recency, raw=True)
