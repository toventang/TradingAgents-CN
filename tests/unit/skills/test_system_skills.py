import pytest
from app.services.skills.system_skills import get_all_system_skills
from app.services.skills.sandbox import PythonSandboxEngine


def test_system_skills_count_and_sandbox_execution():
    skills = get_all_system_skills()
    assert len(skills) >= 6

    engine = PythonSandboxEngine()

    for sk in skills:
        code = sk["code"].strip()
        skill_id = sk["skill_id"]

        # Run each system skill in sandbox with dummy inputs
        res = engine.execute_skill(
            skill_id=skill_id,
            version_num=1,
            code=code,
            kwargs={"returns_20d": 0.08, "volatility_20d": 0.15, "roe": 0.20, "close": 15.0, "ma_20": 12.0, "ma_60": 10.0}
        )

        assert res.success is True, f"System skill {skill_id} failed: {res.error_message}"
        assert res.result is not None
