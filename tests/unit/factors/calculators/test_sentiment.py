from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from app.services.factors.calculators.event import calculate_event_factors
from app.services.factors.calculators.sentiment import calculate_sentiment_factors


UTC = timezone.utc


def test_structured_sentiment_uses_source_decay_and_visibility_boundaries():
    as_of = datetime(2025, 3, 10, 12, tzinfo=UTC)
    news = pd.DataFrame(
        [
            {
                "news_id": "visible-positive",
                "published_at": as_of - timedelta(hours=12),
                "ingested_at": as_of - timedelta(hours=11),
                "sentiment_score": 1.0,
                "source": "trusted",
            },
            {
                "news_id": "visible-negative",
                "published_at": as_of - timedelta(hours=6),
                "ingested_at": as_of - timedelta(hours=5),
                "sentiment_score": -1.0,
                "source": "ordinary",
            },
            {
                "news_id": "late-ingestion",
                "published_at": as_of - timedelta(hours=2),
                "ingested_at": as_of + timedelta(minutes=1),
                "sentiment_score": -1.0,
                "source": "trusted",
            },
            {
                "news_id": "future-publication",
                "published_at": as_of + timedelta(minutes=1),
                "ingested_at": as_of - timedelta(hours=1),
                "sentiment_score": -1.0,
                "source": "trusted",
            },
        ]
    )
    output = calculate_sentiment_factors(
        as_of=as_of,
        news_events=news,
        news_source_weights={"trusted": 3.0, "ordinary": 1.0},
    )
    trusted_weight = 3.0 * 2 ** (-0.5 / 0.5)
    ordinary_weight = 2 ** (-0.25 / 0.5)
    expected = (trusted_weight - ordinary_weight) / (trusted_weight + ordinary_weight)
    assert output["news_sentiment_1d"] == pytest.approx(expected)
    negative_trusted_weight = 3.0 * 2 ** (-0.5 / 3.5)
    negative_ordinary_weight = 2 ** (-0.25 / 3.5)
    assert output["negative_news_ratio_7d"] == pytest.approx(
        negative_ordinary_weight
        / (negative_trusted_weight + negative_ordinary_weight)
    )
    assert output.evidence["news_sentiment_1d"] == (
        "visible-negative", "visible-positive"
    )
    assert "late-ingestion" not in output.evidence["news_sentiment_1d"]


def test_volume_anomaly_uses_prior_rolling_seven_day_counts_in_sixty_days():
    as_of = datetime(2025, 3, 10, 23, tzinfo=UTC)
    rows = []
    for age in range(60):
        count = 4 if age < 7 else 1
        for sequence in range(count):
            rows.append(
                {
                    "news_id": f"n-{age}-{sequence}",
                    "published_at": as_of - timedelta(days=age, hours=1),
                    "ingested_at": as_of - timedelta(days=age),
                    "sentiment_score": 0.25,
                    "source": "wire",
                }
            )
    output = calculate_sentiment_factors(as_of=as_of, news_events=pd.DataFrame(rows))
    assert output["news_volume_zscore_7d"] > 0
    assert output.provenance["news_volume_zscore_7d"]["baseline_days"] == 60


def test_social_outputs_are_structured_and_no_events_return_missing():
    as_of = datetime(2025, 3, 10, tzinfo=UTC)
    social = pd.DataFrame(
        {
            "social_id": ["s1"],
            "published_at": [as_of - timedelta(hours=1)],
            "ingested_at": [as_of - timedelta(minutes=30)],
            "sentiment_score": [0.4],
            "source": ["social-feed"],
        }
    )
    output = calculate_sentiment_factors(as_of=as_of, social_events=social)
    assert len(output) == 8
    assert output["social_sentiment_1d"] == pytest.approx(0.4)
    assert np.isnan(output["news_sentiment_1d"])
    with pytest.raises(ValueError, match="between -1 and 1"):
        calculate_sentiment_factors(
            as_of=as_of,
            social_events=social.assign(sentiment_score=1.5),
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        calculate_sentiment_factors(
            as_of=as_of,
            social_events=social.assign(published_at=datetime(2025, 3, 9)),
        )


def test_sentiment_rejects_accidental_cross_symbol_aggregation():
    as_of = datetime(2025, 3, 10, tzinfo=UTC)
    events = pd.DataFrame(
        {
            "news_id": ["a", "b"],
            "market": ["US", "US"],
            "symbol": ["AAA", "BBB"],
            "published_at": [as_of - timedelta(hours=2)] * 2,
            "ingested_at": [as_of - timedelta(hours=1)] * 2,
            "sentiment_score": [0.2, 0.3],
            "source": ["wire", "wire"],
        }
    )
    with pytest.raises(ValueError, match="exactly one"):
        calculate_sentiment_factors(as_of=as_of, news_events=events)


def _event_frame(length=60):
    returns = np.resize(np.array([-0.01, 0.01]), length - 1)
    close = np.r_[100.0, 100.0 * np.cumprod(1.0 + returns)]
    pre_close = np.r_[np.nan, close[:-1]]
    return pd.DataFrame(
        {
            "market": "CN",
            "board": "MAIN",
            "symbol": "600000",
            "trade_date": pd.date_range("2025-01-01", periods=length, freq="B"),
            "open": pre_close,
            "close": close,
            "pre_close": pre_close,
            "suspended": False,
            "limit_up_price": pre_close * 1.1,
            "limit_down_price": pre_close * 0.9,
        }
    )


def test_event_factors_count_gap_and_suspension_without_treating_zero_volume_as_suspension():
    frame = _event_frame()
    frame.loc[frame.index[-1], "open"] = frame.loc[frame.index[-1], "pre_close"] * 1.10
    frame.loc[frame.index[-3:], "suspended"] = True
    frame["volume"] = 1_000.0
    frame.loc[frame.index[-5], "volume"] = 0.0
    output = calculate_event_factors(frame)
    assert len(output) == 4
    assert output["gap_event_20"].iloc[-1] == pytest.approx(1.0)
    assert output["suspension_days_20"].iloc[-1] == pytest.approx(3.0)


def test_price_limit_counts_use_market_board_and_effective_date_rules():
    frame = _event_frame(25).drop(columns=["limit_up_price", "limit_down_price"])
    switch_date = frame["trade_date"].iloc[10]
    frame["pre_close"] = 100.0
    frame["close"] = 110.0
    rules = pd.DataFrame(
        [
            {
                "market": "CN", "board": "MAIN",
                "effective_from": frame["trade_date"].iloc[0],
                "effective_to": switch_date - timedelta(days=1),
                "up_limit": 0.10, "down_limit": 0.10, "tick_size": 0.01,
            },
            {
                "market": "CN", "board": "MAIN",
                "effective_from": switch_date,
                "effective_to": None,
                "up_limit": 0.20, "down_limit": 0.20, "tick_size": 0.01,
            },
        ]
    )
    output = calculate_event_factors(frame, price_limit_rules=rules)
    assert output["limit_up_count_20"].iloc[-1] == pytest.approx(5.0)
    assert output.provenance["limit_up_count_20"]["rule_alignment"] == (
        "market, board, trade_date"
    )
