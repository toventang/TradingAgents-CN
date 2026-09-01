"""Authenticated APIs for system templates, strategies, versions, and signals."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pymongo.errors import PyMongoError

from app.core.database import get_mongo_db
from app.models.domain_task import DomainTask
from app.models.strategy import (
    FrozenFactorDependency,
    FrozenSkillDependency,
    Strategy,
    StrategyKind,
    StrategySignal,
    StrategyValidationIssue,
    StrategyVersion,
)
from app.models.symbol import Market
from app.repositories.domain_task_repository import DomainTaskRepository
from app.repositories.strategy_repository import (
    StrategyConflict,
    StrategyNotFound,
    StrategyRepository,
)
from app.routers.auth_db import get_current_user
from app.services.domain_tasks import IdempotencyConflictError
from app.services.strategies.api_service import (
    StrategyApiNotFound,
    StrategyApiService,
    StrategyApiValidationError,
)
from app.services.strategies.version_service import StrategyPermissionDenied


router = APIRouter(prefix="/strategies", tags=["strategies"])


class StrategyCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    tags: tuple[str, ...] = ()
    kind: StrategyKind
    market: Market
    definition: dict[str, Any]
    analysis_profile_version_id: str | None = None
    change_summary: str = Field(default="Initial draft", max_length=2000)


class StrategyPairResponse(BaseModel):
    strategy: Strategy
    version: StrategyVersion


class StrategyListResponse(BaseModel):
    items: tuple[Strategy, ...]


class StrategyDetailResponse(BaseModel):
    strategy: Strategy
    versions: tuple[StrategyVersion, ...]


class StrategyCreateVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent_version_id: str | None = None
    change_summary: str = Field(default="New draft", max_length=2000)


class StrategyUpdateVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    definition: dict[str, Any]
    analysis_profile_version_id: str | None = None
    change_summary: str | None = Field(default=None, max_length=2000)


class StrategyValidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    market: Market | None = None
    definition: dict[str, Any] | None = None
    strategy_version_id: str | None = None

    @model_validator(mode="after")
    def require_one_source(self) -> "StrategyValidateRequest":
        if (self.definition is None) == (self.strategy_version_id is None):
            raise ValueError("provide exactly one of definition or strategy_version_id")
        if self.definition is not None and self.market is None:
            raise ValueError("market is required for inline validation")
        return self


class StrategyValidationResponse(BaseModel):
    valid: bool
    errors: tuple[StrategyValidationIssue, ...]
    warnings: tuple[StrategyValidationIssue, ...]
    factor_dependencies: tuple[FrozenFactorDependency, ...]
    skill_dependencies: tuple[FrozenSkillDependency, ...]


class StrategyCloneRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_version_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    tags: tuple[str, ...] | None = None


class StrategySignalTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    universe_snapshot_id: str = Field(min_length=1, max_length=200)
    factor_snapshot_ids: tuple[str, ...] = Field(min_length=1, max_length=5000)
    as_of: datetime
    idempotency_key: str = Field(min_length=1, max_length=200)

    @field_validator("factor_snapshot_ids")
    @classmethod
    def require_unique_factor_snapshots(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("factor_snapshot_ids must be unique")
        return value

    @field_validator("as_of")
    @classmethod
    def require_aware_as_of(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        return value

    @field_validator("universe_snapshot_id", "idempotency_key")
    @classmethod
    def require_trimmed_task_text(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("task identifiers must be trimmed")
        return value


class StrategySignalPage(BaseModel):
    items: tuple[StrategySignal, ...]
    page: int
    page_size: int
    total: int


class TemplateParameterRangeResponse(BaseModel):
    name: str
    default: float | int
    minimum: float | int
    maximum: float | int
    unit: str
    sensitivity: str


class StrategyTemplateResponse(BaseModel):
    template_id: str
    strategy_id: str
    strategy_version_id: str
    version: int
    name: str
    description: str
    formula: str
    kind: StrategyKind
    market: Market
    definition: dict[str, Any]
    parameter_ranges: tuple[TemplateParameterRangeResponse, ...]
    suitable_markets: tuple[str, ...]
    unsuitable_scenarios: tuple[str, ...]
    risk_warning: str


def get_strategy_api_service() -> StrategyApiService:
    database = get_mongo_db()
    repository = StrategyRepository(database)
    return StrategyApiService(
        repository=repository,
        task_repository=DomainTaskRepository(database),
    )


def _error(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _store_unavailable(exc: Exception) -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=_error("STRATEGY_STORE_UNAVAILABLE", "Strategy storage is unavailable"),
    ) from exc


def _template_response(template) -> StrategyTemplateResponse:
    return StrategyTemplateResponse(
        template_id=template.template_id,
        strategy_id=template.strategy_id,
        strategy_version_id=template.strategy_version_id,
        version=template.version,
        name=template.name,
        description=template.description,
        formula=template.formula,
        kind=template.kind,
        market=template.market,
        definition=template.definition_copy(),
        parameter_ranges=tuple(
            TemplateParameterRangeResponse(**item.__dict__)
            for item in template.parameter_ranges
        ),
        suitable_markets=template.suitable_markets,
        unsuitable_scenarios=template.unsuitable_scenarios,
        risk_warning=template.risk_warning,
    )


@router.get("/templates", response_model=tuple[StrategyTemplateResponse, ...])
async def list_templates(
    _current_user: dict = Depends(get_current_user),
    service: StrategyApiService = Depends(get_strategy_api_service),
):
    return tuple(_template_response(item) for item in service.list_templates())


@router.get("/signals", response_model=StrategySignalPage)
async def list_signals(
    strategy_version_id: str | None = Query(default=None),
    signal_date: date | None = Query(default=None),
    symbol: str | None = Query(default=None, min_length=1, max_length=64),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
    service: StrategyApiService = Depends(get_strategy_api_service),
):
    try:
        items, total = await service.list_signals(
            user_id=current_user["id"],
            strategy_version_id=strategy_version_id,
            signal_date=signal_date,
            symbol=symbol,
            page=page,
            page_size=page_size,
        )
        return StrategySignalPage(items=items, page=page, page_size=page_size, total=total)
    except PyMongoError as exc:
        _store_unavailable(exc)


@router.post("/validate", response_model=StrategyValidationResponse)
async def validate_strategy(
    payload: StrategyValidateRequest,
    current_user: dict = Depends(get_current_user),
    service: StrategyApiService = Depends(get_strategy_api_service),
):
    try:
        report = await service.validate(
            user_id=current_user["id"],
            market=payload.market,
            definition=payload.definition,
            strategy_version_id=payload.strategy_version_id,
        )
        return StrategyValidationResponse(
            valid=report.valid,
            errors=report.errors,
            warnings=report.warnings,
            factor_dependencies=report.factor_dependencies,
            skill_dependencies=report.skill_dependencies,
        )
    except StrategyApiNotFound as exc:
        raise HTTPException(404, detail=_error("STRATEGY_VERSION_NOT_FOUND", str(exc))) from exc
    except PyMongoError as exc:
        _store_unavailable(exc)


@router.post("", response_model=StrategyPairResponse, status_code=status.HTTP_201_CREATED)
async def create_strategy(
    payload: StrategyCreateRequest,
    current_user: dict = Depends(get_current_user),
    service: StrategyApiService = Depends(get_strategy_api_service),
):
    try:
        strategy, version = await service.create(user_id=current_user["id"], request=payload)
        return StrategyPairResponse(strategy=strategy, version=version)
    except StrategyConflict as exc:
        raise HTTPException(409, detail=_error("STRATEGY_STATE_CONFLICT", str(exc))) from exc
    except ValueError as exc:
        raise HTTPException(422, detail=_error("STRATEGY_REQUEST_INVALID", str(exc))) from exc
    except PyMongoError as exc:
        _store_unavailable(exc)


@router.get("", response_model=StrategyListResponse)
async def list_strategies(
    include_archived: bool = Query(default=False),
    current_user: dict = Depends(get_current_user),
    service: StrategyApiService = Depends(get_strategy_api_service),
):
    try:
        return StrategyListResponse(
            items=await service.list(
                user_id=current_user["id"], include_archived=include_archived
            )
        )
    except PyMongoError as exc:
        _store_unavailable(exc)


@router.get("/{strategy_id}", response_model=StrategyDetailResponse)
async def get_strategy(
    strategy_id: str,
    current_user: dict = Depends(get_current_user),
    service: StrategyApiService = Depends(get_strategy_api_service),
):
    try:
        strategy, versions = await service.detail(
            user_id=current_user["id"], strategy_id=strategy_id
        )
        return StrategyDetailResponse(strategy=strategy, versions=versions)
    except StrategyApiNotFound as exc:
        raise HTTPException(404, detail=_error("STRATEGY_NOT_FOUND", str(exc))) from exc
    except PyMongoError as exc:
        _store_unavailable(exc)


@router.post("/{strategy_id}/versions", response_model=StrategyVersion)
async def create_strategy_version(
    strategy_id: str,
    payload: StrategyCreateVersionRequest,
    current_user: dict = Depends(get_current_user),
    service: StrategyApiService = Depends(get_strategy_api_service),
):
    try:
        return await service.create_version(
            user_id=current_user["id"],
            strategy_id=strategy_id,
            parent_version_id=payload.parent_version_id,
            change_summary=payload.change_summary,
        )
    except StrategyNotFound as exc:
        raise HTTPException(404, detail=_error("STRATEGY_NOT_FOUND", str(exc))) from exc
    except StrategyConflict as exc:
        raise HTTPException(409, detail=_error("STRATEGY_STATE_CONFLICT", str(exc))) from exc
    except ValueError as exc:
        raise HTTPException(422, detail=_error("STRATEGY_REQUEST_INVALID", str(exc))) from exc
    except PyMongoError as exc:
        _store_unavailable(exc)


@router.put("/{strategy_id}/versions/{version_id}", response_model=StrategyVersion)
async def update_strategy_version(
    strategy_id: str,
    version_id: str,
    payload: StrategyUpdateVersionRequest,
    current_user: dict = Depends(get_current_user),
    service: StrategyApiService = Depends(get_strategy_api_service),
):
    try:
        return await service.update_version(
            user_id=current_user["id"],
            strategy_id=strategy_id,
            version_id=version_id,
            request=payload,
        )
    except StrategyApiNotFound as exc:
        raise HTTPException(404, detail=_error("STRATEGY_DRAFT_NOT_FOUND", str(exc))) from exc
    except StrategyConflict as exc:
        raise HTTPException(409, detail=_error("STRATEGY_STATE_CONFLICT", str(exc))) from exc
    except ValueError as exc:
        raise HTTPException(422, detail=_error("STRATEGY_REQUEST_INVALID", str(exc))) from exc
    except PyMongoError as exc:
        _store_unavailable(exc)


@router.post("/{strategy_id}/versions/{version_id}/publish", response_model=StrategyVersion)
async def publish_strategy_version(
    strategy_id: str,
    version_id: str,
    current_user: dict = Depends(get_current_user),
    service: StrategyApiService = Depends(get_strategy_api_service),
):
    try:
        return await service.publish(
            user_id=current_user["id"], strategy_id=strategy_id, version_id=version_id
        )
    except StrategyApiNotFound as exc:
        raise HTTPException(404, detail=_error("STRATEGY_DRAFT_NOT_FOUND", str(exc))) from exc
    except StrategyApiValidationError as exc:
        raise HTTPException(
            422,
            detail={
                "code": "STRATEGY_VALIDATION_FAILED",
                "message": "Strategy validation failed",
                "issues": [item.model_dump(mode="json") for item in exc.report.errors],
            },
        ) from exc
    except StrategyConflict as exc:
        raise HTTPException(409, detail=_error("STRATEGY_STATE_CONFLICT", str(exc))) from exc
    except ValueError as exc:
        raise HTTPException(422, detail=_error("STRATEGY_REQUEST_INVALID", str(exc))) from exc
    except PyMongoError as exc:
        _store_unavailable(exc)


@router.post("/{strategy_id}/clone", response_model=StrategyPairResponse, status_code=201)
async def clone_strategy(
    strategy_id: str,
    payload: StrategyCloneRequest,
    current_user: dict = Depends(get_current_user),
    service: StrategyApiService = Depends(get_strategy_api_service),
):
    try:
        strategy, version = await service.clone(
            user_id=current_user["id"], strategy_id=strategy_id, request=payload
        )
        return StrategyPairResponse(strategy=strategy, version=version)
    except StrategyNotFound as exc:
        raise HTTPException(404, detail=_error("CLONE_SOURCE_NOT_FOUND", str(exc))) from exc
    except StrategyConflict as exc:
        raise HTTPException(409, detail=_error("STRATEGY_STATE_CONFLICT", str(exc))) from exc
    except ValueError as exc:
        raise HTTPException(422, detail=_error("STRATEGY_REQUEST_INVALID", str(exc))) from exc
    except PyMongoError as exc:
        _store_unavailable(exc)


@router.delete("/{strategy_id}", response_model=Strategy)
async def archive_strategy(
    strategy_id: str,
    current_user: dict = Depends(get_current_user),
    service: StrategyApiService = Depends(get_strategy_api_service),
):
    try:
        return await service.archive(user_id=current_user["id"], strategy_id=strategy_id)
    except StrategyNotFound as exc:
        raise HTTPException(404, detail=_error("STRATEGY_NOT_FOUND", str(exc))) from exc
    except StrategyPermissionDenied as exc:
        raise HTTPException(403, detail=_error("STRATEGY_READ_ONLY", str(exc))) from exc
    except StrategyConflict as exc:
        raise HTTPException(409, detail=_error("STRATEGY_STATE_CONFLICT", str(exc))) from exc
    except PyMongoError as exc:
        _store_unavailable(exc)


@router.post(
    "/{strategy_version_id}/signals",
    response_model=DomainTask,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_signal_task(
    strategy_version_id: str,
    payload: StrategySignalTaskRequest,
    current_user: dict = Depends(get_current_user),
    service: StrategyApiService = Depends(get_strategy_api_service),
):
    try:
        return await service.create_signal_task(
            user_id=current_user["id"],
            strategy_version_id=strategy_version_id,
            request=payload,
        )
    except StrategyApiNotFound as exc:
        raise HTTPException(404, detail=_error("STRATEGY_VERSION_NOT_FOUND", str(exc))) from exc
    except IdempotencyConflictError as exc:
        raise HTTPException(409, detail=_error(exc.code, str(exc))) from exc
    except PyMongoError as exc:
        _store_unavailable(exc)
