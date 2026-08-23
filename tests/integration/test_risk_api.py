import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_risk_api_pre_trade_check():
    payload = {
        "config": {
            "max_stock_weight": 0.10,
            "block_limit_up_buy": True
        },
        "total_equity": 100000.0,
        "cash": 100000.0,
        "positions": {},
        "proposed_trades": [
            {"symbol": "600000.SH", "side": "buy", "quantity": 100, "price": 10.0}
        ]
    }

    res = client.post("/api/risk/pre-trade/check", json=payload, headers={"X-User-ID": "risk_user"})
    assert res.status_code == 200
    data = res.json()
    assert "evaluation" in data
    assert "is_blocked" in data

    # Query audit logs
    res_logs = client.get("/api/risk/audit-logs", headers={"X-User-ID": "risk_user"})
    assert res_logs.status_code == 200
    assert isinstance(res_logs.json(), list)
