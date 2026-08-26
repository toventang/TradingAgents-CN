import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_campaign_api_full_flow():
    # 1. Create Campaign draft
    payload = {
        "name": "API Campaign",
        "description": "Test",
        "strategy_id": "strat_api_1",
        "strategy_version_num": 1,
        "portfolio_id": "port_api_1",
        "initial_allocation_cash": 100000.0,
        "start_date": "2026-12-31"
    }

    res_create = client.post("/api/campaigns", json=payload, headers={"X-User-ID": "camp_api_user"})
    assert res_create.status_code == 201
    data = res_create.json()
    cid = data["campaign"]["campaign_id"]

    # 2. Get Campaign detail
    res_get = client.get(f"/api/campaigns/{cid}", headers={"X-User-ID": "camp_api_user"})
    assert res_get.status_code == 200
    assert res_get.json()["name"] == "API Campaign"

    # 3. List campaigns
    res_list = client.get("/api/campaigns", headers={"X-User-ID": "camp_api_user"})
    assert res_list.status_code == 200
    assert len(res_list.json()) >= 1

    # 4. Get Performance
    res_perf = client.get(f"/api/campaigns/{cid}/performance", headers={"X-User-ID": "camp_api_user"})
    assert res_perf.status_code == 200
    assert "metrics" in res_perf.json()
