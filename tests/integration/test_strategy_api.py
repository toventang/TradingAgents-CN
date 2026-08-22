import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_strategy_api_full_flow():
    # 1. Create strategy
    res = client.post("/api/strategies", json={
        "name": "API Test Strategy",
        "description": "Integration test",
        "parameters": {"weights": {"ret_1d": 1.0}},
        "rules": {"top_k": 3},
        "universe_symbols": ["000001.SZ", "600000.SH"]
    }, headers={"X-User-ID": "api_user"})

    assert res.status_code == 201
    data = res.json()
    strat_id = data["strategy"]["strategy_id"]

    # 2. List strategies
    res_list = client.get("/api/strategies", headers={"X-User-ID": "api_user"})
    assert res_list.status_code == 200
    assert any(s["strategy_id"] == strat_id for s in res_list.json())

    # 3. Publish strategy
    res_pub = client.post(f"/api/strategies/{strat_id}/publish", json={
        "commit_message": "Publish v1"
    }, headers={"X-User-ID": "api_user"})
    assert res_pub.status_code == 200
    assert res_pub.json()["is_published"] is True

    # 4. Signal evaluation
    res_eval = client.post("/api/strategies/signals/evaluate", json={
        "strategy_id": strat_id,
        "factor_values": {
            "000001.SZ": {"ret_1d": 0.05},
            "600000.SH": {"ret_1d": 0.01}
        }
    }, headers={"X-User-ID": "api_user"})

    assert res_eval.status_code == 200
    signals = res_eval.json()
    assert len(signals) == 2
