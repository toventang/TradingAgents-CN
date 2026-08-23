from typing import Dict, Any, List, Optional
from app.models.risk import RiskConfig, RiskEvaluationResult, RiskDecision, RiskSeverity
from app.services.risk.engine import RiskEvaluationEngine


class PreTradeRiskService:
    """盘前/交易前风控检查与订单拦截服务"""

    def __init__(self, engine: Optional[RiskEvaluationEngine] = None):
        self.engine = engine or RiskEvaluationEngine()

    def check_pre_trade_orders(
        self,
        config: RiskConfig,
        total_equity: float,
        cash: float,
        positions: Dict[str, Dict[str, Any]],
        proposed_trades: List[Dict[str, Any]],
        historical_returns: Optional[List[float]] = None,
        current_drawdown: float = 0.0
    ) -> Dict[str, Any]:
        """
        评估拟提交订单。若触发 CRITICAL 风控规则，拦截对应订单并判定 REJECTED。
        """
        eval_result = self.engine.evaluate_portfolio(
            config=config,
            total_equity=total_equity,
            cash=cash,
            positions=positions,
            proposed_trades=proposed_trades,
            historical_returns=historical_returns,
            current_drawdown=current_drawdown
        )

        is_blocked = eval_result.decision == RiskDecision.REJECTED
        blocked_orders = []
        approved_orders = []

        if is_blocked:
            blocked_orders = proposed_trades
        else:
            approved_orders = proposed_trades

        return {
            "evaluation": eval_result.model_dump(),
            "is_blocked": is_blocked,
            "blocked_orders": blocked_orders,
            "approved_orders": approved_orders
        }
