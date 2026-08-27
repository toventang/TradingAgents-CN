import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_notification_api_flow():
    # 1. Get default preferences
    res_get = client.get("/api/notifications/preferences", headers={"X-User-ID": "api_notif_user"})
    assert res_get.status_code == 200
    pref_data = res_get.json()
    assert pref_data["user_id"] == "api_notif_user"

    # 2. Update preferences
    pref_data["channels"]["webhook"]["target_address"] = "https://hooks.example.com/alerts"
    res_put = client.put("/api/notifications/preferences", json=pref_data, headers={"X-User-ID": "api_notif_user"})
    assert res_put.status_code == 200
    assert res_put.json()["channels"]["webhook"]["target_address"] == "https://hooks.example.com/alerts"

    # 3. Test Webhook Ping
    res_test = client.post("/api/notifications/webhooks/test", json={
        "target_url": "https://hooks.example.com/alerts"
    }, headers={"X-User-ID": "api_notif_user"})
    assert res_test.status_code == 200

    # 4. List logs
    res_logs = client.get("/api/notifications/logs", headers={"X-User-ID": "api_notif_user"})
    assert res_logs.status_code == 200
    assert isinstance(res_logs.json(), list)
