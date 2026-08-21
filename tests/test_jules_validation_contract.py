from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10; pytest installs tomli on that runtime.
    import tomli as tomllib


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_dev_extra_declares_supported_pytest_versions():
    with (REPOSITORY_ROOT / "pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream)["project"]

    dependencies = project["optional-dependencies"]["dev"]
    assert "pytest==8.4.2" in dependencies
    assert "pytest-asyncio==1.2.0" in dependencies


def test_setup_installs_the_dev_extra_instead_of_requirements_lock():
    setup = (REPOSITORY_ROOT / "scripts/jules/setup.sh").read_text(encoding="utf-8")
    assert 'python -m pip install -e ".[dev]"' in setup
    assert "requirements-lock.txt" not in setup


def test_pull_request_workflow_uses_stable_validation_entry_points():
    workflow = (
        REPOSITORY_ROOT / ".github/workflows/jules-quality-gate.yml"
    ).read_text(encoding="utf-8")
    assert "pull_request:" in workflow
    assert "bash scripts/jules/verify.sh imports" in workflow
    assert "bash scripts/jules/verify.sh fast" in workflow
    assert "bash scripts/jules/verify.sh frontend" in workflow
