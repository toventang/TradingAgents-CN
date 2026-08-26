import uuid
from typing import Dict, Any, List, Optional
from app.models.attribution import (
    PostExitWindow,
    MissedUpsideSeverity,
    CounterfactualPath,
    CounterfactualResult
)
from app.utils.timezone import now_tz


class CounterfactualService:
    """错失收益与合法反事实分析服务 (5d, 10d, 20d, 60d 可交易路线)"""

    @classmethod
    def analyze_post_exit_paths(
        self,
        trade_id: str,
        symbol: str,
        exit_price: float,
        post_exit_prices: List[float],             # 出场后最多 60 日每日收盘价
        post_exit_bm_prices: List[float]          # 出场后同日期基准价格
    ) -> CounterfactualResult:
        """
        计算离场后 5d, 10d, 20d, 60d 真实可交易收盘价变动与超额收益。
        不以未来最高价作为可实现利润（符合 Legal Counterfactual 约束）。
        """
        window_days = {
            PostExitWindow.DAYS_5: 5,
            PostExitWindow.DAYS_10: 10,
            PostExitWindow.DAYS_20: 20,
            PostExitWindow.DAYS_60: 60
        }

        paths: Dict[PostExitWindow, CounterfactualPath] = {}
        max_excess = -1.0

        bm_exit_base = post_exit_bm_prices[0] if post_exit_bm_prices else 0.0

        for win, days in window_days.items():
            if len(post_exit_prices) >= days and exit_price > 0:
                p_after = post_exit_prices[days - 1]
                ret_after = (p_after - exit_price) / exit_price

                bm_ret = 0.0
                if len(post_exit_bm_prices) >= days and bm_exit_base > 0:
                    bm_ret = (post_exit_bm_prices[days - 1] - bm_exit_base) / bm_exit_base

                excess = round(ret_after - bm_ret, 4)
                max_excess = max(max_excess, excess)

                paths[win] = CounterfactualPath(
                    window=win,
                    days_after_exit=days,
                    exit_price=exit_price,
                    post_exit_price=p_after,
                    return_after_exit_pct=round(ret_after, 4),
                    benchmark_return_pct=round(bm_ret, 4),
                    excess_return_pct=excess
                )

        # 评估错失收益严重程度
        if max_excess > 0.20:
            severity = MissedUpsideSeverity.SEVERE_MISSED_UPSIDE
        elif max_excess > 0.08:
            severity = MissedUpsideSeverity.MILD_MISSED_UPSIDE
        else:
            severity = MissedUpsideSeverity.TIMELY_EXIT

        return CounterfactualResult(
            trade_id=trade_id,
            symbol=symbol,
            paths=paths,
            max_post_exit_excess_pct=max_excess if max_excess != -1.0 else 0.0,
            severity=severity,
            is_legal_tradeable=True,
            analyzed_at=now_tz()
        )
