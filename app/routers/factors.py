from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, status, Response
from pydantic import BaseModel, Field
from app.routers.auth_db import get_current_user
from app.core.database import get_mongo_db
from app.models.factor import FactorDefinition, FactorCategory
from app.models.domain_task import TaskType
from app.services.factors.registry import global_factor_registry
from app.repositories.factor_repository import FactorRepository
from app.repositories.domain_task_repository import DomainTaskRepository

router = APIRouter(prefix="/api/factors", tags=["Factors"])


def get_factor_repository() -> FactorRepository:
    return FactorRepository(db=get_mongo_db())


def get_task_repository() -> DomainTaskRepository:
    return DomainTaskRepository(db=get_mongo_db())


class ComputeFactorRequest(BaseModel):
    symbols: List[str] = Field(..., min_items=1)
    market: str = "CN"
    factor_ids: List[str] = Field(..., min_items=1)
    idempotency_key: Optional[str] = None


@router.get("/definitions")
async def list_factor_definitions(
    category: Optional[str] = Query(None),
    market: Optional[str] = Query(None),
    search: Optional[str] = Query(None)
):
    """获取因子定义元数据目录"""
    defs = global_factor_registry.get_all()

    if category:
        defs = [d for d in defs if d.category.value == category or d.category == category]
    if market:
        mkt = market.upper()
        defs = [d for d in defs if mkt in d.supported_markets]
    if search:
        s = search.lower()
        defs = [d for d in defs if s in d.factor_id.lower() or s in d.name.lower() or s in d.description.lower()]

    return {
        "success": True,
        "data": {
            "items": [d.model_dump() for d in defs],
            "total": len(defs)
        }
    }


@router.get("/definitions/{factor_id}")
async def get_factor_definition(factor_id: str):
    """获取单个因子定义详情"""
    defn = global_factor_registry.get_by_id(factor_id)
    if not defn:
        raise HTTPException(status_code=404, detail="FACTOR_NOT_FOUND")
    return {
        "success": True,
        "data": defn.model_dump()
    }


@router.post("/compute", status_code=status.HTTP_202_ACCEPTED)
async def submit_factor_compute_job(
    payload: ComputeFactorRequest,
    response: Response,
    user: dict = Depends(get_current_user),
    task_repo: DomainTaskRepository = Depends(get_task_repository)
):
    """提交异步因子计算任务"""
    response.status_code = status.HTTP_202_ACCEPTED

    task = await task_repo.create_task(
        user_id=user["id"],
        task_type=TaskType.FACTOR_COMPUTE,
        payload={
            "symbols": payload.symbols,
            "market": payload.market,
            "factor_ids": payload.factor_ids
        },
        idempotency_key=payload.idempotency_key
    )

    return {
        "success": True,
        "data": {
            "task_id": task.task_id,
            "status": task.status.value,
            "message": "Factor compute job submitted successfully"
        }
    }


@router.get("/snapshots/{snapshot_id}")
async def get_factor_snapshot_detail(
    snapshot_id: str,
    user: dict = Depends(get_current_user),
    factor_repo: FactorRepository = Depends(get_factor_repository)
):
    """获取因子快照详情"""
    snap = await factor_repo.get_snapshot(snapshot_id, user_id=user["id"])
    if not snap:
        raise HTTPException(status_code=404, detail="SNAPSHOT_NOT_FOUND")
    return {
        "success": True,
        "data": snap
    }


@router.get("/snapshots/{snapshot_id}/values")
async def get_factor_snapshot_values(
    snapshot_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    user: dict = Depends(get_current_user),
    factor_repo: FactorRepository = Depends(get_factor_repository)
):
    """分页获取因子快照数值"""
    snap = await factor_repo.get_snapshot(snapshot_id, user_id=user["id"])
    if not snap:
        raise HTTPException(status_code=404, detail="SNAPSHOT_NOT_FOUND")

    data = snap.get("data", {})
    symbols = list(data.keys())
    total = len(symbols)

    skip = (page - 1) * page_size
    paged_symbols = symbols[skip : skip + page_size]
    paged_values = {sym: data[sym] for sym in paged_symbols}

    return {
        "success": True,
        "data": {
            "items": paged_values,
            "total": total,
            "page": page,
            "page_size": page_size
        }
    }
