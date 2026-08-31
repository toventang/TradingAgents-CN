"""Authenticated HTTP API for factor metadata, jobs, and immutable snapshots."""

from __future__ import annotations

from datetime import date
from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pymongo.errors import PyMongoError

from app.core.database import get_mongo_db
from app.models.factor import (
    FactorAnalysisAccepted,
    FactorAnalysisRequest,
    FactorAnalysisResult,
    FactorCategory,
    FactorComputeAccepted,
    FactorComputeApiRequest,
    FactorDefinition,
    FactorDefinitionListResponse,
    FactorJob,
    FactorSnapshotListResponse,
    FactorSnapshotStatus,
    FactorStatus,
    FactorValidateRequest,
    FactorValidateResponse,
    FactorValuePage,
)
from app.models.symbol import Market
from app.repositories.domain_task_repository import DomainTaskRepository
from app.repositories.factor_repository import FactorRepository
from app.routers.auth_db import get_current_user
from app.services.domain_tasks import IdempotencyConflictError
from app.services.factors.api_service import (
    FactorApiNotFound,
    FactorApiService,
    FactorApiValidationError,
    factor_feature_enabled,
)
from app.services.factors.analysis import (
    FactorAnalysisApiService,
    FactorAnalysisError,
    FactorAnalysisNotFound,
)


router = APIRouter(prefix="/factors", tags=["factors"])


def get_factor_api_service() -> FactorApiService:
    database = get_mongo_db()
    return FactorApiService(
        factor_repository=FactorRepository(database),
        task_repository=DomainTaskRepository(database),
    )


def get_factor_analysis_api_service() -> FactorAnalysisApiService:
    database = get_mongo_db()
    return FactorAnalysisApiService(
        factor_repository=FactorRepository(database),
        task_repository=DomainTaskRepository(database),
    )


def require_factor_feature() -> None:
    if not factor_feature_enabled():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_error("FACTOR_FEATURE_DISABLED", "Factor APIs are disabled"),
        )


def _error(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _raise_store_unavailable(exc: Exception) -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=_error("FACTOR_STORE_UNAVAILABLE", "Factor storage is unavailable"),
    ) from exc


@router.get("/definitions", response_model=FactorDefinitionListResponse)
async def list_factor_definitions(
    category: FactorCategory | None = Query(default=None),
    market: Market | None = Query(default=None),
    definition_status: FactorStatus | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None, max_length=120),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _feature: None = Depends(require_factor_feature),
    _current_user: dict = Depends(get_current_user),
    service: FactorApiService = Depends(get_factor_api_service),
) -> FactorDefinitionListResponse:
    return service.list_definitions(
        category=category,
        market=market,
        status=definition_status,
        search=search,
        page=page,
        page_size=page_size,
    )


@router.get("/definitions/{factor_id}", response_model=FactorDefinition)
async def get_factor_definition(
    factor_id: str,
    _feature: None = Depends(require_factor_feature),
    _current_user: dict = Depends(get_current_user),
    service: FactorApiService = Depends(get_factor_api_service),
) -> FactorDefinition:
    try:
        return service.get_definition(factor_id)
    except FactorApiNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_error("FACTOR_DEFINITION_NOT_FOUND", "Factor definition was not found"),
        ) from exc


@router.post("/validate", response_model=FactorValidateResponse)
async def validate_factor_request(
    payload: FactorValidateRequest,
    _feature: None = Depends(require_factor_feature),
    _current_user: dict = Depends(get_current_user),
    service: FactorApiService = Depends(get_factor_api_service),
) -> FactorValidateResponse:
    return service.validate(payload)


@router.post(
    "/compute",
    response_model=FactorComputeAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_factor_compute(
    payload: FactorComputeApiRequest,
    _feature: None = Depends(require_factor_feature),
    current_user: dict = Depends(get_current_user),
    service: FactorApiService = Depends(get_factor_api_service),
) -> FactorComputeAccepted:
    try:
        return await service.create_compute(user_id=current_user["id"], request=payload)
    except FactorApiValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "FACTOR_REQUEST_INVALID",
                "message": "Factor request validation failed",
                "issues": [item.model_dump(mode="json") for item in exc.response.issues],
            },
        ) from exc
    except IdempotencyConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_error(exc.code, "Factor request idempotency conflict"),
        ) from exc
    except PyMongoError as exc:
        _raise_store_unavailable(exc)


