from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, Field
from typing import Literal, Optional, Dict, Any, List
import logging

from app.routers.auth_db import get_current_user
from app.core.response import ok
from app.services.paper.paper_service import PaperTradingService, detect_market_and_code

router = APIRouter(prefix="/paper", tags=["paper"])
logger = logging.getLogger("webapi")


def get_paper_service() -> PaperTradingService:
    return PaperTradingService()


class PlaceOrderRequest(BaseModel):
    code: str = Field(..., description="股票代码（支持A股/港股/美股）")
    side: Literal["buy", "sell"]
    quantity: int = Field(..., gt=0)
    market: Optional[str] = Field(None, description="市场类型 (CN/HK/US)，不传则自动识别")
    analysis_id: Optional[str] = None


@router.get("/account", response_model=dict)
async def get_account(
    current_user: dict = Depends(get_current_user),
    service: PaperTradingService = Depends(get_paper_service)
):
    """获取或创建纸上账户，返回资金与持仓估值汇总（支持多市场）"""
    summary = await service.get_account_summary(current_user["id"])
    return ok(summary)


@router.post("/order", response_model=dict)
async def place_order(
    payload: PlaceOrderRequest,
    current_user: dict = Depends(get_current_user),
    service: PaperTradingService = Depends(get_paper_service)
):
    """提交市价单，按最新价即时成交（支持多市场）"""
    try:
        order_dict = await service.place_order(
            user_id=current_user["id"],
            code=payload.code,
            side=payload.side,
            quantity=payload.quantity,
            market=payload.market,
            analysis_id=payload.analysis_id
        )
        return ok({"order": order_dict})
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.get("/positions", response_model=dict)
async def list_positions(
    current_user: dict = Depends(get_current_user),
    service: PaperTradingService = Depends(get_paper_service)
):
    """获取持仓列表（支持多市场）"""
    positions = await service.list_positions(current_user["id"])
    return ok({"items": positions})


@router.get("/orders", response_model=dict)
async def list_orders(
    limit: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
    service: PaperTradingService = Depends(get_paper_service)
):
    """获取订单列表"""
    orders = await service.list_orders(current_user["id"], limit=limit)
    return ok({"items": orders})


@router.post("/reset", response_model=dict)
async def reset_account(
    confirm: bool = Query(False),
    current_user: dict = Depends(get_current_user),
    service: PaperTradingService = Depends(get_paper_service)
):
    """重置账户（支持多货币）"""
    if not confirm:
        raise HTTPException(status_code=400, detail="请设置 confirm=true 以确认重置")
    acc = await service.reset_account(current_user["id"])
    return ok({"message": "账户已重置", "cash": acc.get("cash", {})})
