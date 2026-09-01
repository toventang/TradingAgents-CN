from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.models.analysis import (
    AnalysisFactorContext,
    AnalysisModelReference,
    AnalysisProfileVersion,
)


NOW = datetime(2025, 6, 3, tzinfo=timezone.utc)


def version_payload(**updates):
    payload = {
        "profile_version_id": "profile-version-1",
        "profile_id": "profile-1",
        "user_id": "alice",
        "version": 1,
        "selected_analysts": ("market", "fundamentals"),
        "research_depth": "标准",
        "quick_model_ref": {"config_id": "model-config:quick"},
        "deep_model_ref": {"config_id": "model-config:deep"},
        "risk_preference": "balanced",
        "investment_horizon": "medium",
        "enabled_skill_versions": ("skill-risk:v1",),
        "factor_context": {
            "factor_ids": ("quality_composite", "ret_20d"),
            "summary_schema_version": "factor-summary-v1",
        },
        "strategy_context": "strategy-version-1",
        "debate_rounds": 2,
        "risk_debate_rounds": 1,
        "output_schema_version": "analysis-report-v1",
        "disclaimer_profile": "standard-cn-v1",
        "created_at": NOW,
        "created_by": "alice",
    }
    payload.update(updates)
    return payload


def test_complete_profile_contract_and_checksum_are_deterministic():
    first = AnalysisProfileVersion(**version_payload())
    second = AnalysisProfileVersion(**version_payload())
    assert first == second
    assert first.checksum == second.checksum
    assert first.factor_context.factor_ids == ("quality_composite", "ret_20d")
    assert first.enabled_skill_versions == ("skill-risk:v1",)


@pytest.mark.parametrize(
    "updates",
    [
        {"selected_analysts": ()},
        {"selected_analysts": ("market", "market")},
        {"selected_analysts": ("technical",)},
        {"research_depth": "超深"},
        {"investment_horizon": "intraday"},
        {"debate_rounds": 6},
        {"risk_debate_rounds": 6},
    ],
)
def test_closed_enums_nonempty_analysts_and_system_debate_caps(updates):
    with pytest.raises(ValidationError):
        AnalysisProfileVersion(**version_payload(**updates))


def test_model_references_cannot_copy_secrets():
    with pytest.raises(ValidationError, match="cannot contain credentials"):
        AnalysisModelReference(config_id="sk-proj-secret-material")
    with pytest.raises(ValidationError):
        AnalysisModelReference(config_id="model-config:quick", api_key="secret")


def test_factor_context_is_bounded_structured_summary_only():
    fifty = tuple(f"factor_{index}" for index in range(50))
    assert len(AnalysisFactorContext(factor_ids=fifty).factor_ids) == 50
    with pytest.raises(ValidationError):
        AnalysisFactorContext(factor_ids=fifty + ("factor_50",))
    with pytest.raises(ValidationError):
        AnalysisFactorContext(
            factor_ids=("ret_20d",),
            time_series={"ret_20d": [1, 2, 3]},
        )
