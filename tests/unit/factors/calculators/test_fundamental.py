from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from app.models.factor import FactorCategory
from app.services.factors.calculators.common import INSUFFICIENT_HISTORY, INVALID_DOMAIN
from app.services.factors.calculators.fundamental import (
    NON_POSITIVE_DENOMINATOR,
    calculate_fundamental_factors,
)
from app.services.factors.point_in_time import resolve_point_in_time
from app.services.factors.registry import global_factor_registry


UTC = timezone.utc


def _quarterly_facts(*, negative_start=False, omit_ordinal=None):
    facts = []
    for index in range(13):
        if index == omit_ordinal:
            continue
        year = 2022 + index // 4
        quarter = index % 4 + 1
        level = 100.0 * 1.1 ** (index / 4.0)
        net_profit = level / 10.0
        if negative_start and index == 0:
            net_profit = -net_profit
        data = {
            "revenue": level,
            "net_profit": net_profit,
            "eps": level / 100.0,
            "operating_cashflow": level / 8.0,
            "roe": 0.10 + index * 0.0025,
            "gross_margin": 0.30 + index * 0.0025,
        }
        if index == 12:
            data.update(
                {
                    "net_profit_ttm": 100.0,
                    "equity_mrq": 500.0,
                    "revenue_ttm": 400.0,
                    "operating_cashflow_ttm": 80.0,
                    "cash_dividend_ttm": 20.0,
                    "ebitda_ttm": 120.0,
                    "ebit_ttm": 100.0,
                    "average_equity": 400.0,
                    "average_assets": 800.0,
                    "nopat_ttm": 90.0,
                    "invested_capital": 600.0,
                    "gross_profit_ttm": 160.0,
                    "operating_profit_ttm": 120.0,
                    "free_cashflow_ttm": 60.0,
                    "cost_of_revenue_ttm": 240.0,
                    "average_inventory": 60.0,
                    "average_receivables": 50.0,
                    "current_assets": 300.0,
                    "quick_assets": 240.0,
                    "cash": 100.0,
                    "current_liabilities": 150.0,
                    "total_debt": 200.0,
                    "total_assets": 1_000.0,
                    "total_equity": 500.0,
                    "interest_expense_ttm": 20.0,
                    "goodwill": 50.0,
                    "retention_ratio": 0.60,
                }
            )
        facts.append(
            {
                "fact_id": f"fact-{index}",
                "market": "US",
                "symbol": "AAA",
                "report_period": f"{year}Q{quarter}",
                "publish_at": datetime(year, quarter * 3, 20, tzinfo=UTC)
                + timedelta(days=30),
                "source": "fixture",
                "source_version": "v1",
                "data": data,
            }
        )
    return facts


def _snapshot(**options):
    return resolve_point_in_time(
        _quarterly_facts(**options),
        as_of=datetime(2025, 5, 1, tzinfo=UTC),
    )


def _market_values():
    return {
        "market_cap": 1_000.0,
        "free_float_market_cap": 800.0,
        "enterprise_value": 1_200.0,
        "historical_growth": 0.10,
    }


def test_exact_51_registered_outputs_and_hand_calculated_ratios():
    output = calculate_fundamental_factors(_snapshot(), market_values=_market_values())
    expected = {
        item.factor_id
        for category in (FactorCategory.VALUATION, FactorCategory.QUALITY, FactorCategory.GROWTH)
        for item in global_factor_registry.get_by_category(category)
    }
    assert len(output) == 51
    assert set(output) == expected
    assert "retained_earnings_to_assets" not in output
    assert output["pe_ttm"] == pytest.approx(10.0)
    assert output["earnings_yield"] == pytest.approx(0.10)
    assert output["pb_mrq"] == pytest.approx(2.0)
    assert output["dividend_yield_ttm"] == pytest.approx(0.02)
    assert output["ev_to_ebitda"] == pytest.approx(10.0)
    assert output["peg"] == pytest.approx(1.0)
    assert output["roe_ttm"] == pytest.approx(0.25)
    assert output["gross_margin_ttm"] == pytest.approx(0.40)
    assert output["accruals_ratio"] == pytest.approx(0.025)
    assert output["sustainable_growth_rate"] == pytest.approx(0.15)


