"""Fixed-universe ranks and auditable base composite factor calculations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd


MIN_CROSS_SECTION_SIZE = 20
INSUFFICIENT_CROSS_SECTION = "insufficient_cross_section"
MISSING_DEFINITION = "missing_definition"
MISSING_COMPONENT = "missing_component"
ZERO_DISPERSION = "zero_dispersion"


FIXED_COMPOSITE_WEIGHTS: dict[str, dict[str, float]] = {
    "value_composite": {
        "earnings_yield": 1.0 / 3.0,
        "book_to_price": 1.0 / 3.0,
        "sales_to_price": 1.0 / 3.0,
    },
    "quality_composite": {
        "roe_ttm": 0.2,
        "roic_ttm": 0.2,
        "cfo_to_net_income": 0.2,
        "accruals_ratio": -0.2,
        "debt_to_assets": -0.2,
    },
    "growth_composite": {
        "revenue_yoy": 0.25,
        "net_profit_yoy": 0.25,
        "eps_yoy": 0.25,
        "cfo_yoy": 0.25,
    },
    "momentum_composite": {
        "ret_20d": 1.0 / 3.0,
        "ret_60d": 1.0 / 3.0,
        "ret_120d": 1.0 / 3.0,
        "ret_1d": -1.0,
    },
    "low_vol_composite": {
        "hist_vol_20": -0.25,
        "downside_vol_20": -0.25,
        "beta_60": -0.25,
        "max_drawdown_60": -0.25,
    },
    "liquidity_composite": {
        "turnover_mean_20": 1.0 / 3.0,
        "amount_ratio_20": 1.0 / 3.0,
        "amihud_illiq_20": -1.0 / 3.0,
    },
    "sentiment_composite": {
        "news_sentiment_7d": 1.0 / 3.0,
        "social_sentiment_7d": 1.0 / 3.0,
        "news_volume_zscore_7d": 1.0 / 3.0,
    },
}


class CrossSectionOutput(dict[str, pd.Series]):
    def __init__(self, frame: pd.DataFrame, universe_snapshot_id: str):
        super().__init__()
        self.frame = frame
        self.universe_snapshot_id = universe_snapshot_id
        self.quality_reasons: dict[str, pd.Series] = {}
        self.provenance: dict[str, dict[str, Any]] = {}
        self.contributions: dict[str, pd.DataFrame] = {}

    def add(
        self,
        factor_id: str,
        values: pd.Series,
        *,
        reasons: pd.Series,
        provenance: Mapping[str, Any],
        contributions: pd.DataFrame | None = None,
    ) -> None:
        result = pd.to_numeric(values.reindex(self.frame.index), errors="coerce").astype(float)
        result = result.mask(np.isinf(result))
        result.name = factor_id
        quality = reasons.reindex(self.frame.index).astype("object")
        quality.loc[result.notna()] = pd.NA
        quality.loc[result.isna() & quality.isna()] = MISSING_COMPONENT
        quality.name = factor_id
        self[factor_id] = result
        self.quality_reasons[factor_id] = quality
        self.provenance[factor_id] = {
            "universe_snapshot_id": self.universe_snapshot_id,
            **dict(provenance),
        }
        if contributions is not None:
            self.contributions[factor_id] = contributions.reindex(self.frame.index)


def calculate_cross_section_factors(
    frame: pd.DataFrame,
    *,
    multi_factor_weights: Mapping[str, float] | None = None,
) -> CrossSectionOutput:
    """Calculate ten cross-sectional outputs within one immutable universe."""
    universe_snapshot_id = _validate_universe(frame)
    output = CrossSectionOutput(frame, universe_snapshot_id)
    market_groups = ["market"] if "market" in frame.columns else []

    industry_groups = [name for name in ("market", "industry") if name in frame.columns]
    if "industry" not in frame.columns:
        industry_rank = pd.Series(np.nan, index=frame.index)
        industry_reason = pd.Series(MISSING_COMPONENT, index=frame.index, dtype="object")
    else:
        industry_rank, industry_reason = _percentile_rank(
            frame, "ret_20d", industry_groups
        )
    output.add(
        "industry_momentum_rank_20", industry_rank,
        reasons=industry_reason,
        provenance={
            "formula": "percentile_rank(ret_20d) within market and industry",
            "minimum_valid_symbols": MIN_CROSS_SECTION_SIZE,
        },
    )

    market_rank, market_reason = _percentile_rank(frame, "ret_20d", market_groups)
    output.add(
        "market_momentum_rank_20", market_rank,
        reasons=market_reason,
        provenance={
            "formula": "percentile_rank(ret_20d) within market",
            "minimum_valid_symbols": MIN_CROSS_SECTION_SIZE,
        },
    )

    for factor_id, weights in FIXED_COMPOSITE_WEIGHTS.items():
        score, reasons, contributions = _composite(
            frame, weights, market_groups=market_groups
        )
        output.add(
            factor_id, score, reasons=reasons, contributions=contributions,
            provenance={
                "formula": "sum(explicit_weight * robust_zscore(component))",
                "weights": dict(weights),
                "normalization": "median_and_1.4826_mad",
                "minimum_valid_symbols": MIN_CROSS_SECTION_SIZE,
                "missing_policy": "require_all_components",
            },
        )

    if multi_factor_weights is None:
        missing = pd.Series(np.nan, index=frame.index)
        reasons = pd.Series(MISSING_DEFINITION, index=frame.index, dtype="object")
        output.add(
            "multi_factor_score", missing, reasons=reasons,
            contributions=pd.DataFrame(index=frame.index),
            provenance={
                "formula": "explicit structured factor weights required",
                "weights": None,
            },
        )
    else:
        weights = _validate_weights(multi_factor_weights)
        component_frame = frame.copy()
        for factor_id, values in output.items():
            component_frame[factor_id] = values
        unknown = set(weights) - set(component_frame.columns)
        if unknown:
            raise ValueError(f"unknown multi-factor components: {sorted(unknown)}")
        score, reasons, contributions = _composite(
            component_frame, weights, market_groups=market_groups
        )
        output.add(
            "multi_factor_score", score, reasons=reasons,
            contributions=contributions,
            provenance={
                "formula": "sum(explicit_weight * robust_zscore(component))",
                "weights": dict(weights),
                "normalization": "median_and_1.4826_mad",
                "minimum_valid_symbols": MIN_CROSS_SECTION_SIZE,
                "missing_policy": "require_all_components",
                "definition_is_explicit": True,
            },
        )

    expected = {
        "industry_momentum_rank_20", "market_momentum_rank_20",
        *FIXED_COMPOSITE_WEIGHTS,
        "multi_factor_score",
    }
    if set(output) != expected:
        raise AssertionError("cross-sectional output does not match V1 registry")
    return output


def _validate_universe(frame: pd.DataFrame) -> str:
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("cross-sectional input must be a pandas DataFrame")
    if not frame.index.is_unique:
        raise ValueError("cross-sectional input index must be unique")
    if "universe_snapshot_id" not in frame.columns:
        raise ValueError("universe_snapshot_id is required")
    identifiers = frame["universe_snapshot_id"].dropna().astype(str).unique()
    if len(identifiers) != 1 or frame["universe_snapshot_id"].isna().any():
        raise ValueError("input must contain exactly one complete universe_snapshot_id")
    identity_columns = [name for name in ("market", "symbol") if name in frame.columns]
    if "symbol" not in identity_columns:
        raise ValueError("symbol is required")
    if frame.duplicated(identity_columns).any():
        raise ValueError("duplicate symbol in fixed universe snapshot")
    identifier = str(identifiers[0]).strip()
    if not identifier:
        raise ValueError("universe_snapshot_id cannot be empty")
    return identifier


def _percentile_rank(
    frame: pd.DataFrame,
    column: str,
    group_columns: list[str],
) -> tuple[pd.Series, pd.Series]:
    result = pd.Series(np.nan, index=frame.index, dtype=float)
    reasons = pd.Series(pd.NA, index=frame.index, dtype="object")
    if column not in frame.columns:
        reasons[:] = MISSING_COMPONENT
        return result, reasons
    groups = _groups(frame, group_columns)
    for _, group in groups:
        values = pd.to_numeric(group[column], errors="coerce").replace(
            [np.inf, -np.inf], np.nan
        )
        valid = values.dropna()
        if len(valid) < MIN_CROSS_SECTION_SIZE:
            reasons.loc[group.index] = INSUFFICIENT_CROSS_SECTION
            continue
        result.loc[valid.index] = valid.rank(method="average", pct=True)
        reasons.loc[values.index[values.isna()]] = MISSING_COMPONENT
    return result, reasons


def _composite(
    frame: pd.DataFrame,
    weights: Mapping[str, float],
    *,
    market_groups: list[str],
) -> tuple[pd.Series, pd.Series, pd.DataFrame]:
    contributions = pd.DataFrame(index=frame.index)
    component_reasons: list[pd.Series] = []
    for component, weight in weights.items():
        zscore, reasons = _robust_zscore(frame, component, market_groups)
        contributions[component] = zscore * weight
        component_reasons.append(reasons)
    complete = contributions.notna().all(axis=1)
    score = contributions.sum(axis=1, min_count=len(weights)).where(complete)
    reasons = pd.Series(pd.NA, index=frame.index, dtype="object")
    for component_reason in component_reasons:
        mask = reasons.isna() & component_reason.notna()
        reasons.loc[mask] = component_reason.loc[mask]
    reasons.loc[~complete & reasons.isna()] = MISSING_COMPONENT
    return score, reasons, contributions


def _robust_zscore(
    frame: pd.DataFrame,
    column: str,
    group_columns: list[str],
) -> tuple[pd.Series, pd.Series]:
    result = pd.Series(np.nan, index=frame.index, dtype=float)
    reasons = pd.Series(pd.NA, index=frame.index, dtype="object")
    if column not in frame.columns:
        reasons[:] = MISSING_COMPONENT
        return result, reasons
    for _, group in _groups(frame, group_columns):
        values = pd.to_numeric(group[column], errors="coerce").replace(
            [np.inf, -np.inf], np.nan
        )
        valid = values.dropna()
        if len(valid) < MIN_CROSS_SECTION_SIZE:
            reasons.loc[group.index] = INSUFFICIENT_CROSS_SECTION
            continue
        median = float(valid.median())
        mad = float((valid - median).abs().median())
        if mad == 0:
            reasons.loc[group.index] = ZERO_DISPERSION
            continue
        result.loc[valid.index] = (valid - median) / (1.4826 * mad)
        reasons.loc[values.index[values.isna()]] = MISSING_COMPONENT
    return result, reasons


def _groups(frame: pd.DataFrame, columns: list[str]) -> list[tuple[Any, pd.DataFrame]]:
    if not columns:
        return [(None, frame)]
    grouper: str | list[str] = columns[0] if len(columns) == 1 else columns
    return list(frame.groupby(grouper, sort=False, dropna=False))


def _validate_weights(weights: Mapping[str, float]) -> dict[str, float]:
    if not isinstance(weights, Mapping) or not weights:
        raise ValueError("multi_factor_weights must be a non-empty mapping")
    result: dict[str, float] = {}
    for factor_id, raw_weight in weights.items():
        if not isinstance(factor_id, str) or not factor_id:
            raise ValueError("multi-factor component IDs must be non-empty strings")
        if factor_id == "multi_factor_score":
            raise ValueError("multi_factor_score cannot depend on itself")
        if isinstance(raw_weight, bool):
            raise ValueError("multi-factor weights must be numeric")
        weight = float(raw_weight)
        if not np.isfinite(weight):
            raise ValueError("multi-factor weights must be finite")
        result[factor_id] = weight
    if sum(abs(weight) for weight in result.values()) == 0:
        raise ValueError("multi-factor weights cannot all be zero")
    return result
