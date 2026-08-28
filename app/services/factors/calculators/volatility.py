"""Causal implementations of the 20 volatility and market-risk factors."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

from app.services.factors.calculators.common import (
    FactorOutput,
    annual_trading_days,
    calculate_per_symbol,
    market_code,
    numeric,
    previous_close,
    safe_divide,
)


def calculate_volatility_factors(
    frame: pd.DataFrame,
    *,
    benchmark: pd.DataFrame | pd.Series | None = None,
    market_trading_days: Mapping[str, int] | None = None,
) -> FactorOutput:
    """Calculate risk factors after matching benchmark closes by trade date.

    A benchmark DataFrame must contain ``trade_date`` and either ``close`` or
    ``benchmark_close``.  If it has a ``market`` column, both market and date
    are used as keys.  A benchmark Series is keyed by its date-like index.
    Inline ``benchmark_close`` remains supported for normalized input frames.
    """
    aligned = _align_benchmark(frame, benchmark)
    return calculate_per_symbol(
        aligned,
        lambda group: _calculate_one_symbol(
            group, market_trading_days=market_trading_days
        ),
    )


def _calculate_one_symbol(
    frame: pd.DataFrame,
    *,
    market_trading_days: Mapping[str, int] | None,
) -> FactorOutput:
    output = FactorOutput(frame)
    close = numeric(frame, "close")
    annual_days = annual_trading_days(frame, market_trading_days)
    annual_scale = float(np.sqrt(annual_days))

    previous = close.shift(1)
    simple_return, return_zero = safe_divide(close, previous)
    simple_return = simple_return - 1.0
    valid_log_close = np.log(close.where(close > 0))
    log_return = valid_log_close.diff()

    for window in (5, 10, 20, 60, 120):
        values = log_return.rolling(window, min_periods=window).std(ddof=1) * annual_scale
        output.add(
            f"hist_vol_{window}", values, min_history=window + 1,
            input_columns=("close",), invalid_domain=close <= 0,
            provenance={
                "formula": "std(log(close).diff(), ddof=1) * sqrt(annual_trading_days)",
                "window": window, "annual_trading_days": annual_days,
            },
        )

    high = numeric(frame, "high")
    low = numeric(frame, "low")
    pre_close, pre_columns, pre_source = previous_close(frame)
    true_range = pd.concat(
        (high - low, (high - pre_close).abs(), (low - pre_close).abs()), axis=1
    ).max(axis=1, skipna=False)
    atr = _wilder_mean(true_range, 14)
    atr_pct, atr_close_zero = safe_divide(atr, close)
    output.add(
        "atr_14", atr, min_history=15,
        input_columns=("high", "low", "close", *pre_columns),
        provenance={
            "formula": "Wilder mean(max(high-low, abs(high-pre_close), abs(low-pre_close)))",
            "window": 14, "previous_close": pre_source,
        },
    )
    output.add(
        "atr_pct_14", atr_pct, min_history=15,
        input_columns=("high", "low", "close", *pre_columns),
        zero_denominator=atr_close_zero,
        provenance={"formula": "atr_14 / close", "unit": "decimal"},
    )

    downside_component = simple_return.clip(upper=0.0).pow(2)
    for window in (20, 60):
        values = (
            downside_component.rolling(window, min_periods=window).mean().pow(0.5)
            * annual_scale
        )
        output.add(
            f"downside_vol_{window}", values, min_history=window + 1,
            input_columns=("close",), zero_denominator=return_zero,
            provenance={
                "formula": "sqrt(mean(min(simple_return, 0)^2)) * sqrt(annual_trading_days)",
                "window": window, "annual_trading_days": annual_days,
                "target_return": 0.0,
            },
        )

    for window in (20, 60, 250):
        drawdown = close.rolling(window, min_periods=window).apply(
            _maximum_drawdown, raw=True
        )
        output.add(
            f"max_drawdown_{window}", drawdown, min_history=window + 1,
            input_columns=("close",), invalid_domain=close <= 0,
            provenance={
                "formula": "max(1 - normalized_wealth / running_peak)",
                "window": window, "sign": "positive_loss",
            },
        )

    benchmark_close = numeric(frame, "benchmark_close")
    benchmark_previous = benchmark_close.shift(1)
    benchmark_return, benchmark_zero = safe_divide(benchmark_close, benchmark_previous)
    benchmark_return = benchmark_return - 1.0
    for window in (60, 250):
        beta, benchmark_variance_zero, _, _, _ = _rolling_capm(
            simple_return, benchmark_return, window
        )
        output.add(
            f"beta_{window}", beta, min_history=window + 1,
            input_columns=("close", "benchmark_close"),
            zero_denominator=return_zero | benchmark_zero | benchmark_variance_zero,
            provenance={
                "formula": "cov(symbol_return, benchmark_return) / var(benchmark_return)",
                "window": window, "alignment": "market and trade_date",
            },
        )

    beta_60, variance_zero_60, symbol_mean_60, benchmark_mean_60, residual_var_60 = (
        _rolling_capm(simple_return, benchmark_return, 60)
    )
    alpha = (symbol_mean_60 - beta_60 * benchmark_mean_60) * annual_days
    output.add(
        "alpha_60", alpha, min_history=61,
        input_columns=("close", "benchmark_close"),
        zero_denominator=return_zero | benchmark_zero | variance_zero_60,
        provenance={
            "formula": "(mean(symbol_return) - beta_60 * mean(benchmark_return)) * annual_trading_days",
            "window": 60, "annual_trading_days": annual_days,
            "risk_free_rate": 0.0, "alignment": "market and trade_date",
        },
    )
    idiosyncratic = residual_var_60.clip(lower=0.0).pow(0.5) * annual_scale
    output.add(
        "idio_vol_60", idiosyncratic, min_history=61,
        input_columns=("close", "benchmark_close"),
        zero_denominator=return_zero | benchmark_zero | variance_zero_60,
        provenance={
            "formula": "sqrt(var(symbol_return - alpha_daily - beta*benchmark_return)) * sqrt(annual_trading_days)",
            "window": 60, "annual_trading_days": annual_days,
            "alignment": "market and trade_date",
        },
    )

    var_95 = simple_return.rolling(20, min_periods=20).quantile(0.05).mul(-1.0).clip(lower=0.0)
    output.add(
        "var_95_20", var_95, min_history=21,
        input_columns=("close",), zero_denominator=return_zero,
        provenance={
            "formula": "max(-quantile(simple_return, 0.05), 0)",
            "window": 20, "confidence": 0.95, "interpolation": "linear",
            "sign": "positive_loss",
        },
    )
    cvar_95 = simple_return.rolling(60, min_periods=60).apply(
        _historical_cvar_95, raw=True
    )
    output.add(
        "cvar_95_60", cvar_95, min_history=61,
        input_columns=("close",), zero_denominator=return_zero,
        provenance={
            "formula": "max(-mean(returns <= 5th percentile), 0)",
            "window": 60, "confidence": 0.95, "interpolation": "linear",
            "tail_inclusive": True, "sign": "positive_loss",
        },
    )

    output.add(
        "return_skew_60", simple_return.rolling(60, min_periods=60).skew(),
        min_history=61, input_columns=("close",), zero_denominator=return_zero,
        provenance={"formula": "adjusted sample skew(simple_return)", "window": 60},
    )
    output.add(
        "return_kurt_60", simple_return.rolling(60, min_periods=60).kurt(),
        min_history=61, input_columns=("close",), zero_denominator=return_zero,
        provenance={
            "formula": "unbiased Fisher excess kurtosis(simple_return)", "window": 60,
        },
    )
    return output


def _align_benchmark(
    frame: pd.DataFrame,
    benchmark: pd.DataFrame | pd.Series | None,
) -> pd.DataFrame:
    aligned = frame.copy()
    if benchmark is None:
        if "benchmark_trade_date" in aligned.columns and "trade_date" in aligned.columns:
            symbol_dates = pd.to_datetime(aligned["trade_date"], errors="raise").dt.normalize()
            benchmark_dates = pd.to_datetime(
                aligned["benchmark_trade_date"], errors="raise"
            ).dt.normalize()
            aligned["benchmark_close"] = numeric(aligned, "benchmark_close").where(
                symbol_dates.eq(benchmark_dates)
            )
        return aligned
    if "trade_date" not in aligned.columns:
        raise ValueError("trade_date is required for benchmark alignment")

    if isinstance(benchmark, pd.Series):
        benchmark_frame = pd.DataFrame(
            {"trade_date": benchmark.index, "benchmark_close": benchmark.to_numpy()}
        )
    elif isinstance(benchmark, pd.DataFrame):
        benchmark_frame = benchmark.copy()
        if "trade_date" not in benchmark_frame.columns:
            raise ValueError("benchmark DataFrame requires trade_date")
        if "benchmark_close" not in benchmark_frame.columns:
            if "close" not in benchmark_frame.columns:
                raise ValueError("benchmark DataFrame requires close or benchmark_close")
            benchmark_frame = benchmark_frame.rename(columns={"close": "benchmark_close"})
    else:
        raise TypeError("benchmark must be a DataFrame, Series, or None")

    benchmark_frame["__date"] = pd.to_datetime(
        benchmark_frame["trade_date"], errors="raise"
    ).dt.normalize()
    aligned_dates = pd.to_datetime(aligned["trade_date"], errors="raise").dt.normalize()
    use_market = "market" in aligned.columns and "market" in benchmark_frame.columns
    key_columns = ["__date"]
    if use_market:
        benchmark_frame["__market"] = benchmark_frame["market"].map(market_code)
        key_columns.insert(0, "__market")
    if benchmark_frame.duplicated(key_columns).any():
        raise ValueError("benchmark contains duplicate rows for an alignment key")

    if use_market:
        lookup = benchmark_frame.set_index(key_columns)["benchmark_close"]
        keys = pd.MultiIndex.from_arrays(
            [aligned["market"].map(market_code), aligned_dates],
            names=key_columns,
        )
        aligned["benchmark_close"] = lookup.reindex(keys).to_numpy()
    else:
        lookup = benchmark_frame.set_index("__date")["benchmark_close"]
        aligned["benchmark_close"] = lookup.reindex(aligned_dates).to_numpy()
    return aligned


def _rolling_capm(
    symbol_return: pd.Series,
    benchmark_return: pd.Series,
    window: int,
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series]:
    symbol_mean = symbol_return.rolling(window, min_periods=window).mean()
    benchmark_mean = benchmark_return.rolling(window, min_periods=window).mean()
    covariance = symbol_return.rolling(window, min_periods=window).cov(benchmark_return)
    symbol_variance = symbol_return.rolling(window, min_periods=window).var(ddof=1)
    benchmark_variance = benchmark_return.rolling(window, min_periods=window).var(ddof=1)
    beta, variance_zero = safe_divide(covariance, benchmark_variance)
    residual_variance = symbol_variance - beta * covariance
    return beta, variance_zero, symbol_mean, benchmark_mean, residual_variance


def _maximum_drawdown(sample: np.ndarray) -> float:
    if not np.isfinite(sample).all() or np.any(sample <= 0):
        return np.nan
    wealth = sample / sample[0]
    running_peak = np.maximum.accumulate(wealth)
    return float(np.max(1.0 - wealth / running_peak))


def _historical_cvar_95(sample: np.ndarray) -> float:
    if not np.isfinite(sample).all():
        return np.nan
    threshold = float(np.quantile(sample, 0.05))
    tail = sample[sample <= threshold]
    return max(-float(np.mean(tail)), 0.0)


def _wilder_mean(values: pd.Series, window: int) -> pd.Series:
    result = pd.Series(np.nan, index=values.index, dtype=float)
    valid = values.notna()
    segment_ids = values.isna().cumsum()
    for _, segment in values.loc[valid].groupby(segment_ids.loc[valid], sort=False):
        result.loc[segment.index] = segment.ewm(
            alpha=1.0 / window, adjust=False, min_periods=window
        ).mean()
    return result
