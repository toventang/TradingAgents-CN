"""Authenticated backtest creation, result, comparison, and export APIs."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import NoReturn

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse
from pymongo.errors import PyMongoError

from app.core.database import get_mongo_db
from app.models.backtest import BacktestPerformanceReport, BacktestRequest
from app.repositories.backtest_repository import BacktestRepository
from app.repositories.domain_task_repository import DomainTaskRepository
from app.repositories.strategy_repository import StrategyRepository
from app.routers.auth_db import get_current_user
from app.services.backtest.api_service import (
    BacktestAccepted,
    BacktestApiConflict,
    BacktestApiLimitExceeded,
    BacktestApiNotFound,
    BacktestApiService,
    BacktestApiValidationError,
    BacktestCancelResult,
    BacktestCompareRequest,
    BacktestCompareResult,
    BacktestEquityPage,
    BacktestExportAsyncRequired,
    BacktestPage,
    BacktestRunDetail,
    EquityDownsample,
    ExportFormat,
    ExportResource,
)
from app.services.backtest.ledger import (
    BacktestEventRecord,
    BacktestPositionDailyRecord,
    BacktestRunRecord,
    BacktestRunStatus,
    BacktestTradeRecord,
)


router = APIRouter(prefix="/backtests", tags=["backtests"])


def get_backtest_api_service() -> BacktestApiService:
    database = get_mongo_db()
    return BacktestApiService(
        backtests=BacktestRepository(database),
        tasks=DomainTaskRepository(database),
        strategies=StrategyRepository(database),
    )


def _error(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _raise_api_error(exc: Exception) -> NoReturn:
    if isinstance(exc, BacktestApiNotFound):
        code = status.HTTP_404_NOT_FOUND
    elif isinstance(exc, BacktestApiValidationError):
        code = status.HTTP_422_UNPROCESSABLE_CONTENT
    elif isinstance(exc, BacktestApiConflict):
        code = status.HTTP_409_CONFLICT
    elif isinstance(exc, BacktestApiLimitExceeded):
        code = status.HTTP_413_CONTENT_TOO_LARGE
    else:
        code = status.HTTP_500_INTERNAL_SERVER_ERROR
    raise HTTPException(
        status_code=code,
        detail=_error(getattr(exc, "code", "BACKTEST_API_ERROR"), str(exc)),
    ) from exc


def _raise_store_unavailable(exc: Exception) -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=_error("BACKTEST_STORE_UNAVAILABLE", "Backtest storage is unavailable"),
    ) from exc


@router.post("", response_model=BacktestAccepted, status_code=status.HTTP_202_ACCEPTED)
async def create_backtest(
    payload: BacktestRequest,
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", min_length=1, max_length=200
    ),
    current_user: dict = Depends(get_current_user),
    service: BacktestApiService = Depends(get_backtest_api_service),
) -> BacktestAccepted:
    try:
        return await service.create(
            user_id=current_user["id"],
            request=payload,
            client_idempotency_key=idempotency_key,
        )
    except (BacktestApiValidationError, BacktestApiConflict) as exc:
        _raise_api_error(exc)
    except PyMongoError as exc:
        _raise_store_unavailable(exc)


@router.get("", response_model=BacktestPage[BacktestRunRecord])
async def list_backtests(
    run_status: BacktestRunStatus | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
    service: BacktestApiService = Depends(get_backtest_api_service),
) -> BacktestPage[BacktestRunRecord]:
    try:
        return await service.list_runs(
            user_id=current_user["id"],
            status=run_status,
            page=page,
            page_size=page_size,
        )
    except PyMongoError as exc:
        _raise_store_unavailable(exc)


@router.post("/compare", response_model=BacktestCompareResult)
async def compare_backtests(
    payload: BacktestCompareRequest,
    current_user: dict = Depends(get_current_user),
    service: BacktestApiService = Depends(get_backtest_api_service),
) -> BacktestCompareResult:
    try:
        return await service.compare(user_id=current_user["id"], request=payload)
    except (BacktestApiNotFound, BacktestApiConflict, BacktestApiLimitExceeded) as exc:
        _raise_api_error(exc)
    except PyMongoError as exc:
        _raise_store_unavailable(exc)


@router.get("/{run_id}", response_model=BacktestRunDetail)
async def get_backtest(
    run_id: str,
    current_user: dict = Depends(get_current_user),
    service: BacktestApiService = Depends(get_backtest_api_service),
) -> BacktestRunDetail:
    try:
        return await service.detail(user_id=current_user["id"], run_id=run_id)
    except BacktestApiNotFound as exc:
        _raise_api_error(exc)
    except PyMongoError as exc:
        _raise_store_unavailable(exc)


@router.post(
    "/{run_id}/cancel",
    response_model=BacktestCancelResult,
    status_code=status.HTTP_202_ACCEPTED,
)
async def cancel_backtest(
    run_id: str,
    current_user: dict = Depends(get_current_user),
    service: BacktestApiService = Depends(get_backtest_api_service),
) -> BacktestCancelResult:
    try:
        return await service.cancel(user_id=current_user["id"], run_id=run_id)
    except (BacktestApiNotFound, BacktestApiConflict) as exc:
        _raise_api_error(exc)
    except PyMongoError as exc:
        _raise_store_unavailable(exc)


@router.get("/{run_id}/equity", response_model=BacktestEquityPage)
async def get_backtest_equity(
    run_id: str,
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    downsample: EquityDownsample = Query(default=EquityDownsample.NONE),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=200, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
    service: BacktestApiService = Depends(get_backtest_api_service),
) -> BacktestEquityPage:
    try:
        return await service.equity_page(
            user_id=current_user["id"],
            run_id=run_id,
            start_date=start_date,
            end_date=end_date,
            downsample=downsample,
            page=page,
            page_size=page_size,
        )
    except (BacktestApiNotFound, BacktestApiValidationError, BacktestApiLimitExceeded) as exc:
        _raise_api_error(exc)
    except PyMongoError as exc:
        _raise_store_unavailable(exc)


@router.get("/{run_id}/trades", response_model=BacktestPage[BacktestTradeRecord])
async def get_backtest_trades(
    run_id: str,
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
    service: BacktestApiService = Depends(get_backtest_api_service),
) -> BacktestPage[BacktestTradeRecord]:
    try:
        return await service.trades_page(
            user_id=current_user["id"],
            run_id=run_id,
            start_date=start_date,
            end_date=end_date,
            page=page,
            page_size=page_size,
        )
    except (BacktestApiNotFound, BacktestApiValidationError) as exc:
        _raise_api_error(exc)
    except PyMongoError as exc:
        _raise_store_unavailable(exc)


@router.get(
    "/{run_id}/positions", response_model=BacktestPage[BacktestPositionDailyRecord]
)
async def get_backtest_positions(
    run_id: str,
    trade_date: date | None = Query(default=None),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
    service: BacktestApiService = Depends(get_backtest_api_service),
) -> BacktestPage[BacktestPositionDailyRecord]:
    if trade_date is not None:
        if start_date is not None or end_date is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=_error(
                    "BACKTEST_DATE_FILTER_INVALID",
                    "trade_date cannot be combined with a date range",
                ),
            )
        start_date = end_date = trade_date
    try:
        return await service.positions_page(
            user_id=current_user["id"],
            run_id=run_id,
            start_date=start_date,
            end_date=end_date,
            page=page,
            page_size=page_size,
        )
    except (BacktestApiNotFound, BacktestApiValidationError) as exc:
        _raise_api_error(exc)
    except PyMongoError as exc:
        _raise_store_unavailable(exc)


@router.get("/{run_id}/events", response_model=BacktestPage[BacktestEventRecord])
async def get_backtest_events(
    run_id: str,
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
    service: BacktestApiService = Depends(get_backtest_api_service),
) -> BacktestPage[BacktestEventRecord]:
    try:
        return await service.events_page(
            user_id=current_user["id"],
            run_id=run_id,
            start_date=start_date,
            end_date=end_date,
            page=page,
            page_size=page_size,
        )
    except (BacktestApiNotFound, BacktestApiValidationError) as exc:
        _raise_api_error(exc)
    except PyMongoError as exc:
        _raise_store_unavailable(exc)


@router.get("/{run_id}/metrics", response_model=BacktestPerformanceReport)
async def get_backtest_metrics(
    run_id: str,
    annual_risk_free_rate: Decimal = Query(default=Decimal("0"), gt=-1),
    current_user: dict = Depends(get_current_user),
    service: BacktestApiService = Depends(get_backtest_api_service),
) -> BacktestPerformanceReport:
    try:
        return await service.metrics(
            user_id=current_user["id"],
            run_id=run_id,
            annual_risk_free_rate=annual_risk_free_rate,
        )
    except (BacktestApiNotFound, BacktestApiConflict, BacktestApiLimitExceeded) as exc:
        _raise_api_error(exc)
    except PyMongoError as exc:
        _raise_store_unavailable(exc)


@router.get("/{run_id}/export", response_model=None)
async def export_backtest(
    run_id: str,
    resource: ExportResource = Query(default="trades"),
    export_format: ExportFormat = Query(default="csv", alias="format"),
    current_user: dict = Depends(get_current_user),
    service: BacktestApiService = Depends(get_backtest_api_service),
) -> Response:
    try:
        exported = await service.export(
            user_id=current_user["id"],
            run_id=run_id,
            resource=resource,
            format=export_format,
        )
    except BacktestExportAsyncRequired as exc:
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                "code": exc.code,
                "message": str(exc),
                "resource": exc.resource,
                "estimated_rows": exc.estimated_rows,
                "maximum_rows": exc.maximum_rows,
            },
        )
    except (
        BacktestApiNotFound,
        BacktestApiConflict,
        BacktestApiLimitExceeded,
    ) as exc:
        _raise_api_error(exc)
    except PyMongoError as exc:
        _raise_store_unavailable(exc)
    return Response(
        content=exported.content,
        media_type=exported.media_type,
        headers={"Content-Disposition": f'attachment; filename="{exported.filename}"'},
    )
