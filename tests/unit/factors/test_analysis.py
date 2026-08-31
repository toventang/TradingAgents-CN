from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from app.models.factor import FactorAnalysisRequest
from app.services.factors.analysis import (
    FactorAnalysisInsufficientSamples,
    FactorAnalytics,
    build_forward_returns,
)


def request(**updates) -> FactorAnalysisRequest:
    values = {
        "snapshot_ids": ("a" * 64, "b" * 64, "c" * 64),
        "factor_ids": ("signal", "signal_clone"),
        "horizons": (1,),
        "quantiles": 5,
        "min_samples": 10,
        "min_cross_section": 5,
        "label_as_of": datetime(2025, 1, 5, tzinfo=timezone.utc),
        "label_source_version": "labels-v1",
        "transaction_cost_bps": 10,
        "correlation_threshold": 0.85,
        "industry_by_symbol": {
            "S1": "bank",
            "S2": "bank",
            "S3": "tech",
            "S4": "tech",
            "S5": "energy",
        },
        "exposure_source_version": "industry-v1",
    }
    values.update(updates)
    return FactorAnalysisRequest(**values)


def frames():
    feature_dates = pd.date_range("2025-01-01", periods=3, freq="D")
    price_dates = pd.date_range("2025-01-01", periods=4, freq="D")
    feature_rows = []
    price_rows = []
    for rank in range(1, 6):
        symbol = f"S{rank}"
        daily_return = rank / 100.0
        for trade_date in feature_dates:
            feature_rows.append(
                {
                    "symbol": symbol,
                    "trade_date": trade_date.date(),
                    "signal": float(rank),
                    "signal_clone": float(rank * 2),
                    "market_cap_log": float(rank * 10),
                    "beta_60": float(6 - rank),
                    "industry": "bank" if rank <= 2 else "tech",
                }
            )
        for offset, trade_date in enumerate(price_dates):
            price_rows.append(
                {
                    "symbol": symbol,
                    "trade_date": trade_date.date(),
                    "close": 100.0 * (1.0 + daily_return) ** offset,
                }
            )
    return pd.DataFrame(feature_rows), pd.DataFrame(price_rows)


def test_future_labels_use_explicit_negative_shift_and_do_not_mutate_features():
    features, prices = frames()
    original = features.copy(deep=True)
    labels = build_forward_returns(prices, (1, 5))

    s5 = labels.loc[labels["symbol"] == "S5"].sort_values("trade_date")
    assert s5.iloc[0]["forward_1d"] == pytest.approx(0.05)
    assert s5.iloc[1]["forward_1d"] == pytest.approx(0.05)
    assert pd.isna(s5.iloc[-1]["forward_1d"])
    assert s5["forward_5d"].isna().all()

    FactorAnalytics().compute(features, prices, request())
    pd.testing.assert_frame_equal(features, original)


def test_future_label_changes_cannot_leak_into_feature_only_diagnostics():
    features, prices = frames()
    baseline = FactorAnalytics().compute(features, prices, request())
    changed_prices = prices.copy(deep=True)
    changed_prices.loc[
        changed_prices["trade_date"] == changed_prices["trade_date"].max(), "close"
    ] *= changed_prices.loc[
        changed_prices["trade_date"] == changed_prices["trade_date"].max(), "symbol"
    ].str.removeprefix("S").astype(float)
    changed = FactorAnalytics().compute(features, changed_prices, request())

    assert changed.ic != baseline.ic
    assert changed.distributions == baseline.distributions
    assert changed.time_series == baseline.time_series
    assert changed.turnover == baseline.turnover
    assert changed.correlations == baseline.correlations
    assert changed.exposures == baseline.exposures


def test_ic_quantiles_turnover_correlation_exposure_and_decay_are_hand_calculated():
    features, prices = frames()
    result = FactorAnalytics().compute(features, prices, request())

    signal_ic = next(
        item for item in result.ic if item.factor_id == "signal" and item.horizon == 1
    )
    assert signal_ic.sample_count == 15
    assert signal_ic.period_count == 3
    assert signal_ic.pearson_mean == pytest.approx(1.0)
    assert signal_ic.rank_mean == pytest.approx(1.0)
    assert signal_ic.rank_positive_ratio == 1.0

    quantiles = next(item for item in result.quantile_returns if item.factor_id == "signal")
    assert quantiles.returns["Q1"] == pytest.approx(0.01)
    assert quantiles.returns["Q5"] == pytest.approx(0.05)
    assert quantiles.monotonicity == pytest.approx(1.0)
    assert quantiles.gross_long_short_return == pytest.approx(0.04)
    assert quantiles.net_long_short_return == pytest.approx(0.04)

    turnover = next(item for item in result.turnover if item.factor_id == "signal")
    assert turnover.period_count == 2
    assert turnover.top_turnover == 0.0
    assert turnover.bottom_turnover == 0.0

    warning = result.warnings[0]
    assert {warning.factor_a, warning.factor_b} == {"signal", "signal_clone"}
    assert warning.correlation == pytest.approx(1.0)

    exposure = next(item for item in result.exposures if item.factor_id == "signal")
    assert exposure.market_cap_correlation == pytest.approx(1.0)
    assert exposure.beta_correlation == pytest.approx(-1.0)
    assert exposure.industry_sample_counts["bank"] == 6

    decay = next(item for item in result.decay if item.factor_id == "signal")
    assert decay.rank_ic_by_horizon == {"1": pytest.approx(1.0)}
    assert result.distributions[0].valid_observations == 15
    assert len(result.time_series) == 6


def test_analysis_rejects_each_under_sampled_factor_horizon():
    features, prices = frames()
    with pytest.raises(FactorAnalysisInsufficientSamples) as error:
        FactorAnalytics().compute(
            features,
            prices,
            request(min_samples=16),
        )
    insufficient = error.value.details["insufficient"]
    assert {(item["factor_id"], item["horizon"]) for item in insufficient} == {
        ("signal", 1),
        ("signal_clone", 1),
    }


def test_request_rejects_unversioned_exposure_and_invalid_snapshot_identity():
    with pytest.raises(ValueError, match="exposure_source_version"):
        request(exposure_source_version=None)
    with pytest.raises(ValueError, match="SHA-256"):
        request(snapshot_ids=("not-a-snapshot",))
    with pytest.raises(ValueError, match="quantile count"):
        request(quantiles=10, min_cross_section=5)
