"""Known non-hermetic tests excluded from the pull-request fast gate.

Keep this inventory explicit: broad filename guesses can hide deterministic tests.  A
listed test retains all of its assertions and can be run deliberately with
``pytest -m external`` (or ``-m integration`` for the integration directory) in a
prepared environment.
"""

from fnmatch import fnmatch


INTEGRATION_PATTERNS = (
    "tests/integration/*.py",
)

# Exact paths make changes reviewable and prevent a newly added test from being
# silently classified as external merely because of its name.
EXTERNAL_TESTS = {
    # Live MongoDB/Redis checks.
    "tests/quick_redis_test.py": "requires a reachable Redis instance",
    "tests/test_redis_performance.py": "benchmarks a reachable Redis instance",
    "tests/test_mongodb_check.py": "queries a reachable MongoDB instance",
    "tests/test_mongodb_connection.py": "connects to a local MongoDB instance",
    "tests/test_mongodb_save.py": "writes to a reachable MongoDB instance",
    "tests/test_query.py": "queries a local MongoDB instance",
    "tests/test_system_simple.py": "checks local MongoDB state",
    "tests/test_user_check.py": "queries users in a local MongoDB instance",
    "tests/verify_mongodb_data.py": "manually inspects MongoDB data",
    # Live market-data provider checks.
    "tests/test_tushare_integration.py": "requires a Tushare token and live API",
    "tests/test_finnhub_connection.py": "requires a Finnhub key and live API",
    "tests/test_finnhub_fundamentals.py": "requires a Finnhub key and live API",
    "tests/test_finnhub_hk.py": "requires a Finnhub key and live API",
    "tests/test_akshare_api.py": "calls the live AkShare provider",
    "tests/test_akshare_direct.py": "calls the live AkShare provider",
    "tests/test_akshare_performance.py": "benchmarks the live AkShare provider",
    "tests/test_baostock_quick.py": "calls the live BaoStock provider",
    "tests/test_all_apis.py": "probes multiple live market-data APIs",
    "tests/test_analysis_with_apis.py": "runs analysis against live APIs",
    "tests/test_data_depth_levels.py": "compares live market-data responses",
    # Live LLM/provider checks.
    "tests/test_deepseek_integration.py": "requires live DeepSeek credentials",
    "tests/test_deepseek_cost_calculation.py": "contains an optional live DeepSeek call",
    "tests/test_gemini_25_pro.py": "requires live Gemini credentials",
    "tests/test_gemini_final.py": "requires live Gemini credentials",
    "tests/test_gemini_simple.py": "requires live Gemini credentials",
    "tests/final_gemini_test.py": "requires live Gemini credentials",
    "tests/testgoogle.py": "requires live Google model credentials",
    "tests/test_llm_tool_call.py": "requires a live configured LLM",
    "tests/test_news_analyst_integration.py": "requires live news and LLM providers",
    "tests/test_risk_assessment.py": "contains a live LLM integration stage",
    "tests/test_workflow_integration.py": "runs the live analysis workflow",
    # Tests that expect a separately running application or manual observation.
    "tests/test_amplitude_api.py": "requires a running backend",
    "tests/test_analysis_result.py": "requires a running backend and persisted results",
    "tests/test_api_analysis.py": "requires a running backend and configured services",
    "tests/test_api_format.py": "requires a running backend",
    "tests/test_async_analysis.py": "requires a running backend and analysis worker",
    "tests/test_batch_analysis_planA.py": "requires a running backend and analysis worker",
    "tests/test_decision_data.py": "requires a running backend, credentials, and persisted data",
    "tests/test_conversion.py": "requires local Pandoc/wkhtmltopdf and writes manual artifacts",
    "tests/test_existing_results.py": "requires a running backend and persisted data",
    "tests/test_fixed_analysis.py": "requires a running backend and analysis worker",
    "tests/test_frontend_backend_integration.py": "requires running frontend and backend",
    "tests/test_industries_api.py": "requires a running backend",
    "tests/test_industry_screening_fix.py": "requires a running backend and database",
    "tests/test_login_api.py": "requires a running backend",
    "tests/test_middleware.py": "requires a running backend",
    "tests/test_model_config.py": "requires a running backend",
    "tests/test_non_blocking.py": "requires a running backend and analysis worker",
    "tests/test_progress_steps.py": "requires a running backend and analysis worker",
    "tests/test_quick_async.py": "requires a running backend and analysis worker",
    "tests/test_quick_fix.py": "requires a running backend and analysis worker",
    "tests/test_real_estate_api.py": "requires a running backend",
    "tests/test_reports_api.py": "requires a running backend and persisted reports",
    "tests/test_reports_fix.py": "requires a running backend and persisted reports",
    "tests/test_screening_fix.py": "requires a running backend and database",
    "tests/test_summary_recommendation.py": "requires a running backend and persisted analysis",
    "tests/test_web_api_akshare.py": "requires a running backend and live AkShare",
    "tests/test_web_interface.py": "requires a running web application",
    "tests/test_frontend_display.py": "is a manual browser display check",
    "tests/test_detailed_progress_display.py": "is a manual progress display check",
    "tests/test_time_estimation_display.py": "is a manual progress timing check",
}


def classify_test_path(relative_path: str) -> str | None:
    """Return the pytest marker for a repository-relative POSIX path."""
    normalized = relative_path.replace("\\", "/")
    if any(fnmatch(normalized, pattern) for pattern in INTEGRATION_PATTERNS):
        return "integration"
    if normalized in EXTERNAL_TESTS:
        return "external"
    return None
