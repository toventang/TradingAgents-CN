"""Causal implementations of the 19 volume and liquidity factors."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.services.factors.calculators.common import (
    FactorOutput,
    SUSPENDED,
    calculate_per_symbol,
    numeric,
    safe_divide,
)


_AMOUNT_UNIT_MULTIPLIERS = {
    "base": 1.0,
    "currency": 1.0,
    "unit": 1.0,
    "cny": 1.0,
    "hkd": 1.0,
    "usd": 1.0,
    "yuan": 1.0,
    "dollar": 1.0,
    "cent": 0.01,
    "cents": 0.01,
    "thousand": 1_000.0,
    "thousands": 1_000.0,
    "k": 1_000.0,
    "ten_thousand": 10_000.0,
    "wan": 10_000.0,
    "万元": 10_000.0,
    "million": 1_000_000.0,
    "m": 1_000_000.0,
}


def calculate_liquidity_factors(
    frame: pd.DataFrame,
    *,
    amount_unit: str | float | None = None,
) -> FactorOutput:
    """Calculate liquidity factors using amount normalized to currency units.

    Unit precedence is: explicit ``amount_unit`` argument, positive per-row
    ``amount_unit_multiplier``, per-row ``amount_unit``, then canonical base
    currency units.  Suspended rows are unavailable and never count as genuine
    zero-volume trading days.
    """
    return calculate_per_symbol(
        frame,
        lambda group: _calculate_one_symbol(group, amount_unit=amount_unit),
    )


def _calculate_one_symbol(
    frame: pd.DataFrame,
    *,
    amount_unit: str | float | None,
) -> FactorOutput:
    output = FactorOutput(frame)
    suspended = _suspension_mask(frame)
    suspended_reason = {SUSPENDED: suspended}
    volume = numeric(frame, "volume")
    amount, amount_provenance = _normalized_amount(frame, amount_unit)
    close = numeric(frame, "close")
    high = numeric(frame, "high")
    low = numeric(frame, "low")

    tradable_volume = volume.mask(suspended)
    tradable_amount = amount.mask(suspended)
    tradable_close = close.mask(suspended)

    for window in (5, 20, 60):
        average = tradable_volume.rolling(window, min_periods=window).mean()
        ratio, zero = safe_divide(tradable_volume, average)
        output.add(
            f"volume_ratio_{window}", ratio, min_history=window,
            input_columns=("volume",), zero_denominator=zero,
            quality_reason_masks=suspended_reason,
            provenance={
                "formula": "volume / rolling_mean(volume, window)",
                "window": window, "suspended_volume": "excluded",
            },
        )

    for window in (5, 20):
        average = tradable_amount.rolling(window, min_periods=window).mean()
        ratio, zero = safe_divide(tradable_amount, average)
        output.add(
            f"amount_ratio_{window}", ratio, min_history=window,
            input_columns=("amount",), zero_denominator=zero,
            quality_reason_masks=suspended_reason,
            provenance={
                "formula": "amount / rolling_mean(amount, window)",
                "window": window, **amount_provenance,
            },
        )

    turnover = numeric(frame, "turnover_rate").mask(suspended)
    for factor_id, values, history, formula in (
        ("turnover_rate", turnover, 1, "normalized decimal turnover_rate"),
        ("turnover_mean_20", turnover.rolling(20, min_periods=20).mean(), 20,
         "rolling_mean(turnover_rate, 20)"),
        ("turnover_std_20", turnover.rolling(20, min_periods=20).std(ddof=1), 20,
         "rolling_std(turnover_rate, 20, ddof=1)"),
    ):
        output.add(
            factor_id, values, min_history=history,
            input_columns=("turnover_rate",), quality_reason_masks=suspended_reason,
            provenance={"formula": formula, "unit": "decimal"},
        )

    price_direction = np.sign(tradable_close.ffill().diff())
    if len(price_direction):
        price_direction.iloc[0] = 1.0
    obv_flow = price_direction.where(price_direction.ne(0), 0.0) * tradable_volume
    obv = obv_flow.cumsum()
    output.add(
        "obv", obv, min_history=1,
        input_columns=("close", "volume"), quality_reason_masks=suspended_reason,
        provenance={
            "formula": "cumsum(sign(close.diff()) * volume)",
            "seed": "first_volume", "unchanged_price_flow": 0.0,
            "suspended_volume": "excluded",
        },
    )
    obv_change, obv_zero = safe_divide(obv, obv.shift(20).abs())
    output.add(
        "obv_change_20", obv_change - 1.0, min_history=21,
        input_columns=("close", "volume"), zero_denominator=obv_zero,
        quality_reason_masks=suspended_reason,
        provenance={"formula": "OBV / abs(OBV.shift(20)) - 1", "window": 20},
    )

    typical_price = (high + low + close) / 3.0
    raw_money_flow = typical_price * tradable_volume
    typical_change = typical_price.diff()
    positive_flow = raw_money_flow.where(typical_change > 0, 0.0)
    negative_flow = raw_money_flow.where(typical_change < 0, 0.0)
    positive_sum = positive_flow.rolling(14, min_periods=14).sum()
    negative_sum = negative_flow.rolling(14, min_periods=14).sum()
    flow_ratio, negative_zero = safe_divide(positive_sum, negative_sum)
    mfi = 100.0 - 100.0 / (1.0 + flow_ratio)
    mfi = mfi.where(~(negative_zero & positive_sum.gt(0)), 100.0)
    mfi_zero = negative_zero & positive_sum.eq(0)
    output.add(
        "mfi_14", mfi, min_history=15,
        input_columns=("high", "low", "close", "volume"),
        zero_denominator=mfi_zero, quality_reason_masks=suspended_reason,
        provenance={
            "formula": "100 - 100/(1 + positive_money_flow_14/negative_money_flow_14)",
            "window": 14, "typical_price": "(high+low+close)/3",
        },
    )

    price_range = high - low
    money_flow_multiplier, range_zero = safe_divide(
        (close - low) - (high - close), price_range
    )
    money_flow_volume = money_flow_multiplier * tradable_volume
    volume_sum_20 = tradable_volume.rolling(20, min_periods=20).sum()
    cmf, cmf_volume_zero = safe_divide(
        money_flow_volume.rolling(20, min_periods=20).sum(), volume_sum_20
    )
    range_zero_20 = range_zero.rolling(20, min_periods=1).max().astype(bool)
    output.add(
        "cmf_20", cmf, min_history=20,
        input_columns=("high", "low", "close", "volume"),
        zero_denominator=range_zero_20 | cmf_volume_zero,
        quality_reason_masks=suspended_reason,
        provenance={
            "formula": "sum(money_flow_multiplier*volume,20)/sum(volume,20)",
            "window": 20,
        },
    )
    adl = money_flow_volume.cumsum()
    output.add(
        "adl_change_20", adl - adl.shift(20), min_history=21,
        input_columns=("high", "low", "close", "volume"),
        zero_denominator=range_zero_20, quality_reason_masks=suspended_reason,
        provenance={"formula": "ADL - ADL.shift(20)", "window": 20},
    )

    rolling_amount = tradable_amount.rolling(20, min_periods=20).sum()
    rolling_volume = tradable_volume.rolling(20, min_periods=20).sum()
    vwap, vwap_volume_zero = safe_divide(rolling_amount, rolling_volume)
    vwap_deviation, vwap_zero = safe_divide(tradable_close, vwap)
    output.add(
        "vwap_deviation_20", vwap_deviation - 1.0, min_history=20,
        input_columns=("close", "volume", "amount"),
        zero_denominator=vwap_volume_zero | vwap_zero,
        quality_reason_masks=suspended_reason,
        provenance={
            "formula": "close / (sum(normalized_amount,20)/sum(volume,20)) - 1",
            "window": 20, **amount_provenance,
        },
    )

    previous_close = tradable_close.shift(1)
    returns, close_zero = safe_divide(tradable_close, previous_close)
    returns = returns - 1.0
    previous_volume = tradable_volume.shift(1)
    volume_change, previous_volume_zero = safe_divide(tradable_volume, previous_volume)
    volume_change = volume_change - 1.0
    for window in (20, 60):
        correlation = returns.rolling(window, min_periods=window).corr(volume_change)
        return_zero_variance = returns.rolling(window, min_periods=window).std(ddof=1).eq(0)
        volume_zero_variance = volume_change.rolling(window, min_periods=window).std(ddof=1).eq(0)
        output.add(
            f"price_volume_corr_{window}", correlation, min_history=window + 1,
            input_columns=("close", "volume"),
            zero_denominator=(
                close_zero | previous_volume_zero | return_zero_variance | volume_zero_variance
            ),
            quality_reason_masks=suspended_reason,
            provenance={
                "formula": "corr(simple_return, volume_pct_change)",
                "window": window,
            },
        )
    output.add(
        "volume_volatility_20",
        volume_change.rolling(20, min_periods=20).std(ddof=1),
        min_history=21, input_columns=("volume",),
        zero_denominator=previous_volume_zero,
        quality_reason_masks=suspended_reason,
        provenance={
            "formula": "rolling_std(volume_pct_change, 20, ddof=1)", "window": 20,
        },
    )

    illiquidity_daily, amount_zero = safe_divide(returns.abs(), tradable_amount)
    invalid_amount = tradable_amount.lt(0)
    illiquidity_daily = illiquidity_daily.mask(invalid_amount)
    output.add(
        "amihud_illiq_20",
        illiquidity_daily.rolling(20, min_periods=20).mean(),
        min_history=21, input_columns=("close", "amount"),
        zero_denominator=close_zero | amount_zero, invalid_domain=invalid_amount,
        quality_reason_masks=suspended_reason,
        provenance={
            "formula": "mean(abs(simple_return)/normalized_amount, 20)",
            "window": 20, **amount_provenance,
        },
    )

    zero_volume = volume.eq(0) & volume.notna() & ~suspended
    eligible_volume_day = volume.notna() & ~suspended
    zero_count = zero_volume.astype(float).rolling(20, min_periods=20).sum()
    eligible_count = eligible_volume_day.astype(float).rolling(20, min_periods=20).sum()
    zero_ratio, no_eligible_days = safe_divide(zero_count, eligible_count)
    output.add(
        "zero_volume_days_20", zero_ratio, min_history=20,
        input_columns=("volume",), zero_denominator=no_eligible_days,
        quality_reason_masks=suspended_reason,
        provenance={
            "formula": "count(volume==0 and not suspended)/count(not suspended), 20 rows",
            "window": 20, "suspended_volume": "excluded",
        },
    )
    return output


def _normalized_amount(
    frame: pd.DataFrame,
    explicit_unit: str | float | None,
) -> tuple[pd.Series, dict[str, object]]:
    amount = numeric(frame, "amount")
    if explicit_unit is not None:
        multiplier = _amount_multiplier(explicit_unit)
        return amount * multiplier, {
            "amount_unit": str(explicit_unit),
            "amount_multiplier_to_currency_unit": multiplier,
        }
    if "amount_unit_multiplier" in frame.columns:
        multiplier = numeric(frame, "amount_unit_multiplier")
        if (multiplier.dropna() <= 0).any():
            raise ValueError("amount_unit_multiplier must be positive")
        return amount * multiplier, {
            "amount_unit": "per_row_multiplier",
            "amount_multiplier_to_currency_unit": "amount_unit_multiplier",
        }
    if "amount_unit" in frame.columns:
        multipliers = frame["amount_unit"].map(_amount_multiplier)
        return amount * multipliers, {
            "amount_unit": "per_row_amount_unit",
            "amount_multiplier_to_currency_unit": "mapped_per_row",
        }
    return amount, {
        "amount_unit": "canonical_currency_unit",
        "amount_multiplier_to_currency_unit": 1.0,
    }


def _amount_multiplier(unit: str | float) -> float:
    if isinstance(unit, (int, float)) and not isinstance(unit, bool):
        multiplier = float(unit)
        if not np.isfinite(multiplier) or multiplier <= 0:
            raise ValueError("amount unit multiplier must be finite and positive")
        return multiplier
    key = str(unit).strip().lower()
    try:
        return _AMOUNT_UNIT_MULTIPLIERS[key]
    except KeyError as exc:
        raise ValueError(f"unsupported amount unit: {unit}") from exc


def _suspension_mask(frame: pd.DataFrame) -> pd.Series:
    if "suspended" not in frame.columns:
        return pd.Series(False, index=frame.index)
    values = frame["suspended"]
    if pd.api.types.is_bool_dtype(values.dtype):
        return values.fillna(False).astype(bool)
    truthy = {"1", "true", "yes", "y", "suspended", "停牌"}
    falsey = {"0", "false", "no", "n", "trading", "交易", ""}
    normalized = values.fillna(False).astype(str).str.strip().str.lower()
    unknown = ~normalized.isin(truthy | falsey)
    if unknown.any():
        raise ValueError("suspended contains an unsupported value")
    return normalized.isin(truthy)
