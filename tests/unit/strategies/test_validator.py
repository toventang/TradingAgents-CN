from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from app.models.symbol import Market
from app.services.strategies.validator import (
    DSLValidationError,
    SkillVersionAccess,
    StrategyDSLValidator,
)
from tests.unit.strategies.dsl_fixtures import valid_definition


NOW = datetime(2025, 6, 3, 8, tzinfo=timezone.utc)


def error_codes(report):
    return {item.code for item in report.errors}


def test_valid_closed_dsl_freezes_factor_and_skill_dependencies():
    definition = valid_definition(
        analysis={
            "skill_version_ids": ["skill-version-1"],
            "require_explanation": True,
        }
    )
    skill = SkillVersionAccess(
        skill_version_id="skill-version-1",
        skill_id="risk-review",
        version=2,
        checksum="c" * 64,
        status="published",
        user_id="system",
        visibility="system",
    )
    report = StrategyDSLValidator(clock=lambda: NOW).validate(
        definition,
        market=Market.CN,
        user_id="alice",
        skills={skill.skill_version_id: skill},
    )

    assert report.valid
    assert report.as_lifecycle_result().valid
    assert [(item.factor_id, item.version) for item in report.factor_dependencies] == [
        ("ret_1d", 1)
    ]
    assert [(item.skill_id, item.version) for item in report.skill_dependencies] == [
        ("risk-review", 2)
    ]


def test_rejects_unknown_factor_operator_missing_exit_and_illegal_timing():
    unknown = valid_definition()
    unknown["features"][0]["factor_id"] = "unknown_factor_123"
    unknown["entry"]["condition"]["left"]["factor_id"] = "unknown_factor_123"
    unknown["entry"]["ranking"]["factors"][0]["factor"]["factor_id"] = (
        "unknown_factor_123"
    )
    report = StrategyDSLValidator().validate(
        unknown, market=Market.CN, user_id="alice"
    )
    assert "UNKNOWN_FACTOR_VERSION" in error_codes(report)

    invalid_shape = valid_definition()
    invalid_shape["entry"]["condition"]["operator"] = "execute_python"
    invalid_shape["exit"] = {}
    invalid_shape["execution"]["execution_time"] = "same_close"
    report = StrategyDSLValidator().validate(
        invalid_shape, market=Market.CN, user_id="alice"
    )
    assert "DSL_SCHEMA_INVALID" in error_codes(report)
    with pytest.raises(DSLValidationError):
        StrategyDSLValidator().validate_or_raise(
            invalid_shape, market=Market.CN, user_id="alice"
        )

    illegal_timing = valid_definition()
    illegal_timing["execution"]["execution_time"] = "same_close"
    illegal_timing["execution"]["price"] = "close"
    report = StrategyDSLValidator().validate(
        illegal_timing, market=Market.CN, user_id="alice"
    )
    assert "ILLEGAL_EXECUTION_TIMING" in error_codes(report)


def test_rejects_tree_limits_impossible_conflicts_and_insufficient_history():
    leaf = {
        "type": "compare",
        "left": {"kind": "factor", "factor_id": "ret_1d", "version": 1},
        "operator": "gt",
        "right": {"kind": "constant", "value": 0},
    }
    nested = deepcopy(leaf)
    for _ in range(3):
        nested = {"type": "not", "child": nested}
    too_deep = valid_definition()
    too_deep["entry"]["condition"] = nested
    report = StrategyDSLValidator(max_depth=3).validate(
        too_deep, market=Market.CN, user_id="alice"
    )
    assert "CONDITION_TREE_TOO_DEEP" in error_codes(report)

    impossible = valid_definition()
    impossible["entry"]["condition"] = {
        "type": "all",
        "children": [
            {
                "type": "compare",
                "left": {"kind": "factor", "factor_id": "ret_1d"},
                "operator": "gt",
                "right": {"kind": "constant", "value": 0.1},
            },
            {
                "type": "compare",
                "left": {"kind": "factor", "factor_id": "ret_1d"},
                "operator": "lt",
                "right": {"kind": "constant", "value": 0},
            },
        ],
    }
    report = StrategyDSLValidator().validate(
        impossible, market=Market.CN, user_id="alice"
    )
    assert "IMPOSSIBLE_CONDITION" in error_codes(report)

    history = valid_definition()
    history["entry"]["condition"] = {
        "type": "changed",
        "factor": {"kind": "factor", "factor_id": "ret_1d"},
        "periods": 5,
        "operator": "gt",
        "threshold": 0.1,
    }
    report = StrategyDSLValidator().validate(
        history, market=Market.CN, user_id="alice"
    )
    assert "INSUFFICIENT_DECLARED_HISTORY" in error_codes(report)


def test_rejects_private_or_unpublished_skill_and_portfolio_conflict():
    definition = valid_definition(
        analysis={"skill_version_ids": ["private-draft"]},
        portfolio={
            "weighting": "equal_weight",
            "max_positions": 1,
            "max_position_weight": 0.2,
            "max_industry_weight": 0.2,
            "min_cash_ratio": 0,
        },
    )
    skill = SkillVersionAccess(
        skill_version_id="private-draft",
        skill_id="private-skill",
        version=1,
        checksum="d" * 64,
        status="draft",
        user_id="bob",
        visibility="private",
    )
    report = StrategyDSLValidator().validate(
        definition,
        market=Market.CN,
        user_id="alice",
        skills={skill.skill_version_id: skill},
    )
    assert {
        "SKILL_VERSION_NOT_PUBLISHED",
        "SKILL_VERSION_FORBIDDEN",
        "PORTFOLIO_CAPACITY_CONFLICT",
    }.issubset(error_codes(report))
