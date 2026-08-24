from typing import Dict, Any, List, Optional
import pandas as pd

from app.models.backtest import EquityPoint, PerformanceMetrics
from app.services.backtest.metrics import MetricsCalculator
from app.repositories.paper_repository import PaperRepository


class CampaignPerformanceService:
    """Campaign 定量绩效与机会成本计算服务"""

    def __init__(self, paper_repo: Optional[PaperRepository] = None):
        self.paper_repo = paper_repo or PaperRepository()

    async def calculate_campaign_performance(
        self,
        campaign_id: str,
        portfolio_id: str,
        initial_capital: float,
        daily_equity_curve: List[EquityPoint]
    ) -> Dict[str, Any]:
        """
        计算 Campaign 的定量绩效指标与机会成本 (Opportunity Cost)。
        """
        if not daily_equity_curve:
            return {
                "metrics": PerformanceMetrics().model_dump(),
                "opportunity_cost": {"benchmark_excess": 0.0, "cash_baseline_excess": 0.0}
            }

        metrics = MetricsCalculator.calculate_metrics(daily_equity_curve, [], initial_capital)

        # 计算机会成本 (超越对比基准与纯现金持有收益)
        last_pt = daily_equity_curve[-1]
        camp_total_return = (last_pt.total_equity - initial_capital) / initial_capital if initial_capital > 0 else 0.0
        bm_total_return = (last_pt.benchmark_equity - initial_capital) / initial_capital if initial_capital > 0 else 0.0

        bm_excess = round(camp_total_return - bm_total_return, 4)
        cash_excess = round(camp_total_return - 0.0, 4)

        return {
            "metrics": metrics.model_dump(),
            "opportunity_cost": {
                "benchmark_excess": bm_excess,
                "cash_baseline_excess": cash_excess
            }
        }
