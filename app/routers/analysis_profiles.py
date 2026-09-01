"""Authenticated CRUD and version APIs for AnalysisProfile resources."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pymongo.errors import PyMongoError

from app.core.database import get_mongo_db
from app.models.analysis import (
    AnalysisAnalyst,
    AnalysisInvestmentHorizon,
    AnalysisProfile,
    AnalysisProfileVersion,
    AnalysisResearchDepth,
    AnalysisRiskPreference,
)
from app.repositories.strategy_repository import StrategyConflict, StrategyRepository
from app.routers.auth_db import get_current_user
from app.services.analysis_profiles import AnalysisProfileLifecycleError, AnalysisProfileNotFound
from app.services.strategies.analysis_profile_api import (
    AnalysisProfileApiNotFound,
    AnalysisProfileApiService,
)


router = APIRouter(prefix="/analysis-profiles", tags=["analysis-profiles"])


class AnalysisProfileCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    selected_analysts: tuple[AnalysisAnalyst, ...] = (
        AnalysisAnalyst.MARKET,
        AnalysisAnalyst.FUNDAMENTALS,
        AnalysisAnalyst.NEWS,
        AnalysisAnalyst.SOCIAL,
    )
    research_depth: AnalysisResearchDepth = AnalysisResearchDepth.STANDARD
    # Validate nested sensitive configuration inside the service so FastAPI's
    # default 422 response cannot echo a submitted credential-shaped value.
    quick_model_ref: dict[str, Any] = {"config_id": "model-config:default-quick"}
    deep_model_ref: dict[str, Any] = {"config_id": "model-config:default-deep"}
    risk_preference: AnalysisRiskPreference = AnalysisRiskPreference.BALANCED
    investment_horizon: AnalysisInvestmentHorizon = AnalysisInvestmentHorizon.MEDIUM
    enabled_skill_versions: tuple[str, ...] = ()
    factor_context: dict[str, Any] = {}
    strategy_context: str | None = None
    debate_rounds: int = Field(default=2, ge=0, le=5)
    risk_debate_rounds: int = Field(default=1, ge=0, le=5)
    output_schema_version: str = "analysis-report-v1"
    disclaimer_profile: str = "standard-cn-v1"
    change_summary: str = Field(default="Initial AnalysisProfile draft", max_length=2000)


class AnalysisProfilePairResponse(BaseModel):
    profile: AnalysisProfile
    version: AnalysisProfileVersion


class AnalysisProfilePage(BaseModel):
    items: tuple[AnalysisProfile, ...]
    page: int
    page_size: int
    total: int


class AnalysisProfileDetailResponse(BaseModel):
    profile: AnalysisProfile
    versions: tuple[AnalysisProfileVersion, ...]


class AnalysisProfileUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    changes: dict[str, Any] = Field(min_length=1)
    change_summary: str | None = Field(default=None, max_length=2000)


class AnalysisProfileCreateVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    change_summary: str = Field(default="New AnalysisProfile draft", max_length=2000)


def get_analysis_profile_api_service() -> AnalysisProfileApiService:
    return AnalysisProfileApiService(repository=StrategyRepository(get_mongo_db()))


def _error(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _store_unavailable(exc: Exception) -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=_error(
            "ANALYSIS_PROFILE_STORE_UNAVAILABLE",
            "AnalysisProfile storage is unavailable",
        ),
    ) from exc


@router.post("", response_model=AnalysisProfilePairResponse, status_code=201)
async def create_profile(
    payload: AnalysisProfileCreateRequest,
    current_user: dict = Depends(get_current_user),
    service: AnalysisProfileApiService = Depends(get_analysis_profile_api_service),
):
    try:
        profile, version = await service.create(user_id=current_user["id"], request=payload)
        return AnalysisProfilePairResponse(profile=profile, version=version)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(
            422,
            detail=_error(
                "ANALYSIS_PROFILE_INVALID",
                "AnalysisProfile configuration is invalid",
            ),
        ) from exc
    except StrategyConflict as exc:
        raise HTTPException(
            409, detail=_error("ANALYSIS_PROFILE_STATE_CONFLICT", str(exc))
        ) from exc
    except PyMongoError as exc:
        _store_unavailable(exc)


@router.get("", response_model=AnalysisProfilePage)
async def list_profiles(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
    service: AnalysisProfileApiService = Depends(get_analysis_profile_api_service),
):
    try:
        items, total = await service.list(
            user_id=current_user["id"], page=page, page_size=page_size
        )
        return AnalysisProfilePage(items=items, page=page, page_size=page_size, total=total)
    except PyMongoError as exc:
        _store_unavailable(exc)


@router.get("/{profile_id}", response_model=AnalysisProfileDetailResponse)
async def get_profile(
    profile_id: str,
    current_user: dict = Depends(get_current_user),
    service: AnalysisProfileApiService = Depends(get_analysis_profile_api_service),
):
    try:
        profile, versions = await service.detail(
            user_id=current_user["id"], profile_id=profile_id
        )
        return AnalysisProfileDetailResponse(profile=profile, versions=versions)
    except AnalysisProfileApiNotFound as exc:
        raise HTTPException(404, detail=_error("ANALYSIS_PROFILE_NOT_FOUND", str(exc))) from exc
    except PyMongoError as exc:
        _store_unavailable(exc)


@router.post("/{profile_id}/versions", response_model=AnalysisProfileVersion)
async def create_profile_version(
    profile_id: str,
    payload: AnalysisProfileCreateVersionRequest,
    current_user: dict = Depends(get_current_user),
    service: AnalysisProfileApiService = Depends(get_analysis_profile_api_service),
):
    try:
        return await service.create_version(
            user_id=current_user["id"],
            profile_id=profile_id,
            change_summary=payload.change_summary,
        )
    except AnalysisProfileNotFound as exc:
        raise HTTPException(404, detail=_error("ANALYSIS_PROFILE_NOT_FOUND", str(exc))) from exc
    except (AnalysisProfileLifecycleError, StrategyConflict) as exc:
        raise HTTPException(409, detail=_error("ANALYSIS_PROFILE_STATE_CONFLICT", str(exc))) from exc
    except PyMongoError as exc:
        _store_unavailable(exc)


@router.put("/{profile_id}/versions/{version_id}", response_model=AnalysisProfileVersion)
async def update_profile_version(
    profile_id: str,
    version_id: str,
    payload: AnalysisProfileUpdateRequest,
    current_user: dict = Depends(get_current_user),
    service: AnalysisProfileApiService = Depends(get_analysis_profile_api_service),
):
    try:
        return await service.update_version(
            user_id=current_user["id"],
            profile_id=profile_id,
            version_id=version_id,
            request=payload,
        )
    except AnalysisProfileApiNotFound as exc:
        raise HTTPException(404, detail=_error("ANALYSIS_PROFILE_DRAFT_NOT_FOUND", str(exc))) from exc
    except ValidationError as exc:
        raise HTTPException(
            422,
            detail=_error(
                "ANALYSIS_PROFILE_INVALID",
                "AnalysisProfile configuration is invalid",
            ),
        ) from exc
    except ValueError as exc:
        raise HTTPException(422, detail=_error("ANALYSIS_PROFILE_INVALID", str(exc))) from exc
    except StrategyConflict as exc:
        raise HTTPException(409, detail=_error("ANALYSIS_PROFILE_STATE_CONFLICT", str(exc))) from exc
    except PyMongoError as exc:
        _store_unavailable(exc)


@router.post(
    "/{profile_id}/versions/{version_id}/publish",
    response_model=AnalysisProfileVersion,
)
async def publish_profile_version(
    profile_id: str,
    version_id: str,
    current_user: dict = Depends(get_current_user),
    service: AnalysisProfileApiService = Depends(get_analysis_profile_api_service),
):
    try:
        return await service.publish(
            user_id=current_user["id"], profile_id=profile_id, version_id=version_id
        )
    except AnalysisProfileApiNotFound as exc:
        raise HTTPException(404, detail=_error("ANALYSIS_PROFILE_DRAFT_NOT_FOUND", str(exc))) from exc
    except StrategyConflict as exc:
        raise HTTPException(409, detail=_error("ANALYSIS_PROFILE_STATE_CONFLICT", str(exc))) from exc
    except PyMongoError as exc:
        _store_unavailable(exc)


@router.delete("/{profile_id}", response_model=AnalysisProfile)
async def archive_profile(
    profile_id: str,
    current_user: dict = Depends(get_current_user),
    service: AnalysisProfileApiService = Depends(get_analysis_profile_api_service),
):
    try:
        return await service.archive(
            user_id=current_user["id"],
            profile_id=profile_id,
            archived_at=datetime.now(timezone.utc),
        )
    except AnalysisProfileApiNotFound as exc:
        raise HTTPException(404, detail=_error("ANALYSIS_PROFILE_NOT_FOUND", str(exc))) from exc
    except PyMongoError as exc:
        _store_unavailable(exc)
