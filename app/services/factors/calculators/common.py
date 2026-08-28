"""Shared deterministic helpers for causal time-series factor calculations."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

import numpy as np
import pandas as pd


INSUFFICIENT_HISTORY = "insufficient_history"
MISSING_INPUT = "missing_input"
NON_FINITE_INPUT = "non_finite_input"
NON_FINITE_OUTPUT = "non_finite_output"
ZERO_DENOMINATOR = "zero_denominator"
INVALID_DOMAIN = "invalid_domain"
MISSING_VALUE = "missing_value"


class FactorOutput(dict[str, pd.Series]):
    """Dictionary-compatible factor values with deterministic diagnostics."""

    def __init__(self, frame: pd.DataFrame):
        super().__init__()
        self._frame = frame
        self.quality_reasons: dict[str, pd.Series] = {}
        self.provenance: dict[str, dict[str, Any]] = {}

    def add(
        self,
        factor_id: str,
        values: pd.Series | Iterable[float],
        *,
        min_history: int,
        input_columns: Iterable[str] = (),
        zero_denominator: pd.Series | None = None,
        invalid_domain: pd.Series | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> None:
        if min_history < 1:
            raise ValueError("min_history must be positive")
        raw = to_series(values, self._frame.index)
        numeric_values = pd.to_numeric(raw, errors="coerce").astype(float)
        generated_non_finite = pd.Series(
            np.isinf(numeric_values.to_numpy()), index=self._frame.index
        )
        numeric_values = numeric_values.mask(generated_non_finite)

        missing_input, non_finite_input = input_issue_masks(self._frame, input_columns)
        numeric_values = numeric_values.mask(missing_input | non_finite_input)
        position = pd.Series(np.arange(len(self._frame)), index=self._frame.index)
        insufficient = position < min_history - 1
        numeric_values = numeric_values.mask(insufficient)

        reasons = pd.Series(pd.NA, index=self._frame.index, dtype="object")
        reasons.loc[missing_input] = MISSING_INPUT
        if zero_denominator is not None:
            zero_mask = to_series(zero_denominator, self._frame.index).fillna(False).astype(bool)
            numeric_values = numeric_values.mask(zero_mask)
            reasons.loc[zero_mask] = ZERO_DENOMINATOR
        if invalid_domain is not None:
            invalid_mask = to_series(invalid_domain, self._frame.index).fillna(False).astype(bool)
            numeric_values = numeric_values.mask(invalid_mask)
            reasons.loc[invalid_mask] = INVALID_DOMAIN
        reasons.loc[insufficient] = INSUFFICIENT_HISTORY
        reasons.loc[non_finite_input] = NON_FINITE_INPUT
        reasons.loc[generated_non_finite] = NON_FINITE_OUTPUT
        unexplained = numeric_values.isna() & reasons.isna()
        reasons.loc[unexplained] = MISSING_VALUE

        numeric_values.name = factor_id
        reasons.name = factor_id
        self[factor_id] = numeric_values
        self.quality_reasons[factor_id] = reasons
        self.provenance[factor_id] = dict(provenance or {})


def calculate_per_symbol(
    frame: pd.DataFrame,
    calculator: Callable[[pd.DataFrame], FactorOutput],
) -> FactorOutput:
    """Sort each canonical symbol causally, then restore the original index."""
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("factor input must be a pandas DataFrame")
    if not frame.index.is_unique:
        raise ValueError("factor input index must be unique")
    if frame.empty:
        return calculator(frame.copy())

    group_columns = [name for name in ("market", "symbol") if name in frame.columns]
    if "symbol" not in frame.columns:
        group_columns = []
    grouper: str | list[str] = group_columns[0] if len(group_columns) == 1 else group_columns
    groups = [(None, frame)] if not group_columns else frame.groupby(
        grouper, sort=False, dropna=False
    )

    partials: list[tuple[Any, FactorOutput]] = []
    for group_key, group in groups:
        ordered = _order_group(group)
        partials.append((group_key, calculator(ordered)))

    result = FactorOutput(frame)
    factor_ids = tuple(partials[0][1].keys())
    for _, partial in partials[1:]:
        if tuple(partial.keys()) != factor_ids:
            raise ValueError("per-symbol calculators returned inconsistent factor sets")
    for factor_id in factor_ids:
        values = pd.concat([partial[factor_id] for _, partial in partials]).reindex(frame.index)
        reasons = pd.concat([
            partial.quality_reasons[factor_id] for _, partial in partials
        ]).reindex(frame.index)
        result[factor_id] = values
        result.quality_reasons[factor_id] = reasons
        provenance = [partial.provenance[factor_id] for _, partial in partials]
        if all(item == provenance[0] for item in provenance[1:]):
            result.provenance[factor_id] = dict(provenance[0])
        else:
            result.provenance[factor_id] = {
                "by_group": {
                    str(group_key): dict(partial.provenance[factor_id])
                    for group_key, partial in partials
                }
            }
    return result


def _order_group(group: pd.DataFrame) -> pd.DataFrame:
    if "trade_date" in group.columns:
        dates = pd.to_datetime(group["trade_date"], errors="raise")
        if dates.duplicated().any():
            raise ValueError("duplicate trade_date within one symbol")
        return group.assign(__factor_trade_date=dates).sort_values(
            "__factor_trade_date", kind="mergesort"
        ).drop(columns="__factor_trade_date")
    try:
        return group.sort_index(kind="mergesort")
    except TypeError as exc:
        raise ValueError("input requires trade_date when its index is not sortable") from exc


def numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(np.nan, index=frame.index, dtype=float, name=column)
    values = pd.to_numeric(frame[column], errors="coerce").astype(float)
    return values.mask(np.isinf(values))


def previous_close(frame: pd.DataFrame) -> tuple[pd.Series, tuple[str, ...], str]:
    if "pre_close" in frame.columns:
        return numeric(frame, "pre_close"), ("pre_close",), "pre_close"
    return numeric(frame, "close").shift(1), ("close",), "close.shift(1)"


def input_issue_masks(
    frame: pd.DataFrame, columns: Iterable[str]
) -> tuple[pd.Series, pd.Series]:
    missing = pd.Series(False, index=frame.index)
    non_finite = pd.Series(False, index=frame.index)
    for column in columns:
        if column not in frame.columns:
            missing[:] = True
            continue
        converted = pd.to_numeric(frame[column], errors="coerce")
        raw_missing = frame[column].isna() | converted.isna()
        missing |= raw_missing
        non_finite |= pd.Series(
            np.isinf(converted.astype(float).to_numpy()), index=frame.index
        )
    return missing, non_finite


def to_series(values: pd.Series | Iterable[Any], index: pd.Index | None = None) -> pd.Series:
    if isinstance(values, pd.Series):
        result = values.copy()
        if index is not None and not result.index.equals(index):
            result = result.reindex(index)
        return result
    return pd.Series(values, index=index, dtype=float)


def safe_divide(
    numerator: pd.Series,
    denominator: pd.Series,
) -> tuple[pd.Series, pd.Series]:
    denominator = denominator.astype(float)
    zero = denominator.eq(0) & denominator.notna()
    return numerator.astype(float) / denominator.mask(zero), zero


def sma(values: pd.Series, window: int) -> pd.Series:
    return values.rolling(window=window, min_periods=window).mean()


def ema(values: pd.Series, span: int, *, min_periods: int | None = None) -> pd.Series:
    required = span if min_periods is None else min_periods
    if required < 1:
        raise ValueError("EMA min_periods must be positive")
    result = pd.Series(np.nan, index=values.index, dtype=float)
    valid = values.notna()
    segment_ids = values.isna().cumsum()
    for _, segment in values.loc[valid].groupby(segment_ids.loc[valid], sort=False):
        result.loc[segment.index] = segment.ewm(
            span=span, adjust=False, min_periods=required
        ).mean()
    return result


def rolling_extreme(values: pd.Series, window: int, kind: str) -> pd.Series:
    rolling = values.rolling(window=window, min_periods=window)
    if kind == "max":
        return rolling.max()
    if kind == "min":
        return rolling.min()
    raise ValueError("kind must be max or min")


def rolling_regression(values: pd.Series, window: int) -> tuple[pd.Series, pd.Series]:
    """Return causal OLS slope and R-squared against 0..window-1."""
    x = np.arange(window, dtype=float)
    x_centered = x - x.mean()
    x_ss = float(np.dot(x_centered, x_centered))

    def slope(sample: np.ndarray) -> float:
        if not np.isfinite(sample).all():
            return np.nan
        centered = sample - sample.mean()
        return float(np.dot(x_centered, centered) / x_ss)

    def r_squared(sample: np.ndarray) -> float:
        if not np.isfinite(sample).all():
            return np.nan
        centered = sample - sample.mean()
        y_ss = float(np.dot(centered, centered))
        if y_ss == 0:
            return np.nan
        covariance = float(np.dot(x_centered, centered))
        return covariance * covariance / (x_ss * y_ss)

    rolling = values.rolling(window=window, min_periods=window)
    return rolling.apply(slope, raw=True), rolling.apply(r_squared, raw=True)


def annual_trading_days(frame: pd.DataFrame) -> int:
    if "market" not in frame.columns:
        return 252
    markets = frame["market"].dropna().astype(str).str.upper().unique()
    if len(markets) == 0:
        return 252
    if len(markets) != 1:
        raise ValueError("each calculation group must contain exactly one market")
    try:
        return {"CN": 244, "HK": 250, "US": 252}[markets[0]]
    except KeyError as exc:
        raise ValueError(f"unsupported market: {markets[0]}") from exc


def adapt_macd_hist_for_legacy_ui(values: pd.Series) -> pd.Series:
    """Return the historical UI's doubled histogram without changing factor data."""
    adapted = values * 2.0
    adapted.name = values.name
    return adapted
