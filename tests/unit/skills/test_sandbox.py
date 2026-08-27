import pytest
from app.services.skills.sandbox import PythonSandboxEngine


def test_sandbox_valid_execution():
    engine = PythonSandboxEngine()
    code = """
def run(inputs):
    x = inputs.get('x', 0)
    return {'square': x ** 2, 'sqrt': math.sqrt(x)}
"""
    res = engine.execute_skill("skill_1", 1, code, {"x": 16})
    assert res.success is True
    assert res.result["square"] == 256
    assert res.result["sqrt"] == 4.0


def test_sandbox_forbidden_import_blocking():
    engine = PythonSandboxEngine()
    code = """
import os
def run(inputs):
    return os.listdir('.')
"""
    res = engine.execute_skill("skill_bad", 1, code, {})
    assert res.success is False
    assert "Security Exception" in res.error_message


def test_sandbox_missing_run_function():
    engine = PythonSandboxEngine()
    code = """
def foo(inputs):
    return inputs
"""
    res = engine.execute_skill("skill_no_run", 1, code, {})
    assert res.success is False
    assert "must define a callable function named 'run(inputs)'" in res.error_message
