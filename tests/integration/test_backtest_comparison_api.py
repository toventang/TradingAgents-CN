import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_backtest_comparison_api_flow():
    # 1. Submit two backtests
    payload1 = {"config": {"strategy_id": "s1", "start_date": "2026-01-01", "end_date": "2026-01-05"}}
    payload2 = {"config": {"strategy_id": "s2", "start_date": "2026-01-01", "end_date": "2026-01-05"}}

    r1 = client.post("/api/backtests", json=payload1, headers={"X-User-ID": "cmp_user"})
    r2 = client.post("/api/backtests", json=payload2, headers={"X-User-ID": "cmp_user"})

    bt_id1 = r1.json()["backtest_id"]
    bt_id2 = r2.json()["backtest_id"]

    # 2. Compare backtests
    res = client.post("/api/backtests/compare", json={"backtest_ids": [bt_id1, bt_id2]}, headers={"X-User-ID": "cmp_user"})
    assert res.status_code == 200
    data = res.json()

    assert "summary" in data
    assert len(data["summary"]) == 2
    assert "aligned_equity_curve" in data
