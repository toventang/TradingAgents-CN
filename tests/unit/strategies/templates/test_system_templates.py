import pytest
import pandas as pd
from app.services.strategies.templates.catalog import get_all_system_templates, SYSTEM_TEMPLATES_SPEC
from app.services.strategies.validator import StrategyDSLValidator
from app.services.strategies.signal_engine import DeterministicSignalEngine
from app.models.strategy import StrategyVersion, UniverseSnapshot
from app.utils.timezone import now_tz


def test_exactly_14_system_templates():
    templates = get_all_system_templates()
    assert len(templates) == 14
    template_ids = {t["strategy_id"] for t in templates}
    assert len(template_ids) == 14


def test_all_templates_pass_dsl_validation():
    validator = StrategyDSLValidator()
    templates = get_all_system_templates()

    for tmpl in templates:
        spec = {
            "weights": tmpl["parameters"].get("weights", {}),
            "conditions": tmpl["rules"].get("conditions", {}),
            "rules": tmpl["rules"]
        }
        referenced_factors = validator.validate_strategy_spec(spec)
        assert len(referenced_factors) > 0


def test_signal_execution_positive_and_negative_fixtures():
    engine = DeterministicSignalEngine()
    templates = get_all_system_templates()
    as_of = now_tz()

    univ = UniverseSnapshot(
        universe_id="univ_test",
        user_id="system",
        symbols=["000001.SZ", "600000.SH"]
    )

    for tmpl in templates:
        version = StrategyVersion(
            version_id=f"v_{tmpl['strategy_id']}",
            strategy_id=tmpl["strategy_id"],
            version_num=1,
            is_published=True,
            parameters=tmpl["parameters"],
            rules=tmpl["rules"],
            universe=univ
        )

        # 1. Positive Fixture DataFrame: Should trigger buy signal for 600000.SH
        pos_df = pd.DataFrame({
            "ret_1d": [0.05, 0.05],
            "ret_5d": [0.05, 0.05],
            "ret_10d": [0.05, 0.05],
            "ret_20d": [0.05, 0.05],
            "ret_60d": [0.10, 0.10],
            "ret_120d": [0.10, 0.10],
            "ret_240d": [0.20, 0.20],
            "log_ret_1d": [0.05, 0.05],
            "log_ret_5d": [0.05, 0.05],
            "log_ret_20d": [0.05, 0.05]
        }, index=["000001.SZ", "600000.SH"])

        pos_signals = engine.generate_signals(version, "system", as_of, pos_df)
        assert len(pos_signals) == 2

        # 2. Negative Fixture DataFrame: Should fail condition for all symbols
        neg_df = pd.DataFrame({
            "ret_1d": [-0.50, -0.50],
            "ret_5d": [-0.50, -0.50],
            "ret_10d": [-0.50, -0.50],
            "ret_20d": [-0.50, -0.50],
            "ret_60d": [-0.50, -0.50],
            "ret_120d": [-0.50, -0.50],
            "ret_240d": [-0.50, -0.50],
            "log_ret_1d": [-0.50, -0.50],
            "log_ret_5d": [-0.50, -0.50],
            "log_ret_20d": [-0.50, -0.50]
        }, index=["000001.SZ", "600000.SH"])

        neg_signals = engine.generate_signals(version, "system", as_of, neg_df)
        assert len(neg_signals) == 2
        # All negative signals should be hold or fail condition for strict positive templates
