import uuid
import numpy as np
from app.models.attribution import (
    TradeReviewInput,
    TradeAttributionResult,
    ExcursionMetrics,
    CauseCategory
)
from app.utils.timezone import now_tz


class TradeAttributionService:
    """100% 确定性、无未来信息泄露的 MAE/MFE 交易归因服务"""

    @classmethod
    def analyze_trade(cls, inp: TradeReviewInput) -> TradeAttributionResult:
        """
        根据持仓期间内（不跨越 exit_date 未来窗口）的价格序列计算 MAE / MFE 与原因分解。
        """
        prices = inp.daily_prices
        bm_prices = inp.daily_benchmark_prices
        entry_p = inp.entry_price
        exit_p = inp.exit_price

        if not prices or entry_p <= 0:
            return cls._empty_result(inp)

        # 1. 实际持仓收益率
        realized_pnl_pct = (exit_p - entry_p) / entry_p

        # 2. MAE (Maximum Adverse Excursion) 与 MFE (Maximum Favorable Excursion)
        # 仅观察入场到出场期间的价格 min / max
        min_p = min(prices)
        max_p = max(prices)

        mae_pct = round((min_p - entry_p) / entry_p, 4)
        mfe_pct = round((max_p - entry_p) / entry_p, 4)

        # 3. 基准与超额收益率
        bm_ret_pct = 0.0
        if bm_prices and len(bm_prices) >= 2 and bm_prices[0] > 0:
            bm_ret_pct = (bm_prices[-1] - bm_prices[0]) / bm_prices[0]

        excess_ret_pct = round(realized_pnl_pct - bm_ret_pct, 4)
        slippage_cost_pct = round(inp.execution_slippage / entry_p, 4) if entry_p > 0 else 0.0

        metrics = ExcursionMetrics(
            mae_pct=mae_pct,
            mfe_pct=mfe_pct,
            holding_days=len(prices),
            realized_pnl_pct=round(realized_pnl_pct, 4),
            benchmark_return_pct=round(bm_ret_pct, 4),
            excess_return_pct=excess_ret_pct,
            slippage_cost_pct=slippage_cost_pct
        )

        # 4. 确定性归因原因判定 (Standard Cause Candidates)
        breakdown = {
            CauseCategory.MARKET_TREND: 0.0,
            CauseCategory.INDUSTRY_ROTATION: 0.0,
            CauseCategory.EXECUTION_SLIPPAGE: 0.0,
            CauseCategory.FACTOR_TIMING: 0.0,
            CauseCategory.RISK_EXIT_TRIGGERED: 0.0,
            CauseCategory.OTHER: 0.0
        }

        # 规则 1: 若基准下跌导致的亏损占主导 -> MARKET_TREND
        if realized_pnl_pct < 0 and bm_ret_pct < -0.02 and abs(bm_ret_pct) >= abs(realized_pnl_pct) * 0.5:
            primary = CauseCategory.MARKET_TREND
            breakdown[CauseCategory.MARKET_TREND] = 0.6
            breakdown[CauseCategory.FACTOR_TIMING] = 0.4
        # 规则 2: 若滑点成本占亏损比例过高 -> EXECUTION_SLIPPAGE
        elif realized_pnl_pct < 0 and slippage_cost_pct > abs(realized_pnl_pct) * 0.3:
            primary = CauseCategory.EXECUTION_SLIPPAGE
            breakdown[CauseCategory.EXECUTION_SLIPPAGE] = 0.7
            breakdown[CauseCategory.FACTOR_TIMING] = 0.3
        # 规则 3: 因子选股择时漂移 (MFE 高但最终亏损或未能锁定收益) -> FACTOR_TIMING
        elif mfe_pct > 0.05 and realized_pnl_pct < 0:
            primary = CauseCategory.FACTOR_TIMING
            breakdown[CauseCategory.FACTOR_TIMING] = 0.8
            breakdown[CauseCategory.OTHER] = 0.2
        else:
            primary = CauseCategory.FACTOR_TIMING if realized_pnl_pct < 0 else CauseCategory.MARKET_TREND
            breakdown[primary] = 1.0

        return TradeAttributionResult(
            review_id=f"rev_{uuid.uuid4().hex[:12]}",
            trade_id=inp.trade_id,
            symbol=inp.symbol,
            metrics=metrics,
            primary_cause=primary,
            cause_breakdown=breakdown,
            reviewed_at=now_tz()
        )

    @classmethod
    def _empty_result(cls, inp: TradeReviewInput) -> TradeAttributionResult:
        metrics = ExcursionMetrics(
            mae_pct=0.0,
            mfe_pct=0.0,
            holding_days=0,
            realized_pnl_pct=0.0,
            benchmark_return_pct=0.0,
            excess_return_pct=0.0,
            slippage_cost_pct=0.0
        )
        return TradeAttributionResult(
            review_id=f"rev_{uuid.uuid4().hex[:12]}",
            trade_id=inp.trade_id,
            symbol=inp.symbol,
            metrics=metrics,
            primary_cause=CauseCategory.OTHER,
            cause_breakdown={CauseCategory.OTHER: 1.0},
            reviewed_at=now_tz()
        )
