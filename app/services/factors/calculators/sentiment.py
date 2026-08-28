"""Structured, point-in-time sentiment factor calculations without LLM calls."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd

from app.services.factors.calculators.common import (
    INSUFFICIENT_HISTORY,
    MISSING_INPUT,
    ZERO_DENOMINATOR,
)


class SentimentFactorOutput(dict[str, float]):
    def __init__(self, *, as_of: datetime):
        super().__init__()
        self.as_of = as_of
        self.quality_reasons: dict[str, str | None] = {}
        self.provenance: dict[str, dict[str, Any]] = {}
        self.evidence: dict[str, tuple[str, ...]] = {}

    def add(
        self,
        factor_id: str,
        value: float | None,
        *,
        reason: str | None = None,
        provenance: Mapping[str, Any] | None = None,
        evidence: tuple[str, ...] = (),
    ) -> None:
        if value is None or not np.isfinite(value):
            self[factor_id] = np.nan
            self.quality_reasons[factor_id] = reason or MISSING_INPUT
        else:
            self[factor_id] = float(value)
            self.quality_reasons[factor_id] = None
        self.provenance[factor_id] = {
            "as_of": self.as_of.isoformat(), **dict(provenance or {})
        }
        self.evidence[factor_id] = tuple(sorted(set(evidence)))


def calculate_sentiment_factors(
    *,
    as_of: datetime,
    news_events: pd.DataFrame | None = None,
    social_events: pd.DataFrame | None = None,
    news_source_weights: Mapping[str, float] | None = None,
    social_source_weights: Mapping[str, float] | None = None,
    market: str | None = None,
    symbol: str | None = None,
) -> SentimentFactorOutput:
    """Calculate the eight V1 sentiment factors from visible structured events."""
    as_of_utc = _aware_utc(as_of)
    news = _visible_events(
        news_events, kind="news", as_of=as_of_utc, market=market, symbol=symbol
    )
    social = _visible_events(
        social_events, kind="social", as_of=as_of_utc, market=market, symbol=symbol
    )
    _validate_single_identity(news, social)
    news_weights = _source_weights(news_source_weights)
    social_weights = _source_weights(social_source_weights)
    output = SentimentFactorOutput(as_of=as_of_utc)

    for window in (1, 7, 30):
        value, evidence = _weighted_sentiment(
            news, as_of_utc, window, news_weights, half_life_days=max(window / 2.0, 0.5)
        )
        output.add(
            f"news_sentiment_{window}d", value,
            reason=None if value is not None else MISSING_INPUT,
            evidence=evidence,
            provenance={
                "formula": "weighted_mean(structured_sentiment, source_weight*time_decay)",
                "window_days": window,
                "decay": "exponential_half_life",
                "half_life_days": max(window / 2.0, 0.5),
                "source_weights": dict(news_weights),
                "visibility": "published_at and ingested_at <= as_of",
            },
        )

    news_zscore, news_reason = _volume_zscore(news, as_of_utc)
    output.add(
        "news_volume_zscore_7d", news_zscore, reason=news_reason,
        evidence=_event_ids(_window(news, as_of_utc, 60)),
        provenance={
            "formula": "zscore(latest_7d_count, prior_7d_rolling_counts_in_60d)",
            "window_days": 7, "baseline_days": 60,
            "visibility": "published_at and ingested_at <= as_of",
        },
    )
    negative_ratio, negative_evidence = _negative_ratio(
        news, as_of_utc, news_weights
    )
    output.add(
        "negative_news_ratio_7d", negative_ratio,
        reason=None if negative_ratio is not None else MISSING_INPUT,
        evidence=negative_evidence,
        provenance={
            "formula": "weighted_mean(structured_sentiment < 0, source_weight*time_decay)",
            "window_days": 7, "half_life_days": 3.5, "unit": "decimal",
            "source_weights": dict(news_weights),
        },
    )

    for window in (1, 7):
        value, evidence = _weighted_sentiment(
            social, as_of_utc, window, social_weights,
            half_life_days=max(window / 2.0, 0.5),
        )
        output.add(
            f"social_sentiment_{window}d", value,
            reason=None if value is not None else MISSING_INPUT,
            evidence=evidence,
            provenance={
                "formula": "weighted_mean(structured_sentiment, source_weight*time_decay)",
                "window_days": window,
                "decay": "exponential_half_life",
                "half_life_days": max(window / 2.0, 0.5),
                "source_weights": dict(social_weights),
                "visibility": "published_at and ingested_at <= as_of",
            },
        )
    social_zscore, social_reason = _volume_zscore(social, as_of_utc)
    output.add(
        "social_volume_zscore_7d", social_zscore, reason=social_reason,
        evidence=_event_ids(_window(social, as_of_utc, 60)),
        provenance={
            "formula": "zscore(latest_7d_count, prior_7d_rolling_counts_in_60d)",
            "window_days": 7, "baseline_days": 60,
            "visibility": "published_at and ingested_at <= as_of",
        },
    )
    if set(output) != {
        "news_sentiment_1d", "news_sentiment_7d", "news_sentiment_30d",
        "news_volume_zscore_7d", "negative_news_ratio_7d",
        "social_sentiment_1d", "social_sentiment_7d", "social_volume_zscore_7d",
    }:
        raise AssertionError("sentiment output does not match V1 registry")
    return output


def _visible_events(
    frame: pd.DataFrame | None,
    *,
    kind: str,
    as_of: datetime,
    market: str | None,
    symbol: str | None,
) -> pd.DataFrame:
    if frame is None or frame.empty:
        return _empty_events()
    if not isinstance(frame, pd.DataFrame):
        raise TypeError(f"{kind}_events must be a pandas DataFrame")
    prefix = f"{kind}_"
    aliases = {
        "event_id": (f"{kind}_id", "event_id", "id"),
        "published_at": (f"{prefix}published_at", "published_at"),
        "ingested_at": (f"{prefix}ingested_at", "ingested_at"),
        "sentiment": (f"{prefix}sentiment", "sentiment_score", "sentiment"),
        "source": (f"{prefix}source", "source"),
    }
    normalized = pd.DataFrame(index=frame.index)
    for target, candidates in aliases.items():
        source = next((name for name in candidates if name in frame.columns), None)
        if source is None:
            if target == "event_id":
                normalized[target] = frame.index.map(str)
                continue
            if target == "source":
                normalized[target] = "unknown"
                continue
            raise ValueError(f"{kind}_events requires {target}")
        normalized[target] = frame[source]

    for identity in ("market", "symbol"):
        source = next(
            (name for name in (f"{prefix}{identity}", identity) if name in frame.columns),
            None,
        )
        normalized[identity] = (
            "" if source is None
            else frame[source].map(lambda value: str(getattr(value, "value", value)))
        )

    published = _aware_timestamp_series(normalized["published_at"], "published_at")
    ingested = _aware_timestamp_series(normalized["ingested_at"], "ingested_at")
    normalized["published_at"] = published
    normalized["ingested_at"] = ingested
    normalized["sentiment"] = pd.to_numeric(
        normalized["sentiment"], errors="coerce"
    ).astype(float)
    if np.isinf(normalized["sentiment"]).any():
        raise ValueError("structured sentiment must be finite")
    valid_scores = normalized["sentiment"].dropna()
    if ((valid_scores < -1) | (valid_scores > 1)).any():
        raise ValueError("structured sentiment must be between -1 and 1")
    selected = pd.Series(True, index=normalized.index)
    if market is not None:
        selected &= normalized["market"].eq(str(getattr(market, "value", market)))
    if symbol is not None:
        selected &= normalized["symbol"].eq(str(symbol))
    visible = normalized.loc[selected & (published <= as_of) & (ingested <= as_of)].copy()
    return visible.sort_values(["published_at", "event_id"], kind="mergesort")


def _weighted_sentiment(
    events: pd.DataFrame,
    as_of: datetime,
    window_days: int,
    source_weights: Mapping[str, float],
    *,
    half_life_days: float,
) -> tuple[float | None, tuple[str, ...]]:
    selected = _window(events, as_of, window_days).dropna(subset=["sentiment"])
    if selected.empty:
        return None, ()
    ages = (as_of - selected["published_at"]).dt.total_seconds() / 86400.0
    weights = selected["source"].map(lambda source: source_weights.get(str(source), 1.0))
    weights = weights * np.exp(-np.log(2.0) * ages / half_life_days)
    if weights.sum() <= 0:
        return None, _event_ids(selected)
    return float(np.average(selected["sentiment"], weights=weights)), _event_ids(selected)


def _negative_ratio(
    events: pd.DataFrame,
    as_of: datetime,
    source_weights: Mapping[str, float],
) -> tuple[float | None, tuple[str, ...]]:
    selected = _window(events, as_of, 7).dropna(subset=["sentiment"])
    if selected.empty:
        return None, ()
    ages = (as_of - selected["published_at"]).dt.total_seconds() / 86400.0
    weights = selected["source"].map(lambda source: source_weights.get(str(source), 1.0))
    weights = weights * np.exp(-np.log(2.0) * ages / 3.5)
    if weights.sum() <= 0:
        return None, _event_ids(selected)
    return float(np.average(selected["sentiment"] < 0, weights=weights)), _event_ids(selected)


def _volume_zscore(
    events: pd.DataFrame, as_of: datetime
) -> tuple[float | None, str | None]:
    start_date = (as_of - timedelta(days=59)).date()
    end_date = as_of.date()
    days = pd.date_range(start_date, end_date, freq="D", tz="UTC")
    visible = _window(events, as_of, 60)
    counts = (
        visible.assign(day=visible["published_at"].dt.normalize())
        .groupby("day").size().reindex(days, fill_value=0).astype(float)
    )
    rolling = counts.rolling(7, min_periods=7).sum()
    baseline = rolling.iloc[:-1].dropna()
    if len(baseline) < 20:
        return None, INSUFFICIENT_HISTORY
    standard_deviation = float(baseline.std(ddof=0))
    if standard_deviation == 0:
        return None, ZERO_DENOMINATOR
    return float((rolling.iloc[-1] - baseline.mean()) / standard_deviation), None


def _window(events: pd.DataFrame, as_of: datetime, days: int) -> pd.DataFrame:
    lower = as_of - timedelta(days=days)
    return events.loc[
        (events["published_at"] > lower) & (events["published_at"] <= as_of)
    ]


def _source_weights(values: Mapping[str, float] | None) -> dict[str, float]:
    result = {str(source): float(weight) for source, weight in (values or {}).items()}
    if any(not np.isfinite(weight) or weight < 0 for weight in result.values()):
        raise ValueError("source weights must be finite and non-negative")
    return result


def _event_ids(events: pd.DataFrame) -> tuple[str, ...]:
    return tuple(events["event_id"].astype(str).tolist())


def _empty_events() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "event_id": pd.Series(dtype="object"),
            "published_at": pd.Series(dtype="datetime64[ns, UTC]"),
            "ingested_at": pd.Series(dtype="datetime64[ns, UTC]"),
            "sentiment": pd.Series(dtype="float64"),
            "source": pd.Series(dtype="object"),
            "market": pd.Series(dtype="object"),
            "symbol": pd.Series(dtype="object"),
        }
    )


def _aware_timestamp_series(values: pd.Series, name: str) -> pd.Series:
    converted = []
    for value in values:
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError(f"{name} must contain timezone-aware timestamps")
        converted.append(timestamp.tz_convert("UTC"))
    return pd.Series(converted, index=values.index, dtype="datetime64[ns, UTC]")


def _validate_single_identity(*groups: pd.DataFrame) -> None:
    identities = {
        (str(row.market), str(row.symbol))
        for group in groups
        for row in group.loc[
            group["market"].ne("") | group["symbol"].ne(""), ["market", "symbol"]
        ].itertuples(index=False)
    }
    if len(identities) > 1:
        raise ValueError("sentiment calculation requires exactly one market and symbol")


def _aware_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("as_of must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)
