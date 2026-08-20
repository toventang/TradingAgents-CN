# Jules validation baseline

Status: Established by task J00.

## Environment Specifications

- **Python Version**: Python 3.10+ (System / .venv)
- **Node.js Version**: Node.js 20+
- **Yarn Version**: 1.22.22 (Classic)
- **CI Workflow Name**: `PR Quality Gate` (`.github/workflows/pr-quality.yml`)

## Dependency & Test Configuration

- `pyproject.toml` contains `test` and `dev` optional dependency groups with `pytest>=8.0.0` and `pytest-asyncio>=0.23.0`.
- `tests/pytest.ini` defines `integration` and `external` markers and skips them by default (`-m "not integration and not external"`).
- `scripts/jules/verify.sh` provides standard validation commands:
  - `bash scripts/jules/verify.sh imports`: Python static import validation (`scripts/validation/check_imports.py`).
  - `bash scripts/jules/verify.sh backend`: Curated unit tests (`tests/unit/`).
  - `bash scripts/jules/verify.sh frontend`: Frontend type-check (`yarn --cwd frontend type-check`) and build (`yarn --cwd frontend build`).

## Baseline Execution Results

1. **Import Validation**: `bash scripts/jules/verify.sh imports` — **PASSED**
2. **Backend Unit Tests**: `bash scripts/jules/verify.sh backend` — **PASSED**
3. **Frontend Validation**: `bash scripts/jules/verify.sh frontend` — **PASSED**

## Unrelated / Known Failure Log

- No pre-existing baseline failures observed in fast-gate suites (`imports`, `backend tests/unit/`, `frontend`).
