"""Authenticated HTTP API for factor metadata, jobs, and immutable snapshots."""

from __future__ import annotations

from datetime import date
from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pymongo.errors import PyMongoError

from app.core.database import get_mongo_db
from app.models.factor import (
    CompositeCreateRequest,
    CompositeFactorResource,
    CompositeUpdateRequest,
    CompositeValidateRequest,
    CompositeValidationResponse,
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
from app.services.factors.composites import (
    CompositeDslEngine,
    CompositeDslError,
    CompositeFactorService,
    CompositeNotFound,
    CompositeStateConflict,
)


router = APIRouter()
factor_router = APIRouter(prefix="/factors", tags=["factors"])
composite_router = APIRouter(prefix="/factor-composites", tags=["factor-composites"])


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


def get_composite_factor_service() -> CompositeFactorService:
    return CompositeFactorService(FactorRepository(get_mongo_db()))


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


@factor_router.get("/definitions", response_model=FactorDefinitionListResponse)
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


@factor_router.get("/definitions/{factor_id}", response_model=FactorDefinition)
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


@factor_router.post(
    "/validate",
    response_model=FactorValidateResponse | CompositeValidationResponse,
)
async def validate_factor_request(
    payload: FactorValidateRequest | CompositeValidateRequest,
    _feature: None = Depends(require_factor_feature),
    _current_user: dict = Depends(get_current_user),
    service: FactorApiService = Depends(get_factor_api_service),
) -> FactorValidateResponse | CompositeValidationResponse:
    if isinstance(payload, CompositeValidateRequest):
        return CompositeDslEngine().validation_response(payload)
    return service.validate(payload)


@factor_router.post(
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


@factor_router.get("/jobs/{job_id}", response_model=FactorJob)
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


@factor_router.get("/snapshots", response_model=FactorSnapshotListResponse)
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


@factor_router.get("/snapshots/{snapshot_id}/values", response_model=FactorValuePage)
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


@factor_router.post(
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


@factor_router.get("/analysis/{analysis_id}", response_model=FactorAnalysisResult)
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


@composite_router.post(
    "",
    response_model=CompositeFactorResource,
    status_code=status.HTTP_201_CREATED,
)
async def create_composite_factor(
    payload: CompositeCreateRequest,
    _feature: None = Depends(require_factor_feature),
    current_user: dict = Depends(get_current_user),
    service: CompositeFactorService = Depends(get_composite_factor_service),
) -> CompositeFactorResource:
    try:
        return await service.create(user_id=current_user["id"], request=payload)
    except CompositeDslError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": exc.code, "message": str(exc), "factor_id": exc.factor_id},
        ) from exc
    except CompositeStateConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_error(exc.code, str(exc)),
        ) from exc
    except PyMongoError as exc:
        _raise_store_unavailable(exc)


@composite_router.put("/{composite_id}", response_model=CompositeFactorResource)
async def update_composite_factor(
    composite_id: str,
    payload: CompositeUpdateRequest,
    _feature: None = Depends(require_factor_feature),
    current_user: dict = Depends(get_current_user),
    service: CompositeFactorService = Depends(get_composite_factor_service),
) -> CompositeFactorResource:
    try:
        return await service.update(
            user_id=current_user["id"],
            composite_id=composite_id,
            request=payload,
        )
    except CompositeNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_error("COMPOSITE_NOT_FOUND", "Composite factor was not found"),
        ) from exc
    except CompositeDslError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": exc.code, "message": str(exc), "factor_id": exc.factor_id},
        ) from exc
    except CompositeStateConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_error(exc.code, str(exc)),
        ) from exc
    except PyMongoError as exc:
        _raise_store_unavailable(exc)


@composite_router.post(
    "/{composite_id}/publish",
    response_model=CompositeFactorResource,
)
async def publish_composite_factor(
    composite_id: str,
    _feature: None = Depends(require_factor_feature),
    current_user: dict = Depends(get_current_user),
    service: CompositeFactorService = Depends(get_composite_factor_service),
) -> CompositeFactorResource:
    try:
        return await service.publish(
            user_id=current_user["id"], composite_id=composite_id
        )
    except CompositeNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_error("COMPOSITE_NOT_FOUND", "Composite factor was not found"),
        ) from exc
    except CompositeStateConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_error(exc.code, str(exc)),
        ) from exc
    except PyMongoError as exc:
        _raise_store_unavailable(exc)


@composite_router.post(
    "/validate",
    response_model=CompositeValidationResponse,
)
async def validate_composite_factor(
    payload: CompositeValidateRequest,
    _feature: None = Depends(require_factor_feature),
    _current_user: dict = Depends(get_current_user),
    service: CompositeFactorService = Depends(get_composite_factor_service),
) -> CompositeValidationResponse:
    return service.validate(payload)


router.include_router(factor_router)
router.include_router(composite_router)
