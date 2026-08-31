from __future__ import annotations

import pytest

from app.repositories.factor_repository import FactorRepository
from app.routers.factors import get_composite_factor_service
from app.services.factors.composites import CompositeFactorService
from tests.integration.test_factor_api import asgi_request, make_api


pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def payload(**updates):
    result = {
        "name": "Quality momentum",
        "description": "Versioned structured composite",
        "market": "CN",
        "definition": {
            "terms": [
                {
                    "factor": {"factor_id": "ret_1d", "version": 1},
                    "weight": 2,
                    "transform": {"kind": "zscore"},
                },
                {
                    "factor": {"factor_id": "hist_vol_20", "version": 1},
                    "weight": -1,
                    "transform": {"kind": "robust_zscore"},
                },
            ],
            "auto_direction": True,
            "neutralize": "industry_and_market_cap",
            "arithmetic": "weighted_sum",
            "missing": "renormalize_weights",
            "filters": {
                "minimum_factor_coverage": 0.6,
                "minimum_listing_days": 60,
                "exclude_st": True,
                "exclude_delisting": True,
                "exclude_suspended": True,
            },
        },
    }
    result.update(updates)
    return result


async def configured_api(monkeypatch):
    app, database, _, active_user = await make_api(monkeypatch)
    service = CompositeFactorService(FactorRepository(database))
    app.dependency_overrides[get_composite_factor_service] = lambda: service
    return app, database, active_user


async def test_composite_draft_publish_new_version_and_owner_isolation(monkeypatch):
    app, database, active_user = await configured_api(monkeypatch)

    code, validated = await asgi_request(
        app,
        "POST",
        "/api/factors/validate",
        {"market": "CN", "definition": payload()["definition"]},
    )
    assert code == 200
    assert validated["valid"] is True
    assert sum(abs(term["weight"]) for term in validated["normalized_definition"]["terms"]) == pytest.approx(1.0)

    code, created = await asgi_request(app, "POST", "/api/factor-composites", payload())
    assert code == 201
    assert created["status"] == "draft"
    assert created["version"] == 1
    assert len(created["definition_checksum"]) == 64
    assert created["dependencies"][1]["effective_multiplier"] == -1
    assert sum(abs(term["weight"]) for term in created["definition"]["terms"]) == pytest.approx(1.0)

    updated_payload = payload(description="Updated draft only")
    code, updated = await asgi_request(
        app,
        "PUT",
        f"/api/factor-composites/{created['composite_id']}",
        updated_payload,
    )
    assert code == 200
    assert updated["version"] == 1
    assert updated["description"] == "Updated draft only"

    code, published = await asgi_request(
        app,
        "POST",
        f"/api/factor-composites/{created['composite_id']}/publish",
    )
    assert code == 200
    assert published["status"] == "published"
    immutable_checksum = published["definition_checksum"]

    code, conflict = await asgi_request(
        app,
        "POST",
        f"/api/factor-composites/{created['composite_id']}/publish",
    )
    assert code == 409
    assert conflict["detail"]["code"] == "COMPOSITE_STATE_CONFLICT"

    next_payload = payload(name="Quality momentum v2", description="New draft")
    code, next_draft = await asgi_request(
        app,
        "PUT",
        f"/api/factor-composites/{created['composite_id']}",
        next_payload,
    )
    assert code == 200
    assert next_draft["version"] == 2
    assert next_draft["status"] == "draft"
    documents = sorted(database["factor_composites"].documents, key=lambda item: item["version"])
    assert len(documents) == 2
    assert documents[0]["status"] == "published"
    assert documents[0]["definition_checksum"] == immutable_checksum
    assert documents[0]["name"] == "Quality momentum"
    index_names = {options.get("name") for _, options in database["factor_composites"].indexes}
    assert {
        "factor_composite_owner_id_version_unique",
        "factor_composite_owner_state_version",
    }.issubset(index_names)

    active_user["id"] = "other"
    code, body = await asgi_request(
        app,
        "PUT",
        f"/api/factor-composites/{created['composite_id']}",
        next_payload,
    )
    assert code == 404
    assert body["detail"]["code"] == "COMPOSITE_NOT_FOUND"
    code, body = await asgi_request(
        app,
        "POST",
        f"/api/factor-composites/{created['composite_id']}/publish",
    )
    assert code == 404
    assert body["detail"]["code"] == "COMPOSITE_NOT_FOUND"


async def test_composite_rejects_unavailable_versions_and_executable_shaped_fields(monkeypatch):
    app, database, _ = await configured_api(monkeypatch)
    invalid_version = payload()
    invalid_version["definition"]["terms"][0]["factor"]["version"] = 999
    code, body = await asgi_request(
        app, "POST", "/api/factor-composites", invalid_version
    )
    assert code == 422
    assert body["detail"]["code"] == "COMPOSITE_FACTOR_VERSION_MISMATCH"

    injected = payload()
    injected["definition"]["expression"] = "malicious_payload()"
    code, body = await asgi_request(app, "POST", "/api/factor-composites", injected)
    assert code == 422
    assert any(item["type"] == "extra_forbidden" for item in body["detail"])
    assert database["factor_composites"].documents == []


async def test_composite_feature_flag_blocks_mutation(monkeypatch):
    app, database, _ = await configured_api(monkeypatch)
    monkeypatch.setenv("FACTOR_FEATURE_ENABLED", "false")
    code, body = await asgi_request(app, "POST", "/api/factor-composites", payload())
    assert code == 404
    assert body["detail"]["code"] == "FACTOR_FEATURE_DISABLED"
    assert database["factor_composites"].documents == []
