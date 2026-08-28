"""Causal market-event factors using explicit date-versioned trading rules."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from app.services.factors.calculators.common import (
    FactorOutput,
    calculate_per_symbol,
    numeric,
    previous_close,
    safe_divide,
)


def calculate_event_factors(
    frame: pd.DataFrame,
    *,
    price_limit_rules: pd.DataFrame | None = None,
) -> FactorOutput:
    """Calculate four event factors after resolving market/board/date rules."""
    prepared = _attach_limit_prices(frame, price_limit_rules)
    return calculate_per_symbol(prepared, _calculate_one_symbol)


def _calculate_one_symbol(frame: pd.DataFrame) -> FactorOutput:
    output = FactorOutput(frame)
    close = numeric(frame, "close")
    open_price = numeric(frame, "open")
    pre_close, pre_columns, pre_source = previous_close(frame)
    limit_up_price = numeric(frame, "__limit_up_price")
    limit_down_price = numeric(frame, "__limit_down_price")

    up_event = _at_price(close, limit_up_price).where(
        close.notna() & limit_up_price.notna()
    ).astype(float)
    down_event = _at_price(close, limit_down_price).where(
        close.notna() & limit_down_price.notna()
    ).astype(float)
    output.add(
        "limit_up_count_20", up_event.rolling(20, min_periods=20).sum(),
        min_history=20, input_columns=("close", "__limit_up_price"),
        provenance={
            "formula": "count(close matches date_specific_limit_up_price, 20)",
            "rule_alignment": "market, board, trade_date",
        },
    )
    output.add(
        "limit_down_count_20", down_event.rolling(20, min_periods=20).sum(),
        min_history=20, input_columns=("close", "__limit_down_price"),
        provenance={
            "formula": "count(close matches date_specific_limit_down_price, 20)",
            "rule_alignment": "market, board, trade_date",
        },
    )

    close_return, close_zero = safe_divide(close, pre_close)
    close_return = close_return - 1.0
    historical_volatility = (
        close_return.rolling(20, min_periods=20).std(ddof=1).shift(1)
    )
    gap, gap_zero = safe_divide(open_price, pre_close)
    gap = gap - 1.0
    gap_event = gap.abs().gt(2.0 * historical_volatility).where(
        gap.notna() & historical_volatility.notna()
    ).astype(float)
    output.add(
        "gap_event_20", gap_event.rolling(20, min_periods=20).sum(),
        min_history=41, input_columns=("open", "close", *pre_columns),
        zero_denominator=close_zero | gap_zero,
        provenance={
            "formula": "count(abs(open/pre_close-1) > 2*prior_20d_return_std, 20)",
            "event_window": 20, "volatility_window": 20,
            "volatility_lag": 1, "previous_close": pre_source,
        },
    )

    suspended = _suspension_mask(frame)
    output.add(
        "suspension_days_20",
        suspended.astype(float).rolling(20, min_periods=20).sum(),
        min_history=20, input_columns=("suspended",),
        provenance={
            "formula": "count(suspended is true, 20)", "window": 20,
            "zero_volume_is_not_suspension": True,
        },
    )
    if set(output) != {
        "limit_up_count_20", "limit_down_count_20", "gap_event_20",
        "suspension_days_20",
    }:
        raise AssertionError("event output does not match V1 registry")
    return output


def _attach_limit_prices(
    frame: pd.DataFrame, rules: pd.DataFrame | None
) -> pd.DataFrame:
    prepared = frame.copy()
    if {"limit_up_price", "limit_down_price"}.issubset(prepared.columns):
        prepared["__limit_up_price"] = numeric(prepared, "limit_up_price")
        prepared["__limit_down_price"] = numeric(prepared, "limit_down_price")
        return prepared
    if rules is None:
        prepared["__limit_up_price"] = np.nan
        prepared["__limit_down_price"] = np.nan
        return prepared
    required_frame = {"market", "board", "trade_date", "pre_close"}
    if missing := required_frame - set(prepared.columns):
        raise ValueError(f"price-limit calculation missing frame columns: {sorted(missing)}")
    if not isinstance(rules, pd.DataFrame):
        raise TypeError("price_limit_rules must be a pandas DataFrame")
    required_rules = {"market", "board", "effective_from", "up_limit", "down_limit"}
    if missing := required_rules - set(rules.columns):
        raise ValueError(f"price_limit_rules missing columns: {sorted(missing)}")

    normalized = rules.copy()
    normalized["market"] = normalized["market"].map(_market_code)
    normalized["board"] = normalized["board"].astype(str)
    normalized["effective_from"] = pd.to_datetime(
        normalized["effective_from"], errors="raise"
    ).dt.normalize()
    if "effective_to" in normalized.columns:
        original_effective_to = normalized["effective_to"]
        parsed_effective_to = pd.to_datetime(original_effective_to, errors="coerce")
        if (original_effective_to.notna() & parsed_effective_to.isna()).any():
            raise ValueError("price_limit_rules contains an invalid effective_to")
        normalized["effective_to"] = parsed_effective_to.dt.normalize()
    else:
        normalized["effective_to"] = pd.NaT
    for column in ("up_limit", "down_limit"):
        normalized[column] = pd.to_numeric(normalized[column], errors="raise").astype(float)
        if ((normalized[column] <= 0) | (normalized[column] >= 1)).any():
            raise ValueError("price-limit percentages must be decimals between 0 and 1")
    invalid_range = (
        normalized["effective_to"].notna()
        & normalized["effective_from"].gt(normalized["effective_to"])
    )
    if invalid_range.any():
        raise ValueError("price-limit effective_from cannot be after effective_to")
    if "tick_size" not in normalized.columns:
        normalized["tick_size"] = np.nan
    else:
        original_tick = normalized["tick_size"]
        normalized["tick_size"] = pd.to_numeric(original_tick, errors="coerce")
        if (original_tick.notna() & normalized["tick_size"].isna()).any():
            raise ValueError("price_limit_rules contains an invalid tick_size")

    up_prices = pd.Series(np.nan, index=prepared.index, dtype=float)
    down_prices = pd.Series(np.nan, index=prepared.index, dtype=float)
    dates = pd.to_datetime(prepared["trade_date"], errors="raise").dt.normalize()
    previous = numeric(prepared, "pre_close")
    for index in prepared.index:
        market = _market_code(prepared.at[index, "market"])
        board = str(prepared.at[index, "board"])
        date = dates.loc[index]
        matches = normalized.loc[
            normalized["market"].eq(market)
            & normalized["board"].isin((board, "*"))
            & normalized["effective_from"].le(date)
            & (normalized["effective_to"].isna() | normalized["effective_to"].ge(date))
        ]
        exact = matches.loc[matches["board"].eq(board)]
        if not exact.empty:
            matches = exact
        if len(matches) > 1:
            raise ValueError("overlapping price-limit rules for market/board/date")
        if matches.empty or not np.isfinite(previous.loc[index]):
            continue
        rule = matches.iloc[0]
        up = previous.loc[index] * (1.0 + rule["up_limit"])
        down = previous.loc[index] * (1.0 - rule["down_limit"])
        tick = _finite(rule["tick_size"])
        if tick is not None:
            if tick <= 0:
                raise ValueError("tick_size must be positive")
            up = _round_to_tick(up, tick)
            down = _round_to_tick(down, tick)
        up_prices.loc[index] = up
        down_prices.loc[index] = down
    prepared["__limit_up_price"] = up_prices
    prepared["__limit_down_price"] = down_prices
    return prepared


def _suspension_mask(frame: pd.DataFrame) -> pd.Series:
    if "suspended" not in frame.columns:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    values = frame["suspended"]
    if pd.api.types.is_bool_dtype(values.dtype):
        return values.astype("boolean")
    normalized = values.astype(str).str.strip().str.lower()
    mapping: dict[str, Any] = {
        "true": True, "1": True, "yes": True, "suspended": True, "停牌": True,
        "false": False, "0": False, "no": False, "trading": False, "交易": False,
    }
    converted = normalized.map(mapping)
    converted.loc[values.isna()] = pd.NA
    if converted.isna().any() and not values.loc[converted.isna()].isna().all():
        raise ValueError("suspended contains an unsupported value")
    return converted.astype("boolean")


def _market_code(value: Any) -> str:
    return str(getattr(value, "value", value)).strip().upper().rsplit(".", 1)[-1]


def _round_to_tick(value: float, tick: float) -> float:
    return float(np.floor(value / tick + 0.5 + 1e-12) * tick)


def _at_price(values: pd.Series, target: pd.Series) -> pd.Series:
    tolerance = np.maximum(target.abs() * 1e-10, 1e-8)
    return (values - target).abs().le(tolerance)


def _finite(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if np.isfinite(numeric) else None
