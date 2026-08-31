from __future__ import annotations

import math

import pandas as pd
import pytest

from app.models.factor import (
    CompositeArithmeticKind,
    CompositeDefinition,
    CompositeFactorTerm,
    CompositeFilterPolicy,
    CompositeMissingKind,
    CompositeNeutralizeKind,
    CompositeTransformSpec,
    FactorVersionRef,
)
from app.models.symbol import Market
from app.services.factors.composites import CompositeDslEngine, CompositeDslError


def term(factor_id, weight=1.0, transform=None, version=1):
    return CompositeFactorTerm(
        factor=FactorVersionRef(factor_id=factor_id, version=version),
        weight=weight,
        transform=transform or CompositeTransformSpec(),
    )


def definition(**updates):
    values = {
        "terms": (
            term("ret_1d", 2.0),
            term("hist_vol_20", -1.0),
        ),
        "auto_direction": False,
        "neutralize": "none",
        "arithmetic": "weighted_sum",
        "missing": "drop_symbol",
    }
    values.update(updates)
    return CompositeDefinition(**values)


def test_closed_models_reject_code_fields_unknown_operations_and_bad_parameters():
    payload = definition().model_dump(mode="json")
    payload["expression"] = "malicious_payload()"
    with pytest.raises(ValueError, match="Extra inputs"):
        CompositeDefinition.model_validate(payload)
    with pytest.raises(ValueError):
        CompositeTransformSpec(kind="unsupported")
    with pytest.raises(ValueError, match="does not accept transform parameters"):
        CompositeTransformSpec(kind="identity", mad_scale=3)
    with pytest.raises(ValueError, match="upper_quantile"):
        CompositeTransformSpec(
            kind="winsorize_quantile", lower_quantile=0.4, upper_quantile=0.3
        )


def test_resolution_normalizes_absolute_weights_and_pins_direction_and_versions():
    engine = CompositeDslEngine()
    resolved, dependencies, checksum = engine.resolve(
        Market.CN, definition(auto_direction=True)
    )
    assert sum(abs(item.weight) for item in resolved.terms) == pytest.approx(1.0)
    assert [item.weight for item in resolved.terms] == pytest.approx([2 / 3, -1 / 3])
    by_id = {item.factor_id: item for item in dependencies}
    assert by_id["ret_1d"].effective_multiplier == 1
    assert by_id["hist_vol_20"].effective_multiplier == -1
    assert by_id["hist_vol_20"].version == 1
    assert len(by_id["hist_vol_20"].definition_checksum) == 64
    assert len(checksum) == 64

    with pytest.raises(CompositeDslError) as mismatch:
        engine.resolve(
            Market.CN,
            definition(terms=(term("ret_1d", version=2),)),
        )
    assert mismatch.value.code == "COMPOSITE_FACTOR_VERSION_MISMATCH"


@pytest.mark.parametrize(
    ("transform", "expected"),
    [
        ({"kind": "identity"}, [-2.0, 0.0, 2.0]),
        ({"kind": "negate"}, [2.0, 0.0, -2.0]),
        ({"kind": "log1p_abs"}, [-math.log(3), 0.0, math.log(3)]),
        ({"kind": "zscore"}, [-math.sqrt(1.5), 0.0, math.sqrt(1.5)]),
        ({"kind": "robust_zscore"}, [-1 / 1.4826, 0.0, 1 / 1.4826]),
        ({"kind": "percentile_rank"}, [1 / 3, 2 / 3, 1.0]),
    ],
)
def test_transform_whitelist_has_deterministic_cross_section_semantics(
    transform, expected
):
    engine = CompositeDslEngine()
    selected = CompositeDefinition(
        terms=(term("ret_1d", transform=CompositeTransformSpec(**transform)),)
    )
    resolved, dependencies, _ = engine.resolve(Market.CN, selected)
    result = engine.score(
        pd.DataFrame({"symbol": ["A", "B", "C"], "ret_1d": [-2.0, 0.0, 2.0]}),
        resolved,
        dependencies,
    )
    assert [item.raw_score for item in result.rows] == pytest.approx(expected)
    assert all(sum(item.contributions.values()) == pytest.approx(item.raw_score) for item in result.rows)


