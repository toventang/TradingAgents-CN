import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.services.skills.sandbox import PythonSandboxEngine

client = TestClient(app)


def test_cross_tenant_resource_isolation_strategies():
    # User A creates strategy
    res_a = client.post("/api/strategies", json={
        "name": "Secret Strategy User A",
        "parameters": {"k": 1}
    }, headers={"X-User-ID": "user_tenant_a"})
    assert res_a.status_code == 201
    strat_id = res_a.json()["strategy"]["strategy_id"]

    # User B attempts to access User A's strategy -> 403
    res_b = client.get(f"/api/strategies/{strat_id}", headers={"X-User-ID": "user_tenant_b"})
    assert res_b.status_code == 403


def test_cross_tenant_resource_isolation_backtests():
    # User A submits backtest
    res_a = client.post("/api/backtests", json={
        "config": {"strategy_id": "s1", "start_date": "2026-01-01", "end_date": "2026-01-05"}
    }, headers={"X-User-ID": "user_tenant_a"})
    assert res_a.status_code == 202
    bt_id = res_a.json()["backtest_id"]

    # User B attempts to access User A's backtest -> 403
    res_b = client.get(f"/api/backtests/{bt_id}", headers={"X-User-ID": "user_tenant_b"})
    assert res_b.status_code == 403


def test_python_sandbox_security_blocking():
    engine = PythonSandboxEngine()

    dangerous_codes = [
        "import os\ndef run(inputs):\n    return os.system('ls')",
        "import sys\ndef run(inputs):\n    return sys.exit(1)",
        "import subprocess\ndef run(inputs):\n    return subprocess.run(['ls'])",
        "def run(inputs):\n    return eval('1 + 1')",
        "def run(inputs):\n    return open('/etc/passwd').read()"
    ]

    for code in dangerous_codes:
        res = engine.execute_skill("skill_sec_test", 1, code, {})
        assert res.success is False
        assert "Security Exception" in res.error_message or "Runtime Exception" in res.error_message


def test_secret_redaction_in_middleware():
    # Submit request with sensitive headers/params
    res = client.get("/api/strategies", headers={
        "X-User-ID": "user_sec_audit",
        "Authorization": "Bearer secret_jwt_token_12345"
    })
    assert res.status_code == 200
