import pytest
from app.models.risk import RiskConfig
from app.services.risk.pre_trade import PreTradeRiskService


def test_pre_trade_risk_service_blocking():
    service = PreTradeRiskService()
    config = RiskConfig(block_limit_up_buy=True)

    trades = [
        {"symbol": "600000.SH", "side": "buy", "quantity": 1000, "price": 10.0, "is_limit_up": True}
    ]

    res = service.check_pre_trade_orders(
        config=config,
        total_equity=100000.0,
        cash=100000.0,
        positions={},
        proposed_trades=trades
    )

    assert res["is_blocked"] is True
    assert len(res["blocked_orders"]) == 1
    assert len(res["approved_orders"]) == 0
