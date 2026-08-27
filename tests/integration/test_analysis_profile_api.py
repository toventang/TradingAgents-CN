import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_analysis_profile_api_flow():
    # 1. Create Profile
    res = client.post("/api/analysis-profiles", json={
        "name": "Custom Profile",
        "description": "API Test",
        "depth": "deep",
        "risk_preference": "aggressive"
    }, headers={"X-User-ID": "profile_user"})

    assert res.status_code == 201
    data = res.json()
    pid = data["profile"]["profile_id"]

    # 2. Get Profile
    res_get = client.get(f"/api/analysis-profiles/{pid}", headers={"X-User-ID": "profile_user"})
    assert res_get.status_code == 200
    assert res_get.json()["profile"]["name"] == "Custom Profile"

    # 3. Resolve Profile
    res_res = client.post("/api/analysis-profiles/resolve", json={
        "profile_id": pid
    }, headers={"X-User-ID": "profile_user"})

    assert res_res.status_code == 200
    assert res_res.json()["depth"] == "deep"
