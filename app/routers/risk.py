from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Header, status
from pydantic import BaseModel

from app.models.risk import RiskConfig
from app.services.risk.pre_trade import PreTradeRiskService
from app.repositories.risk_repository import RiskRepository
from app.services.auth_service import AuthService

router = APIRouter(prefix="/api/risk", tags=["Risk"])


class PreTradeCheckRequest(BaseModel):
    config: RiskConfig
    total_equity: float
    cash: float
    positions: Dict[str, Dict[str, Any]]
    proposed_trades: List[Dict[str, Any]]
    historical_returns: Optional[List[float]] = None
    current_drawdown: float = 0.0


def check_is_admin(x_user_role: Optional[str] = Header(None)) -> bool:
    return bool(x_user_role and x_user_role.lower() in ("admin", "superuser", "system"))


@router.post("/pre-trade/check", response_model=Dict[str, Any])
async def check_pre_trade_risk(
    req: PreTradeCheckRequest,
    user_id: str = Depends(AuthService.get_canonical_user_id)
):
    service = PreTradeRiskService()
    res = service.check_pre_trade_orders(
        config=req.config,
        total_equity=req.total_equity,
        cash=req.cash,
        positions=req.positions,
        proposed_trades=req.proposed_trades,
        historical_returns=req.historical_returns,
        current_drawdown=req.current_drawdown
    )

    # 记录审计日志
    from app.models.risk import RiskEvaluationResult
    eval_obj = RiskEvaluationResult(**res["evaluation"])
    repo = RiskRepository()
    await repo.save_audit_log(user_id, eval_obj)

    return res


@router.get("/audit-logs", response_model=List[Dict[str, Any]])
async def list_risk_audit_logs(
    limit: int = 50,
    offset: int = 0,
    user_id: str = Depends(AuthService.get_canonical_user_id),
    is_admin: bool = Depends(check_is_admin)
):
    repo = RiskRepository()
    logs = await repo.list_audit_logs(user_id=user_id, is_admin=is_admin, limit=limit, offset=offset)
    return logs
