from typing import List, Dict, Any
import pandas as pd
from app.models.backtest import BacktestResult


class BacktestComparisonService:
    """多回测结果定量横向对比服务"""

    @classmethod
    def compare_backtests(cls, results: List[BacktestResult]) -> Dict[str, Any]:
        """
        对比多个回测结果的对齐权益曲线与关键绩效指标差值。
        """
        if not results:
            return {"comparison": [], "aligned_equity_curve": []}

        summary_list = []
        equity_series_dict = {}

        for res in results:
            bt_id = res.backtest_id
            m = res.metrics

            summary_list.append({
                "backtest_id": bt_id,
                "strategy_id": res.config.strategy_id,
                "version_num": res.config.version_num,
                "total_return": m.total_return if m else 0.0,
                "annualized_return": m.annualized_return if m else 0.0,
                "max_drawdown": m.max_drawdown if m else 0.0,
                "sharpe_ratio": m.sharpe_ratio if m else 0.0,
                "excess_return": m.excess_return if m else 0.0,
                "total_trades": m.total_trades if m else 0,
                "turnover_rate": m.turnover_rate if m else 0.0
            })

            # 构建日期 -> total_equity dict
            eq_map = {e.trade_date: e.total_equity for e in res.equity_curve}
            equity_series_dict[bt_id] = eq_map

        # 对齐日期
        all_dates = sorted(list({e.trade_date for res in results for e in res.equity_curve}))
        aligned_curve = []

        for d in all_dates:
            pt = {"trade_date": d}
            for res in results:
                bt_id = res.backtest_id
                pt[bt_id] = equity_series_dict[bt_id].get(d, None)
            aligned_curve.append(pt)

        # 估算相对基准对比 Deltas (以第一个回测为基准)
        deltas = {}
        if len(results) >= 2:
            b1 = summary_list[0]
            for b2 in summary_list[1:]:
                bt_id = b2["backtest_id"]
                deltas[f"{bt_id}_vs_{b1['backtest_id']}"] = {
                    "total_return_delta": round(b2["total_return"] - b1["total_return"], 4),
                    "max_drawdown_delta": round(b2["max_drawdown"] - b1["max_drawdown"], 4),
                    "sharpe_ratio_delta": round(b2["sharpe_ratio"] - b1["sharpe_ratio"], 4),
                    "excess_return_delta": round(b2["excess_return"] - b1["excess_return"], 4)
                }

        return {
            "summary": summary_list,
            "deltas": deltas,
            "aligned_equity_curve": aligned_curve
        }
