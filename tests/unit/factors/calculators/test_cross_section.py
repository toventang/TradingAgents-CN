import numpy as np
import pandas as pd
import pytest

from app.services.factors.calculators.cross_section import (
    INSUFFICIENT_CROSS_SECTION,
    calculate_cross_section_factors,
)


COMPONENTS = {
    "ret_1d", "ret_20d", "ret_60d", "ret_120d",
    "earnings_yield", "book_to_price", "sales_to_price",
    "roe_ttm", "roic_ttm", "cfo_to_net_income", "accruals_ratio", "debt_to_assets",
    "revenue_yoy", "net_profit_yoy", "eps_yoy", "cfo_yoy",
    "hist_vol_20", "downside_vol_20", "beta_60", "max_drawdown_60",
    "turnover_mean_20", "amount_ratio_20", "amihud_illiq_20",
    "news_sentiment_7d", "social_sentiment_7d", "news_volume_zscore_7d",
}


def _universe(size=40):
    position = np.arange(size, dtype=float)
    frame = pd.DataFrame(
        {
            "universe_snapshot_id": "universe-v1",
            "market": "US",
            "symbol": [f"S{index:03d}" for index in range(size)],
            "industry": ["A" if index < size / 2 else "B" for index in range(size)],
        }
    )
    for offset, component in enumerate(sorted(COMPONENTS), start=1):
        frame[component] = position + position**2 * offset / 10_000.0
    return frame


def test_exact_ten_outputs_rank_only_inside_fixed_universe():
    frame = _universe()
    output = calculate_cross_section_factors(frame)
    assert set(output) == {
        "industry_momentum_rank_20", "market_momentum_rank_20",
        "value_composite", "quality_composite", "growth_composite",
        "momentum_composite", "low_vol_composite", "liquidity_composite",
        "sentiment_composite", "multi_factor_score",
    }
    assert output["industry_momentum_rank_20"].iloc[0] == pytest.approx(1.0 / 20.0)
    assert output["industry_momentum_rank_20"].iloc[19] == pytest.approx(1.0)
    assert output["market_momentum_rank_20"].iloc[0] == pytest.approx(1.0 / 40.0)
    assert output.universe_snapshot_id == "universe-v1"


def test_fixed_composite_contributions_sum_exactly_to_published_score():
    output = calculate_cross_section_factors(_universe())
    for factor_id in (
        "value_composite", "quality_composite", "growth_composite",
        "momentum_composite", "low_vol_composite", "liquidity_composite",
        "sentiment_composite",
    ):
        contributions = output.contributions[factor_id]
        pd.testing.assert_series_equal(
            output[factor_id],
            contributions.sum(axis=1, min_count=len(contributions.columns)).rename(factor_id),
        )
        assert output.provenance[factor_id]["weights"]


def test_multi_factor_requires_explicit_weights_and_saves_definition_and_contributions():
    frame = _universe()
    missing = calculate_cross_section_factors(frame)
    assert missing["multi_factor_score"].isna().all()
    assert missing.provenance["multi_factor_score"]["weights"] is None

    output = calculate_cross_section_factors(
        frame,
        multi_factor_weights={"earnings_yield": 0.6, "book_to_price": 0.4},
    )
    assert output["multi_factor_score"].notna().all()
    assert output.provenance["multi_factor_score"]["weights"] == {
        "earnings_yield": 0.6, "book_to_price": 0.4,
    }
    contributions = output.contributions["multi_factor_score"]
    pd.testing.assert_series_equal(
        output["multi_factor_score"],
        contributions.sum(axis=1, min_count=2).rename("multi_factor_score"),
    )
    with pytest.raises(ValueError, match="unknown multi-factor"):
        calculate_cross_section_factors(
            frame, multi_factor_weights={"not_a_registered_input": 1.0}
        )
    with pytest.raises(ValueError, match="cannot depend on itself"):
        calculate_cross_section_factors(
            frame, multi_factor_weights={"multi_factor_score": 1.0}
        )


def test_fewer_than_twenty_valid_symbols_returns_no_rank_or_zscore():
    output = calculate_cross_section_factors(_universe(19))
    assert output["market_momentum_rank_20"].isna().all()
    assert output["value_composite"].isna().all()
    assert (
        output.quality_reasons["market_momentum_rank_20"]
        == INSUFFICIENT_CROSS_SECTION
    ).all()


def test_missing_component_does_not_silently_reweight_and_universe_must_be_fixed():
    frame = _universe()
    frame.loc[0, "earnings_yield"] = np.nan
    output = calculate_cross_section_factors(frame)
    assert np.isnan(output["value_composite"].iloc[0])
    assert output["value_composite"].iloc[1:].notna().all()

    mixed = _universe()
    mixed.loc[0, "universe_snapshot_id"] = "changed-during-calculation"
    with pytest.raises(ValueError, match="exactly one"):
        calculate_cross_section_factors(mixed)