def test_winsorization_neutralization_filters_and_arithmetic_are_closed():
    engine = CompositeDslEngine()
    frame = pd.DataFrame(
        {
            "symbol": ["A", "B", "C", "D", "E"],
            "ret_1d": [1.0, 2.0, 3.0, 4.0, 100.0],
            "hist_vol_20": [1.0, 4.0, 9.0, 16.0, 25.0],
            "market_cap_log": [10.0, 11.0, 12.0, 13.0, 14.0],
            "industry": ["bank", "bank", "tech", "tech", "tech"],
            "listing_days": [100, 100, 100, 10, 100],
            "is_st": [False, False, False, False, True],
            "is_delisting": False,
            "is_suspended": False,
        }
    )
    selected = definition(
        terms=(
            term(
                "ret_1d",
                transform=CompositeTransformSpec(kind="winsorize_quantile"),
            ),
            term("hist_vol_20"),
        ),
        neutralize=CompositeNeutralizeKind.INDUSTRY_AND_MARKET_CAP,
        arithmetic=CompositeArithmeticKind.MEAN,
        filters=CompositeFilterPolicy(
            minimum_market_cap_log=10,
            maximum_market_cap_log=14,
            include_industries=("bank", "tech"),
            minimum_listing_days=30,
            exclude_st=True,
            exclude_delisting=True,
            exclude_suspended=True,
        ),
    )
    resolved, dependencies, _ = engine.resolve(Market.CN, selected)
    result = engine.score(frame, resolved, dependencies)
    assert {row.symbol for row in result.rows} == {"A", "B", "C"}
    assert result.filtered_symbols == 2
    assert all(
        sum(row.contributions.values()) == pytest.approx(row.raw_score)
        for row in result.rows
    )

    geometric = definition(
        terms=(term("ret_1d"), term("hist_vol_20")),
        arithmetic=CompositeArithmeticKind.GEOMETRIC_MEAN,
    )
    resolved, dependencies, _ = engine.resolve(Market.CN, geometric)
    result = engine.score(frame.iloc[:1], resolved, dependencies)
    assert result.rows[0].raw_score == pytest.approx(1.0)

    mad_selected = CompositeDefinition(
        terms=(
            term(
                "ret_1d",
                transform=CompositeTransformSpec(kind="winsorize_mad", mad_scale=3),
            ),
        )
    )
    resolved, dependencies, _ = engine.resolve(Market.CN, mad_selected)
    result = engine.score(
        pd.DataFrame(
            {"symbol": ["A", "B", "C", "D"], "ret_1d": [0, 1, 2, 100]}
        ),
        resolved,
        dependencies,
    )
    assert result.rows[-1].raw_score == pytest.approx(1.5 + 3 * 1.4826)


def test_missing_policies_enforce_sixty_percent_coverage_and_contributions():
    engine = CompositeDslEngine()
    selected = definition(
        terms=(term("ret_1d", 0.6), term("hist_vol_20", 0.4)),
        missing=CompositeMissingKind.RENORMALIZE_WEIGHTS,
    )
    resolved, dependencies, _ = engine.resolve(Market.CN, selected)
    result = engine.score(
        pd.DataFrame(
            {
                "symbol": ["keep", "drop"],
                "ret_1d": [2.0, None],
                "hist_vol_20": [None, 5.0],
            }
        ),
        resolved,
        dependencies,
    )
    assert [row.symbol for row in result.rows] == ["keep"]
    assert result.rows[0].coverage_ratio == pytest.approx(0.6)
    assert result.rows[0].raw_score == pytest.approx(2.0)
    assert result.rows[0].contributions == {
        "ret_1d": pytest.approx(2.0),
        "hist_vol_20": 0.0,
    }

    neutral = definition(
        terms=(term("ret_1d", 0.6), term("hist_vol_20", 0.4)),
        missing=CompositeMissingKind.NEUTRAL_SCORE,
    )
    resolved, dependencies, _ = engine.resolve(Market.CN, neutral)
    result = engine.score(
        pd.DataFrame(
            {"symbol": ["A"], "ret_1d": [2.0], "hist_vol_20": [None]}
        ),
        resolved,
        dependencies,
    )
    assert result.rows[0].raw_score == pytest.approx(1.2)
    assert result.rows[0].contributions["hist_vol_20"] == 0.0

    coverage_filter = neutral.model_copy(
        update={
            "filters": CompositeFilterPolicy(minimum_factor_coverage=0.7)
        }
    )
    result = engine.score(
        pd.DataFrame(
            {"symbol": ["A"], "ret_1d": [2.0], "hist_vol_20": [None]}
        ),
        coverage_filter,
        dependencies,
    )
    assert result.rows == []
