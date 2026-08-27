from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import pandas as pd

from app.models.backtest import BacktestConfig, BacktestResult, BacktestStatus, EquityPoint, TradeFill
from app.models.strategy import StrategyVersion
from app.services.strategies.signal_engine import DeterministicSignalEngine
from app.services.backtest.cost_model import CostModelService
from app.services.backtest.metrics import MetricsCalculator
from app.utils.timezone import now_tz


class BacktestExecutionEngine:
    """Point-In-Time 逐日回测执行引擎"""

    def __init__(self, signal_engine: Optional[DeterministicSignalEngine] = None):
        self.signal_engine = signal_engine or DeterministicSignalEngine()

    def run_backtest(
        self,
        backtest_id: str,
        user_id: str,
        config: BacktestConfig,
        strategy_version: StrategyVersion,
        daily_prices_df: pd.DataFrame,      # MultiIndex (date, symbol) -> close, etc.
        daily_factors_df: pd.DataFrame,     # MultiIndex (date, symbol) -> factor_ids
        benchmark_prices: Dict[str, float]  # date -> benchmark close
    ) -> BacktestResult:
        """
        逐日模拟回测：无未来函数、考虑交易调仓与成本滑点扣减。
        """
        cash = config.initial_capital
        positions: Dict[str, int] = {}       # symbol -> quantity
        fills: List[TradeFill] = []
        equity_curve: List[EquityPoint] = []

        # 获取排好序的交易日列表
        if isinstance(daily_prices_df.index, pd.MultiIndex):
            dates = sorted(list(set(daily_prices_df.index.get_level_values(0))))
        else:
            dates = sorted(list(daily_prices_df["date"].unique())) if "date" in daily_prices_df.columns else []

        if not dates:
            return BacktestResult(
                backtest_id=backtest_id,
                user_id=user_id,
                config=config,
                status=BacktestStatus.FAILED,
                error_message="No price data available for the specified date range"
            )

        bm_base_price = None

        for d_idx, trade_date in enumerate(dates):
            # 获取当天的价格数据 snapshot
            try:
                day_prices = daily_prices_df.loc[trade_date]
            except KeyError:
                continue

            if isinstance(day_prices, pd.Series):
                day_prices_map = {day_prices.name: float(day_prices["close"])} if "close" in day_prices else {}
            else:
                day_prices_map = day_prices["close"].to_dict() if "close" in day_prices.columns else {}

            # 获取当天的因子数据 snapshot
            day_factors = pd.DataFrame()
            if daily_factors_df is not None and not daily_factors_df.empty:
                try:
                    day_factors = daily_factors_df.loc[trade_date]
                    # 确保返回 DataFrame，即使只有一行数据
                    if isinstance(day_factors, pd.Series):
                        day_factors = day_factors.to_frame().T
                except (KeyError, TypeError):
                    day_factors = pd.DataFrame()

            # 1. 信号计算与调仓 (Rebalance)
            as_of_dt = datetime.strptime(str(trade_date)[:10], "%Y-%m-%d")
            signals = self.signal_engine.generate_signals(strategy_version, user_id, as_of_dt, day_factors)

            # 评估总权益，计算目标调仓
            mkt_val = sum(positions.get(sym, 0) * day_prices_map.get(sym, 0.0) for sym in positions)
            curr_equity = cash + mkt_val

            target_buy_signals = [s for s in signals if s.signal_type == "buy"]

            if target_buy_signals:
                target_symbols = {s.symbol for s in target_buy_signals}

                # 卖出不在目标列表中的股票
                for sym in list(positions.keys()):
                    if sym not in target_symbols and positions[sym] > 0:
                        qty = positions[sym]
                        price = day_prices_map.get(sym, 0.0)
                        if price > 0:
                            fill = CostModelService.calculate_fill(
                                backtest_id, str(trade_date)[:10], sym, "sell", qty, price, config.cost_model
                            )
                            cash += (fill.turnover - fill.total_cost)
                            fills.append(fill)
                            positions[sym] = 0

                # 重新计算可用现金买入新调仓股票
                target_alloc_per_stock = curr_equity * (1.0 / len(target_buy_signals))
                for s in target_buy_signals:
                    sym = s.symbol
                    price = day_prices_map.get(sym, 0.0)
                    if price > 0:
                        curr_qty = positions.get(sym, 0)
                        target_qty = int(target_alloc_per_stock / (price * (1.0 + config.cost_model.slippage_rate)))
                        diff_qty = target_qty - curr_qty

                        if diff_qty > 0:
                            fill = CostModelService.calculate_fill(
                                backtest_id, str(trade_date)[:10], sym, "buy", diff_qty, price, config.cost_model
                            )
                            required_cash = fill.turnover + fill.total_cost
                            if cash >= required_cash:
                                cash -= required_cash
                                positions[sym] = curr_qty + diff_qty
                                fills.append(fill)

            # 2. 当日收盘盯市 (Mark-to-market)
            total_mkt_val = sum(positions.get(sym, 0) * day_prices_map.get(sym, 0.0) for sym in positions)
            total_eq = cash + total_mkt_val

            bm_price = benchmark_prices.get(str(trade_date)[:10], 1000.0)
            if bm_base_price is None:
                bm_base_price = bm_price
            bm_eq = (bm_price / bm_base_price) * config.initial_capital if bm_base_price > 0 else config.initial_capital

            prev_eq = equity_curve[-1].total_equity if equity_curve else config.initial_capital
            prev_bm_eq = equity_curve[-1].benchmark_equity if equity_curve else config.initial_capital

            d_ret = (total_eq - prev_eq) / prev_eq if prev_eq > 0 else 0.0
            bm_d_ret = (bm_eq - prev_bm_eq) / prev_bm_eq if prev_bm_eq > 0 else 0.0

            eq_pt = EquityPoint(
                trade_date=str(trade_date)[:10],
                cash=round(cash, 2),
                market_value=round(total_mkt_val, 2),
                total_equity=round(total_eq, 2),
                benchmark_equity=round(bm_eq, 2),
                daily_return=round(d_ret, 6),
                benchmark_return=round(bm_d_ret, 6)
            )
            equity_curve.append(eq_pt)

        # 3. 最终定量指标计算
        metrics = MetricsCalculator.calculate_metrics(equity_curve, fills, config.initial_capital)

        return BacktestResult(
            backtest_id=backtest_id,
            user_id=user_id,
            config=config,
            status=BacktestStatus.COMPLETED,
            equity_curve=equity_curve,
            fills=fills,
            metrics=metrics,
            created_at=now_tz(),
            completed_at=now_tz()
        )