def test_growth_cagr_stability_and_quarter_statistics_use_disclosed_history():
    output = calculate_fundamental_factors(_snapshot(), market_values=_market_values())
    assert output["revenue_yoy"] == pytest.approx(0.10)
    assert output["revenue_cagr_3y"] == pytest.approx(0.10)
    assert output["net_profit_cagr_3y"] == pytest.approx(0.10)
    assert output["revenue_stability_8q"] == pytest.approx(0.0, abs=1e-12)
    assert output["positive_profit_quarters_8q"] == pytest.approx(1.0)
    assert output["positive_cfo_quarters_8q"] == pytest.approx(1.0)
    assert output["consecutive_revenue_growth_q"] == pytest.approx(8.0)
    assert output["consecutive_profit_growth_q"] == pytest.approx(8.0)
    assert output["roe_change_yoy"] == pytest.approx(0.01)
    assert output.provenance["revenue_cagr_3y"]["endpoint_rule"] == "both_strictly_positive"


def test_negative_earnings_and_nonpositive_denominators_return_missing():
    snapshot = _snapshot()
    values = dict(snapshot.values)
    values.update({"net_profit_ttm": -10.0, "current_liabilities": 0.0})
    output = calculate_fundamental_factors(
        values,
        as_of=snapshot.as_of,
        market_values=_market_values(),
    )
    assert np.isnan(output["pe_ttm"])
    assert output.quality_reasons["pe_ttm"] == NON_POSITIVE_DENOMINATOR
    assert np.isnan(output["earnings_yield"])
    assert output["net_margin_ttm"] == pytest.approx(-0.025)
    assert np.isnan(output["cfo_to_net_income"])
    assert np.isnan(output["current_ratio"])
    assert output.quality_reasons["current_ratio"] == NON_POSITIVE_DENOMINATOR


def test_missing_quarter_blocks_history_dependent_values_without_estimates():
    output = calculate_fundamental_factors(
        _snapshot(omit_ordinal=7), market_values=_market_values()
    )
    assert np.isnan(output["revenue_stability_8q"])
    assert output.quality_reasons["revenue_stability_8q"] == INSUFFICIENT_HISTORY
    assert np.isnan(output["positive_profit_quarters_8q"])


def test_invalid_three_year_cagr_endpoint_is_missing_and_evidence_is_preserved():
    output = calculate_fundamental_factors(
        _snapshot(negative_start=True), market_values=_market_values()
    )
    assert np.isnan(output["net_profit_cagr_3y"])
    assert output.quality_reasons["net_profit_cagr_3y"] == INVALID_DOMAIN
    assert len(output.evidence["net_profit_cagr_3y"]) == 2
    assert all(item.publish_at <= output.snapshot.as_of for item in output.evidence["pe_ttm"])


def test_consensus_growth_requires_an_explicit_source_and_percentages_stay_decimal():
    values = dict(_snapshot().values)
    values.pop("historical_growth", None)
    output_without_source = calculate_fundamental_factors(
        values,
        as_of=datetime(2025, 5, 1, tzinfo=UTC),
        market_values={
            **_market_values(),
            "historical_growth": None,
            "consensus_growth": 0.10,
        },
    )
    assert np.isnan(output_without_source["peg"])
    output = calculate_fundamental_factors(
        values,
        as_of=datetime(2025, 5, 1, tzinfo=UTC),
        market_values={
            **_market_values(),
            "historical_growth": None,
            "consensus_growth": 0.10,
            "consensus_growth_source": "licensed-consensus-v1",
        },
    )
    assert output["peg"] == pytest.approx(1.0)
    assert output.provenance["peg"]["percentage_storage"] == "decimal"
