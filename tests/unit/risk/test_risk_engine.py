import pytest
from app.models.risk import RiskConfig, RiskDecision, RiskSeverity, RiskAction
from app.services.risk.engine import RiskEvaluationEngine


def test_risk_engine_position_concentration_and_t1():
    engine = RiskEvaluationEngine()
    config = RiskConfig(
        max_stock_weight=0.10,
        max_sector_weight=0.30,
        enforce_t_plus_1=True,
        block_limit_up_buy=True
    )

    positions = {
        "600000.SH": {
            "quantity": 1000,
            "market_value": 200000.0,  # 20% of 1M -> exceeds 10%
            "sector": "Banking",
            "t_plus_1_available_qty": 500,
            "is_limit_up": False
        }
    }

    trades = [
        {"symbol": "600000.SH", "side": "sell", "quantity": 800, "price": 200.0, "sector": "Banking"},
        {"symbol": "000001.SZ", "side": "buy", "quantity": 100, "price": 10.0, "sector": "Banking", "is_limit_up": True}
    ]

    res = engine.evaluate_portfolio(
        config=config,
        total_equity=1000000.0,
        cash=800000.0,
        positions=positions,
        proposed_trades=trades
    )

    assert res.decision == RiskDecision.REJECTED
    assert len(res.violations) >= 2

    # Check T+1 violation
    t1_violation = next(v for v in res.violations if v.rule_id == "RULE_T_PLUS_1")
    assert t1_violation.severity == RiskSeverity.CRITICAL

    # Check Limit Up Buy violation
    limit_up_violation = next(v for v in res.violations if v.rule_id == "RULE_LIMIT_UP_BUY")
    assert limit_up_violation.severity == RiskSeverity.CRITICAL


def test_risk_engine_clean_portfolio():
    engine = RiskEvaluationEngine()
    config = RiskConfig(max_stock_weight=0.20, max_sector_weight=0.50)

    positions = {
        "000001.SZ": {"quantity": 1000, "market_value": 10000.0, "sector": "Banking", "t_plus_1_available_qty": 1000}
    }

    res = engine.evaluate_portfolio(
        config=config,
        total_equity=100000.0,
        cash=90000.0,
        positions=positions
    )

    assert res.decision == RiskDecision.APPROVED
    assert len(res.violations) == 0
