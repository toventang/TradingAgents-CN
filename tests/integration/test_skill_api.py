import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_skill_api_creation_and_sandbox_execution():
    # 1. Create custom skill
    code = "def run(inputs):\n    v = inputs.get('val', 0)\n    return {'result': v * 2}"
    payload = {
        "name": "Multiplier Skill",
        "description": "Multiplies val by 2",
        "skill_type": "market",
        "code": code
    }

    res_create = client.post("/api/skills", json=payload, headers={"X-User-ID": "skill_user_api"})
    assert res_create.status_code == 201
    data = res_create.json()
    sk_id = data["skill"]["skill_id"]

    # 2. Get skill detail
    res_get = client.get(f"/api/skills/{sk_id}", headers={"X-User-ID": "skill_user_api"})
    assert res_get.status_code == 200
    assert res_get.json()["skill"]["name"] == "Multiplier Skill"

    # 3. Execute skill
    res_exec = client.post(f"/api/skills/{sk_id}/execute", json={"kwargs": {"val": 21}}, headers={"X-User-ID": "skill_user_api"})
    assert res_exec.status_code == 200
    exec_data = res_exec.json()
    assert exec_data["success"] is True
    assert exec_data["result"]["result"] == 42
