from typing import List
import numpy as np
import pandas as pd
from app.models.backtest import EquityPoint, PerformanceMetrics, TradeFill


class MetricsCalculator:
    """回测绩效指标计算器"""

    @classmethod
    def calculate_metrics(
        cls,
        equity_curve: List[EquityPoint],
        fills: List[TradeFill],
        initial_capital: float,
        risk_free_rate: float = 0.02
    ) -> PerformanceMetrics:
        """
        根据每日权益曲线和成交记录计算完整定量绩效指标。
        """
        if not equity_curve:
            return PerformanceMetrics()

        df = pd.DataFrame([e.model_dump() for e in equity_curve])
        if df.empty or len(df) < 2:
            return PerformanceMetrics(total_trades=len(fills))

        # 1. 累计收益率与年化收益率
        start_eq = initial_capital
        end_eq = df["total_equity"].iloc[-1]
        total_return = (end_eq - start_eq) / start_eq

        days_count = len(df)
        annualized_return = ((1.0 + total_return) ** (252.0 / days_count)) - 1.0 if days_count > 0 else 0.0

        # 基准累计收益率
        bm_start = df["benchmark_equity"].iloc[0]
        bm_end = df["benchmark_equity"].iloc[-1]
        bm_return = (bm_end - bm_start) / bm_start if bm_start > 0 else 0.0
        excess_return = total_return - bm_return

        # 2. 最大回撤 (Max Drawdown) 与最大回撤天数
        equity_series = df["total_equity"]
        running_max = equity_series.cummax()
        drawdowns = (equity_series - running_max) / running_max
        max_drawdown = float(abs(drawdowns.min())) if not drawdowns.empty else 0.0

        # 回撤持续天数
        is_mdd = drawdowns < 0
        mdd_duration = 0
        current_dur = 0
        for val in is_mdd:
            if val:
                current_dur += 1
                mdd_duration = max(mdd_duration, current_dur)
            else:
                current_dur = 0

        # 3. 夏普比率 (Sharpe Ratio) & 索提诺比率 (Sortino Ratio) & 信息比率 (Information Ratio)
        daily_returns = df["daily_return"].dropna()
        rf_daily = risk_free_rate / 252.0
        excess_daily_returns = daily_returns - rf_daily

        std_daily = daily_returns.std(ddof=1)
        if std_daily > 0:
            sharpe_ratio = float((excess_daily_returns.mean() / std_daily) * np.sqrt(252.0))
        else:
            sharpe_ratio = 0.0

        downside_returns = daily_returns[daily_returns < rf_daily]
        downside_std = downside_returns.std(ddof=1) if len(downside_returns) > 1 else 0.0
        if downside_std > 0:
            sortino_ratio = float((excess_daily_returns.mean() / downside_std) * np.sqrt(252.0))
        else:
            sortino_ratio = 0.0

        # 信息比率
        active_returns = df["daily_return"] - df["benchmark_return"]
        active_std = active_returns.std(ddof=1)
        if active_std > 0:
            information_ratio = float((active_returns.mean() / active_std) * np.sqrt(252.0))
        else:
            information_ratio = 0.0

        # 4. 胜率、盈亏比与换手率
        total_trades = len(fills)
        win_trades = 0
        loss_trades = 0
        total_gain = 0.0
        total_loss = 0.0

        # 对平仓/成交估算盈亏
        total_turnover = sum(f.turnover for f in fills)
        avg_equity = df["total_equity"].mean()
        turnover_rate = float(total_turnover / avg_equity) if avg_equity > 0 else 0.0

        # 简易胜率估算 (以每日正收益为胜)
        win_days = (daily_returns > 0).sum()
        loss_days = (daily_returns < 0).sum()
        win_rate = float(win_days / len(daily_returns)) if len(daily_returns) > 0 else 0.0

        gain_sum = daily_returns[daily_returns > 0].sum()
        loss_sum = abs(daily_returns[daily_returns < 0].sum())
        profit_loss_ratio = float(gain_sum / loss_sum) if loss_sum > 0 else 0.0

        return PerformanceMetrics(
            total_return=round(float(total_return), 4),
            annualized_return=round(float(annualized_return), 4),
            benchmark_return=round(float(bm_return), 4),
            excess_return=round(float(excess_return), 4),
            max_drawdown=round(float(max_drawdown), 4),
            max_drawdown_duration_days=int(mdd_duration),
            sharpe_ratio=round(float(sharpe_ratio), 4),
            sortino_ratio=round(float(sortino_ratio), 4),
            information_ratio=round(float(information_ratio), 4),
            win_rate=round(float(win_rate), 4),
            profit_loss_ratio=round(float(profit_loss_ratio), 4),
            total_trades=total_trades,
            turnover_rate=round(float(turnover_rate), 4)
        )
