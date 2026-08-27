import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_backtest_api_submission_and_isolation():
    # 1. Submit backtest
    payload = {
        "config": {
            "strategy_id": "strat_001",
            "version_num": 1,
            "start_date": "2026-01-01",
            "end_date": "2026-01-05",
            "initial_capital": 1000000.0
        }
    }

    res_sub = client.post("/api/backtests", json=payload, headers={"X-User-ID": "user_a"})
    assert res_sub.status_code == 202
    data = res_sub.json()
    bt_id = data["backtest_id"]

    # 2. Query backtest by owner -> 200
    res_get = client.get(f"/api/backtests/{bt_id}", headers={"X-User-ID": "user_a"})
    assert res_get.status_code == 200
    assert res_get.json()["backtest_id"] == bt_id

    # 3. Query backtest by another user -> 403 Forbidden
    res_other = client.get(f"/api/backtests/{bt_id}", headers={"X-User-ID": "user_b"})
    assert res_other.status_code == 403

    # 4. Query backtest by admin user -> 200 OK
    res_admin = client.get(f"/api/backtests/{bt_id}", headers={"X-User-ID": "user_b", "X-User-Role": "admin"})
    assert res_admin.status_code == 200
    assert res_admin.json()["backtest_id"] == bt_id
