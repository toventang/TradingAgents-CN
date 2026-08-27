import uuid
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Header, status
from pydantic import BaseModel

from app.models.backtest import BacktestConfig, BacktestResult, BacktestStatus
from app.models.domain_task import DomainTask, TaskType, TaskStatus
from app.repositories.backtest_repository import BacktestRepository, BacktestNotFoundError, BacktestForbiddenError
from app.repositories.domain_task_repository import DomainTaskRepository
from app.services.auth_service import AuthService
from app.utils.timezone import now_tz

router = APIRouter(prefix="/api/backtests", tags=["Backtests"])


class SubmitBacktestRequest(BaseModel):
    config: BacktestConfig
    prices_data: Optional[List[Dict[str, Any]]] = None
    factors_data: Optional[List[Dict[str, Any]]] = None
    benchmark_prices: Optional[Dict[str, float]] = None


def check_is_admin(x_user_role: Optional[str] = Header(None)) -> bool:
    """检查请求头是否具备 admin / superuser 角色"""
    return bool(x_user_role and x_user_role.lower() in ("admin", "superuser", "system"))


@router.post("", response_model=Dict[str, Any], status_code=status.HTTP_202_ACCEPTED)
async def submit_backtest(
    req: SubmitBacktestRequest,
    user_id: str = Depends(AuthService.get_canonical_user_id)
):
    bt_repo = BacktestRepository()
    bt_id = f"bt_{uuid.uuid4().hex[:12]}"
    now = now_tz()

    init_result = BacktestResult(
        backtest_id=bt_id,
        user_id=user_id,
        config=req.config,
        status=BacktestStatus.PENDING,
        created_at=now
    )
    await bt_repo.create_backtest(init_result)

    # 提交异步 DomainTask
    from app.core.database import get_mongo_db
    task_repo = DomainTaskRepository(db=get_mongo_db())

    payload = {
        "config": req.config.model_dump(),
        "prices_data": req.prices_data or [],
        "factors_data": req.factors_data or [],
        "benchmark_prices": req.benchmark_prices or {}
    }

    task = DomainTask(
        task_id=bt_id,
        user_id=user_id,
        task_type=TaskType.BACKTEST_SIMULATION,
        status=TaskStatus.PENDING,
        payload=payload,
        created_at=now,
        updated_at=now
    )
    await task_repo.create_task(task)

    return {"backtest_id": bt_id, "status": "pending", "message": "Backtest task submitted successfully"}


@router.get("", response_model=List[Dict[str, Any]])
async def list_backtests(
    user_id: str = Depends(AuthService.get_canonical_user_id),
    is_admin: bool = Depends(check_is_admin)
):
    bt_repo = BacktestRepository()
    results = await bt_repo.list_backtests(user_id=user_id, is_admin=is_admin)
    return [r.model_dump() for s in results for r in [s]]


@router.get("/{backtest_id}", response_model=Dict[str, Any])
async def get_backtest(
    backtest_id: str,
    user_id: str = Depends(AuthService.get_canonical_user_id),
    is_admin: bool = Depends(check_is_admin)
):
    bt_repo = BacktestRepository()
    bt = await bt_repo.get_backtest(backtest_id)
    if not bt:
        raise HTTPException(status_code=404, detail="Backtest not found")
    if bt.user_id != user_id and not is_admin:
        raise HTTPException(status_code=403, detail="Forbidden")

    return bt.model_dump()


@router.get("/{backtest_id}/result", response_model=Dict[str, Any])
async def get_backtest_result(
    backtest_id: str,
    user_id: str = Depends(AuthService.get_canonical_user_id),
    is_admin: bool = Depends(check_is_admin)
):
    bt_repo = BacktestRepository()
    bt = await bt_repo.get_backtest(backtest_id)
    if not bt:
        raise HTTPException(status_code=404, detail="Backtest not found")
    if bt.user_id != user_id and not is_admin:
        raise HTTPException(status_code=403, detail="Forbidden")

    return {
        "backtest_id": bt.backtest_id,
        "status": bt.status,
        "metrics": bt.metrics.model_dump() if bt.metrics else None,
        "equity_curve": [e.model_dump() for e in bt.equity_curve],
        "fills": [f.model_dump() for f in bt.fills]
    }


@router.delete("/{backtest_id}", response_model=Dict[str, Any])
async def delete_backtest(
    backtest_id: str,
    user_id: str = Depends(AuthService.get_canonical_user_id),
    is_admin: bool = Depends(check_is_admin)
):
    bt_repo = BacktestRepository()
    try:
        deleted = await bt_repo.delete_backtest(backtest_id, user_id=user_id, is_admin=is_admin)
        return {"backtest_id": backtest_id, "deleted": deleted}
    except BacktestNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except BacktestForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

class CompareBacktestsRequest(BaseModel):
    backtest_ids: List[str]


@router.post("/compare", response_model=Dict[str, Any])
async def compare_backtests(
    req: CompareBacktestsRequest,
    user_id: str = Depends(AuthService.get_canonical_user_id),
    is_admin: bool = Depends(check_is_admin)
):
    if not req.backtest_ids or len(req.backtest_ids) < 1:
        raise HTTPException(status_code=400, detail="Must provide at least one backtest_id to compare")

    bt_repo = BacktestRepository()
    results = []

    for bt_id in req.backtest_ids:
        bt = await bt_repo.get_backtest(bt_id)
        if not bt:
            raise HTTPException(status_code=404, detail=f"Backtest {bt_id} not found")
        if bt.user_id != user_id and not is_admin:
            raise HTTPException(status_code=403, detail=f"Forbidden access to backtest {bt_id}")
        results.append(bt)

    from app.services.backtest.comparison import BacktestComparisonService
    return BacktestComparisonService.compare_backtests(results)
