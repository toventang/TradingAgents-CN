"""HTTP adapter for the extracted manual paper-trading domain."""

from typing import Literal, NoReturn, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.core.database import get_mongo_db
from app.core.response import ok
from app.routers.auth_db import get_current_user
from app.services.paper import (
    PaperConsistencyError,
    PaperTradingService,
    PaperValidationError,
)

router = APIRouter(prefix="/paper", tags=["paper"])


class PlaceOrderRequest(BaseModel):
    code: str = Field(..., description="股票代码（支持A股/港股/美股）")
    side: Literal["buy", "sell"]
    quantity: int = Field(..., gt=0)
    market: Optional[str] = Field(
        None,
        description="市场类型 (CN/HK/US)，不传则自动识别",
    )
    analysis_id: Optional[str] = None


def get_paper_trading_service() -> PaperTradingService:
    return PaperTradingService(get_mongo_db())


def _raise_domain_error(exc: Exception) -> NoReturn:
    if isinstance(exc, PaperValidationError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    if isinstance(exc, PaperConsistencyError):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": exc.code,
                "message": str(exc),
                "recovery_id": exc.recovery_id,
            },
        ) from exc
    raise exc


@router.get("/account", response_model=dict)
async def get_account(
    current_user: dict = Depends(get_current_user),
    service: PaperTradingService = Depends(get_paper_trading_service),
):
    return ok(await service.get_account(current_user["id"]))


@router.post("/order", response_model=dict)
async def place_order(
    payload: PlaceOrderRequest,
    current_user: dict = Depends(get_current_user),
    service: PaperTradingService = Depends(get_paper_trading_service),
):
    try:
        data = await service.place_order(
            user_id=current_user["id"],
            code=payload.code,
            market=payload.market,
            side=payload.side,
            quantity=payload.quantity,
            analysis_id=payload.analysis_id,
        )
    except (PaperValidationError, PaperConsistencyError) as exc:
        _raise_domain_error(exc)
    return ok(data)


@router.get("/positions", response_model=dict)
async def list_positions(
    current_user: dict = Depends(get_current_user),
    service: PaperTradingService = Depends(get_paper_trading_service),
):
    return ok(await service.list_positions(current_user["id"]))


@router.get("/orders", response_model=dict)
async def list_orders(
    limit: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
    service: PaperTradingService = Depends(get_paper_trading_service),
):
    return ok(await service.list_orders(current_user["id"], limit))


@router.post("/reset", response_model=dict)
async def reset_account(
    confirm: bool = Query(False),
    current_user: dict = Depends(get_current_user),
    service: PaperTradingService = Depends(get_paper_trading_service),
):
    if not confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请设置 confirm=true 以确认重置",
        )
    try:
        data = await service.reset(current_user["id"])
    except PaperConsistencyError as exc:
        _raise_domain_error(exc)
    return ok(data)
