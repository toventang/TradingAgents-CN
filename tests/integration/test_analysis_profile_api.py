from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI, HTTPException

from app.repositories.strategy_repository import StrategyRepository
from app.routers.analysis_profiles import get_analysis_profile_api_service, router
from app.routers.auth_db import get_current_user
from app.services.analysis_profiles import AnalysisProfileService
from app.services.strategies.analysis_profile_api import AnalysisProfileApiService
from tests.integration.strategy_api_helpers import asgi_request
from tests.strategy_fakes import FakeDatabase


pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
NOW = datetime(2025, 6, 3, 8, tzinfo=timezone.utc)


async def make_api():
    database = FakeDatabase()
    repository = StrategyRepository(database)
    identifiers = iter(f"profile-api-id-{index}" for index in range(1, 100))
    lifecycle = AnalysisProfileService(
        repository,
        clock=lambda: NOW,
        id_factory=lambda: next(identifiers),
    )
    service = AnalysisProfileApiService(repository=repository, lifecycle=lifecycle)
    active_user = {"id": "alice"}
    app = FastAPI()
    app.include_router(router, prefix="/api")

    async def user_override():
        if active_user["id"] is None:
            raise HTTPException(401, detail="Not authenticated")
        return active_user

    app.dependency_overrides[get_current_user] = user_override
    app.dependency_overrides[get_analysis_profile_api_service] = lambda: service
    return app, database, repository, active_user


def profile_payload(**updates):
    payload = {
        "name": "My research profile",
        "selected_analysts": ["market", "fundamentals", "news"],
        "research_depth": "标准",
        "quick_model_ref": {"config_id": "model-config:quick"},
        "deep_model_ref": {"config_id": "model-config:deep"},
        "risk_preference": "balanced",
        "investment_horizon": "medium",
        "enabled_skill_versions": ["skill-news:v1"],
        "factor_context": {"factor_ids": ["quality_composite", "ret_20d"]},
        "debate_rounds": 2,
        "risk_debate_rounds": 1,
        "output_schema_version": "analysis-report-v1",
        "disclaimer_profile": "standard-cn-v1",
    }
    payload.update(updates)
    return payload


async def test_profile_crud_versions_publish_and_owner_isolation():
    app, _, _, active_user = await make_api()
    active_user["id"] = None
    code, _ = await asgi_request(app, "GET", "/api/analysis-profiles")
    assert code == 401

    active_user["id"] = "alice"
    code, created = await asgi_request(
        app, "POST", "/api/analysis-profiles", profile_payload()
    )
    assert code == 201, created
    profile_id = created["profile"]["profile_id"]
    version_id = created["version"]["profile_version_id"]
    checksum = created["version"]["checksum"]

    code, page = await asgi_request(app, "GET", "/api/analysis-profiles")
    assert code == 200 and page["total"] == 1
    code, detail = await asgi_request(
        app, "GET", f"/api/analysis-profiles/{profile_id}"
    )
    assert code == 200 and len(detail["versions"]) == 1

    code, changed = await asgi_request(
        app,
        "PUT",
        f"/api/analysis-profiles/{profile_id}/versions/{version_id}",
        {
            "expected_checksum": checksum,
            "changes": {"research_depth": "深度", "debate_rounds": 3},
            "change_summary": "deeper",
        },
    )
    assert code == 200, changed
    assert changed["research_depth"] == "深度"

    code, published = await asgi_request(
        app,
        "POST",
        f"/api/analysis-profiles/{profile_id}/versions/{version_id}/publish",
    )
    assert code == 200 and published["status"] == "published"
    code, second = await asgi_request(
        app,
        "POST",
        f"/api/analysis-profiles/{profile_id}/versions",
        {"change_summary": "v2"},
    )
    assert code == 200 and second["version"] == 2

    active_user["id"] = "bob"
    code, body = await asgi_request(
        app, "GET", f"/api/analysis-profiles/{profile_id}"
    )
    assert code == 404
    assert body["detail"]["code"] == "ANALYSIS_PROFILE_NOT_FOUND"
    code, _ = await asgi_request(app, "DELETE", f"/api/analysis-profiles/{profile_id}")
    assert code == 404

    active_user["id"] = "alice"
    code, archived = await asgi_request(
        app, "DELETE", f"/api/analysis-profiles/{profile_id}"
    )
    assert code == 200 and archived["archived_at"] is not None
    code, page = await asgi_request(app, "GET", "/api/analysis-profiles")
    assert code == 200 and page["total"] == 0


async def test_profile_api_rejects_secrets_bounds_and_invalid_draft_changes():
    app, _, _, _ = await make_api()
    code, body = await asgi_request(
        app,
        "POST",
        "/api/analysis-profiles",
        profile_payload(quick_model_ref={"config_id": "sk-proj-secret"}),
    )
    assert code == 422
    assert "sk-proj-secret" not in str(body)

    code, body = await asgi_request(
        app,
        "POST",
        "/api/analysis-profiles",
        profile_payload(factor_context={"factor_ids": [f"factor_{i}" for i in range(51)]}),
    )
    assert code == 422

    code, created = await asgi_request(
        app, "POST", "/api/analysis-profiles", profile_payload()
    )
    profile_id = created["profile"]["profile_id"]
    version_id = created["version"]["profile_version_id"]
    code, body = await asgi_request(
        app,
        "PUT",
        f"/api/analysis-profiles/{profile_id}/versions/{version_id}",
        {
            "expected_checksum": created["version"]["checksum"],
            "changes": {"api_key": "must-not-be-accepted"},
        },
    )
    assert code == 422
    assert body["detail"]["code"] == "ANALYSIS_PROFILE_INVALID"

    code, body = await asgi_request(
        app,
        "PUT",
        f"/api/analysis-profiles/{profile_id}/versions/{version_id}",
        {
            "expected_checksum": created["version"]["checksum"],
            "changes": {"quick_model_ref": {"config_id": "sk-proj-secret"}},
        },
    )
    assert code == 422
    assert "sk-proj-secret" not in str(body)
