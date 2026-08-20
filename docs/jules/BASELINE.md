# Jules validation baseline

Status: Established and verified by task J00.

## Environment details

- Starting Commit: 5331e6f4a1e223186c5a5acb609603d9ddd9ac10
- Python Version: Python 3.10.20
- Node Version: v22.22.1
- Yarn Version: 1.22.22

## Validation Commands & Curated Fast Test Paths

### 1. Import Validation
- Command: `bash scripts/jules/verify.sh imports`
- Status: PASS
- Output: Checked 310 Python files, 2757 imports, 0 errors.

### 2. Fast Backend Tests
- Command: `bash scripts/jules/verify.sh backend`
- Curated Paths:
  - `tests/config/`
  - `tests/middleware/test_trace_id.py`
  - `tests/test_code_normalization.py`
  - `tests/test_env_config.py`
- Status: PASS (10 passed in 0.71s)

### 3. Frontend Type-Check and Build
- Command: `bash scripts/jules/verify.sh frontend`
- Status: PASS (`vue-tsc --noEmit` and `vite build` completed successfully)

## CI Workflow
- File: `.github/workflows/jules-ci.yml`
- Workflow Name: `Jules Quality Gate`
- Jobs: `backend-quality`, `frontend-quality`

## Known Unrelated Issues / Baseline Observations
- `tests/unit/dataflows/test_unified_dataframe.py`: fails with `ModuleNotFoundError` (`tradingagents.dataflows.unified_dataframe` missing) when running raw `pytest tests/unit/`.
- `tests/unit/test_stocks_kline_news_api.py`: fails with `ModuleNotFoundError` (`app.routers.auth` missing) when running raw `pytest tests/unit/`.
- `tests/test_config_system.py::TestConfigCompat::test_load_settings`: fails due to missing `max_debate_rounds` key when MongoDB is unavailable.
- These unrelated legacy test failures are documented here and excluded from the fast deterministic CI gate.