@router.get("/jobs/{job_id}", response_model=FactorJob)
async def get_factor_job(
    job_id: str,
    _feature: None = Depends(require_factor_feature),
    current_user: dict = Depends(get_current_user),
    service: FactorApiService = Depends(get_factor_api_service),
) -> FactorJob:
    try:
        return await service.get_job(user_id=current_user["id"], job_id=job_id)
    except FactorApiNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_error("FACTOR_JOB_NOT_FOUND", "Factor job was not found"),
        ) from exc
    except PyMongoError as exc:
        _raise_store_unavailable(exc)


@router.get("/snapshots", response_model=FactorSnapshotListResponse)
async def list_factor_snapshots(
    market: Market | None = Query(default=None),
    trade_date: date | None = Query(default=None),
    snapshot_status: FactorSnapshotStatus = Query(
        default=FactorSnapshotStatus.READY, alias="status"
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _feature: None = Depends(require_factor_feature),
    current_user: dict = Depends(get_current_user),
    service: FactorApiService = Depends(get_factor_api_service),
) -> FactorSnapshotListResponse:
    try:
        return await service.list_snapshots(
            user_id=current_user["id"],
            market=market,
            trade_date=trade_date,
            snapshot_status=snapshot_status,
            page=page,
            page_size=page_size,
        )
    except PyMongoError as exc:
        _raise_store_unavailable(exc)


@router.get("/snapshots/{snapshot_id}/values", response_model=FactorValuePage)
async def list_factor_values(
    snapshot_id: str,
    symbol: str | None = Query(default=None, min_length=1, max_length=64),
    factors: str | None = Query(default=None, max_length=2000),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=200),
    _feature: None = Depends(require_factor_feature),
    current_user: dict = Depends(get_current_user),
    service: FactorApiService = Depends(get_factor_api_service),
) -> FactorValuePage:
    factor_ids = tuple(
        item.strip() for item in (factors or "").split(",") if item.strip()
    )
    try:
        return await service.list_values(
            user_id=current_user["id"],
            snapshot_id=snapshot_id,
            symbol=symbol,
            factors=factor_ids,
            page=page,
            page_size=page_size,
        )
    except FactorApiNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_error("FACTOR_SNAPSHOT_NOT_FOUND", "Ready factor snapshot was not found"),
        ) from exc
    except PyMongoError as exc:
        _raise_store_unavailable(exc)


@router.post(
    "/analyze",
    response_model=FactorAnalysisAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_factor_analysis(
    payload: FactorAnalysisRequest,
    _feature: None = Depends(require_factor_feature),
    current_user: dict = Depends(get_current_user),
    service: FactorAnalysisApiService = Depends(get_factor_analysis_api_service),
) -> FactorAnalysisAccepted:
    try:
        return await service.create(user_id=current_user["id"], request=payload)
    except FactorAnalysisError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": exc.code, "message": str(exc), "details": exc.details},
        ) from exc
    except IdempotencyConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_error(exc.code, "Factor analysis idempotency conflict"),
        ) from exc
    except PyMongoError as exc:
        _raise_store_unavailable(exc)


@router.get("/analysis/{analysis_id}", response_model=FactorAnalysisResult)
async def get_factor_analysis(
    analysis_id: str,
    _feature: None = Depends(require_factor_feature),
    current_user: dict = Depends(get_current_user),
    service: FactorAnalysisApiService = Depends(get_factor_analysis_api_service),
) -> FactorAnalysisResult:
    try:
        return await service.get_result(
            user_id=current_user["id"], analysis_id=analysis_id
        )
    except FactorAnalysisNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_error(
                "FACTOR_ANALYSIS_NOT_FOUND",
                "Factor analysis result was not found",
            ),
        ) from exc
    except PyMongoError as exc:
        _raise_store_unavailable(exc)
