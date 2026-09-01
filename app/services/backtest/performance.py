"""Deterministic backtest metrics calculated only from structured ledgers.

All ratios use ``Decimal`` with a fixed local precision. Daily dispersion uses
sample standard deviation; downside deviation uses the population lower partial
moment over every return observation. Undefined ratios are returned as ``None``
instead of infinity or a fabricated zero.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext
from typing import Mapping, Sequence

from app.models.backtest import (
    BacktestClosedLot,
    BacktestPerformanceConfig,
    BacktestPerformanceReport,
    BacktestPeriodReturn,
    BrokerOrderStatus,
    OrderSide,
)
from app.services.backtest.ledger import (
    MONEY_TOLERANCE,
    BacktestEquityDailyRecord,
    BacktestEventRecord,
    BacktestOrderRecord,
    BacktestPositionDailyRecord,
    BacktestTradeRecord,
)


FORMULAS = {
    "initial_equity": "positive initial capital supplied by the immutable run request",
    "final_equity": "equity on the final ordered ledger date",
    "return_observations": "number of ordered daily equity ledger rows",
    "total_return": "final_equity / initial_equity - 1",
    "cagr": "(final_equity / initial_equity) ** (annualization_periods / return_observations) - 1",
    "mean_daily_return": "arithmetic mean of equity_t / equity_(t-1) - 1, including initial equity as t0",
    "annualized_volatility": "sample_std(daily_returns) * sqrt(annualization_periods)",
    "daily_risk_free_rate": "(1 + annual_risk_free_rate) ** (1 / annualization_periods) - 1",
    "sharpe_ratio": "mean(daily_return - daily_risk_free_rate) / sample_std(daily_returns) * sqrt(annualization_periods)",
    "annualized_downside_deviation": "sqrt(mean(min(daily_return - daily_risk_free_rate, 0) ** 2)) * sqrt(annualization_periods)",
    "sortino_ratio": "mean(daily_return - daily_risk_free_rate) * annualization_periods / annualized_downside_deviation",
    "max_drawdown": "minimum(equity / running_peak_equity - 1), including initial equity baseline",
    "max_drawdown_start_date": "date of running peak preceding maximum drawdown; None denotes initial capital baseline",
    "max_drawdown_end_date": "date of the maximum drawdown trough",
    "max_drawdown_recovery_date": "first later date equity reaches the preceding peak; None when unrecovered",
    "calmar_ratio": "CAGR / abs(max_drawdown)",
    "benchmark_total_return": "final_benchmark_equity / initial_equity - 1",
    "relative_total_return": "strategy_total_return - benchmark_total_return",
    "beta": "sample_covariance(strategy_returns, benchmark_returns) / sample_variance(benchmark_returns)",
    "annualized_alpha": "mean(strategy_return - rf_daily - beta * (benchmark_return - rf_daily)) * annualization_periods",
    "tracking_error": "sample_std(strategy_return - benchmark_return) * sqrt(annualization_periods)",
    "information_ratio": "mean(strategy_return - benchmark_return) * annualization_periods / tracking_error",
    "closed_lot_pnl": "FIFO by (trade_date, order_id, trade_id): allocated net sell proceeds - fee-inclusive buy cost",
    "closed_lot_return": "closed_lot_pnl / fee-inclusive FIFO buy cost",
    "closed_lot_count": "number of fee-inclusive FIFO buy/sell matches",
    "winning_lot_count": "count FIFO matches with PnL > 0",
    "losing_lot_count": "count FIFO matches with PnL < 0",
    "breakeven_lot_count": "count FIFO matches with PnL = 0",
    "win_rate": "profitable FIFO closed lots / all FIFO closed lots",
    "loss_rate": "losing FIFO closed lots / all FIFO closed lots",
    "profit_loss_ratio": "average profitable lot PnL / abs(average losing lot PnL)",
    "profit_factor": "sum(profitable lot PnL) / abs(sum(losing lot PnL))",
    "gross_winning_pnl": "sum(max(closed_lot_pnl, 0))",
    "gross_losing_pnl": "sum(min(closed_lot_pnl, 0))",
    "net_closed_pnl": "sum(all FIFO closed lot PnL)",
    "average_closed_lot_pnl": "arithmetic mean of FIFO closed lot PnL",
    "median_closed_lot_pnl": "median of FIFO closed lot PnL",
    "average_closed_lot_return": "arithmetic mean of FIFO closed lot returns",
    "median_closed_lot_return": "median of FIFO closed lot returns",
    "maximum_winning_pnl": "maximum profitable FIFO closed lot PnL",
    "maximum_losing_pnl": "minimum losing FIFO closed lot PnL",
    "holding_sessions": "count of equity sessions where entry_date < session_date <= exit_date",
    "average_holding_sessions": "arithmetic mean of FIFO closed lot holding sessions",
    "median_holding_sessions": "median of FIFO closed lot holding sessions",
    "total_turnover": "sum(daily traded notional / previous equity)",
    "average_daily_turnover": "arithmetic mean of daily turnover",
    "total_fees": "sum(all fee components recorded on fills)",
    "total_slippage_cost": "sum((fill-raw)*qty for buys and (raw-fill)*qty for sells)",
    "fee_to_gross_profit_ratio": "total_fees / (final_equity - initial_equity + total_fees), when denominator is positive",
    "cash_ratio": "cash / equity",
    "average_gross_exposure": "arithmetic mean of daily gross exposure",
    "maximum_gross_exposure": "maximum daily gross exposure",
    "average_net_exposure": "arithmetic mean of daily net exposure",
    "maximum_net_exposure": "maximum daily net exposure",
    "average_cash_ratio": "arithmetic mean of daily cash / equity",
    "minimum_cash_ratio": "minimum daily cash / equity",
    "maximum_cash_ratio": "maximum daily cash / equity",
    "final_cash_ratio": "final-day cash / final-day equity",
    "stock_concentration": "maximum recorded single-stock portfolio weight",
    "industry_concentration": "maximum daily sum of position weights grouped by supplied industry classification",
    "monthly_returns": "compound daily returns within each calendar month",
    "yearly_returns": "compound daily returns within each calendar year",
    "exit_reason_distribution": "count distinct filled sell order IDs by deterministic exit reason mapping",
    "trade_count": "count immutable fill records",
    "rejected_order_count": "count distinct orders with a rejected final state or rejection event",
    "partially_filled_order_count": "count distinct orders with a partial-fill state or event",
}


class PerformanceCalculationError(ValueError):
    code = "BACKTEST_PERFORMANCE_INVALID"


@dataclass
class _OpenLot:
    trade_id: str
    order_id: str
    symbol: str
    trade_date: date
    remaining_quantity: int
    unit_cost: Decimal


class BacktestPerformanceCalculator:
    def calculate(
        self,
        *,
        initial_equity: Decimal,
        equity: Sequence[BacktestEquityDailyRecord],
        trades: Sequence[BacktestTradeRecord] = (),
        orders: Sequence[BacktestOrderRecord] = (),
        positions: Sequence[BacktestPositionDailyRecord] = (),
        events: Sequence[BacktestEventRecord] = (),
        config: BacktestPerformanceConfig | None = None,
        industry_by_symbol: Mapping[str, str] | None = None,
        exit_reason_by_order_id: Mapping[str, str] | None = None,
    ) -> BacktestPerformanceReport:
        config = config or BacktestPerformanceConfig()
        with localcontext() as context:
            context.prec = 40
            return self._calculate(
                initial_equity=initial_equity,
                equity=equity,
                trades=trades,
                orders=orders,
                positions=positions,
                events=events,
                config=config,
                industry_by_symbol=industry_by_symbol or {},
                exit_reason_by_order_id=exit_reason_by_order_id or {},
            )

    def _calculate(
        self,
        *,
        initial_equity: Decimal,
        equity: Sequence[BacktestEquityDailyRecord],
        trades: Sequence[BacktestTradeRecord],
        orders: Sequence[BacktestOrderRecord],
        positions: Sequence[BacktestPositionDailyRecord],
        events: Sequence[BacktestEventRecord],
        config: BacktestPerformanceConfig,
        industry_by_symbol: Mapping[str, str],
        exit_reason_by_order_id: Mapping[str, str],
    ) -> BacktestPerformanceReport:
        initial_equity = _finite(initial_equity, "initial_equity")
        if initial_equity <= 0:
            raise PerformanceCalculationError("initial equity must be positive")
        rows = tuple(sorted(equity, key=lambda item: item.trade_date))
        if not rows:
            raise PerformanceCalculationError("at least one equity row is required")
        if len({item.trade_date for item in rows}) != len(rows):
            raise PerformanceCalculationError("equity dates must be unique")
        self._validate_ledger(rows, trades, orders, positions, events)
        for row in rows:
            _finite(row.cash, "cash")
            _finite(row.market_value, "market_value")
            value = _finite(row.equity, "equity")
            if value <= 0:
                raise PerformanceCalculationError("equity must remain positive")
            if abs(row.cash + row.market_value - row.equity) > MONEY_TOLERANCE:
                raise PerformanceCalculationError("daily equity does not reconcile")

        equities = tuple(item.equity for item in rows)
        daily_returns = _returns(initial_equity, equities)
        periods = Decimal(config.annualization_periods)
        observation_count = len(daily_returns)
        final_equity = equities[-1]
        total_return = final_equity / initial_equity - 1
        cagr = _decimal_power(
            final_equity / initial_equity,
            periods / Decimal(observation_count),
        ) - 1
        mean_return = _mean(daily_returns)
        daily_rf = _decimal_power(
            Decimal("1") + config.annual_risk_free_rate,
            Decimal("1") / periods,
        ) - 1
        excess_returns = tuple(item - daily_rf for item in daily_returns)
        daily_std = _sample_std(daily_returns)
        annual_volatility = (daily_std or Decimal("0")) * periods.sqrt()
        sharpe = (
            None
            if daily_std in (None, Decimal("0"))
            else _mean(excess_returns) / daily_std * periods.sqrt()
        )
        downside_daily = (
            _mean(tuple(min(item, Decimal("0")) ** 2 for item in excess_returns))
        ).sqrt()
        annual_downside = downside_daily * periods.sqrt()
        sortino = (
            None
            if annual_downside == 0
            else _mean(excess_returns) * periods / annual_downside
        )
        drawdown, drawdown_start, drawdown_end, recovery = _drawdown(rows, initial_equity)
        calmar = None if drawdown == 0 else cagr / abs(drawdown)

        warnings: list[str] = []
        if observation_count < config.minimum_return_observations:
            warnings.append(
                f"RETURN_SAMPLE_INSUFFICIENT:{observation_count}<{config.minimum_return_observations}"
            )
        if len(trades) < config.minimum_trade_count:
            warnings.append(
                f"TRADE_SAMPLE_INSUFFICIENT:{len(trades)}<{config.minimum_trade_count}"
            )
        if daily_std in (None, Decimal("0")):
            warnings.append("ZERO_RETURN_VOLATILITY")
        if annual_downside == 0:
            warnings.append("NO_DOWNSIDE_DEVIATION")
        if drawdown == 0:
            warnings.append("NO_DRAWDOWN")

        benchmark = self._benchmark_metrics(
            rows, initial_equity, daily_returns, daily_rf, periods, warnings
        )
        reasons = self._exit_reasons(events, exit_reason_by_order_id)
        closed_lots = self._fifo_closed_lots(trades, rows, reasons)
        closed = self._closed_lot_metrics(closed_lots)
        costs = self._cost_metrics(trades, rows, initial_equity)
        concentration = self._concentration_metrics(
            rows, positions, industry_by_symbol, warnings
        )
        counts = self._execution_counts(trades, orders, events)
        dated_returns = tuple(
            (rows[index].trade_date, daily_returns[index])
            for index in range(observation_count)
        )

        return BacktestPerformanceReport(
            initial_equity=initial_equity,
            final_equity=final_equity,
            return_observations=observation_count,
            total_return=total_return,
            cagr=cagr,
            mean_daily_return=mean_return,
            annualized_volatility=annual_volatility,
            annual_risk_free_rate=config.annual_risk_free_rate,
            daily_risk_free_rate=daily_rf,
            sharpe_ratio=sharpe,
            annualized_downside_deviation=annual_downside,
            sortino_ratio=sortino,
            max_drawdown=drawdown,
            max_drawdown_start_date=drawdown_start,
            max_drawdown_end_date=drawdown_end,
            max_drawdown_recovery_date=recovery,
            calmar_ratio=calmar,
            **benchmark,
            **closed,
            **costs,
            **concentration,
            **counts,
            monthly_returns=_period_returns(dated_returns, monthly=True),
            yearly_returns=_period_returns(dated_returns, monthly=False),
            exit_reason_distribution=_exit_distribution(trades, reasons),
            closed_lots=closed_lots,
            warnings=tuple(warnings),
            formulas=dict(FORMULAS),
        )

    @staticmethod
    def _validate_ledger(rows, trades, orders, positions, events) -> None:
        run_ids = {
            item.run_id for item in (*rows, *trades, *orders, *positions, *events)
        }
        user_ids = {
            item.user_id for item in (*rows, *trades, *orders, *positions, *events)
        }
        if len(run_ids) != 1 or len(user_ids) != 1:
            raise PerformanceCalculationError(
                "performance inputs must share one run and owner"
            )
        if len({item.trade_id for item in trades}) != len(trades):
            raise PerformanceCalculationError("trade IDs must be unique")
        if len({item.order_id for item in orders}) != len(orders):
            raise PerformanceCalculationError("order IDs must be unique")
        position_keys = {(item.trade_date, item.symbol) for item in positions}
        if len(position_keys) != len(positions):
            raise PerformanceCalculationError("daily position identities must be unique")
        valid_dates = {item.trade_date for item in rows}
        if any(item.trade_date not in valid_dates for item in (*trades, *positions, *events)):
            raise PerformanceCalculationError(
                "trades, positions, and events must fall on equity dates"
            )

    @staticmethod
    def _benchmark_metrics(rows, initial, strategy_returns, daily_rf, periods, warnings):
        observations = sum(item.benchmark_equity is not None for item in rows)
        empty = {
            "benchmark_observations": observations,
            "benchmark_total_return": None,
            "relative_total_return": None,
            "beta": None,
            "annualized_alpha": None,
            "tracking_error": None,
            "information_ratio": None,
        }
        if observations == 0:
            warnings.append("BENCHMARK_UNAVAILABLE")
            return empty
        if observations != len(rows):
            warnings.append("BENCHMARK_INCOMPLETE")
            return empty
        benchmark_equities = tuple(
            _finite(item.benchmark_equity, "benchmark_equity") for item in rows
        )
        if any(item <= 0 for item in benchmark_equities):
            raise PerformanceCalculationError("benchmark equity must be positive")
        benchmark_returns = _returns(initial, benchmark_equities)
        benchmark_total = benchmark_equities[-1] / initial - 1
        strategy_total = rows[-1].equity / initial - 1
        result = {
            **empty,
            "benchmark_total_return": benchmark_total,
            "relative_total_return": strategy_total - benchmark_total,
        }
        if len(benchmark_returns) < 2:
            warnings.append("BENCHMARK_SAMPLE_INSUFFICIENT")
            return result
        variance = _sample_variance(benchmark_returns)
        active = tuple(
            strategy - benchmark
            for strategy, benchmark in zip(strategy_returns, benchmark_returns)
        )
        tracking_daily = _sample_std(active)
        tracking = (
            None if tracking_daily is None else tracking_daily * periods.sqrt()
        )
        information = (
            None
            if tracking in (None, Decimal("0"))
            else _mean(active) * periods / tracking
        )
        result.update(
            tracking_error=tracking,
            information_ratio=information,
        )
        if variance == 0:
            warnings.append("BENCHMARK_ZERO_VARIANCE")
            return result
        beta = _sample_covariance(strategy_returns, benchmark_returns) / variance
        alpha = _mean(
            tuple(
                strategy - daily_rf - beta * (benchmark - daily_rf)
                for strategy, benchmark in zip(strategy_returns, benchmark_returns)
            )
        ) * periods
        result.update(beta=beta, annualized_alpha=alpha)
        return result

    @staticmethod
    def _exit_reasons(events, supplied) -> dict[str, str]:
        reasons = {key: value for key, value in supplied.items() if value}
        for event in sorted(events, key=lambda item: (item.trade_date, item.sequence)):
            order_id = event.data.get("order_id")
            reason = event.data.get("exit_reason")
            if order_id and reason:
                reasons.setdefault(str(order_id), str(reason))
        return reasons

    @staticmethod
    def _fifo_closed_lots(trades, rows, reasons) -> tuple[BacktestClosedLot, ...]:
        sessions = tuple(item.trade_date for item in rows)
        open_lots: dict[str, list[_OpenLot]] = defaultdict(list)
        result: list[BacktestClosedLot] = []
        ordered = sorted(
            trades,
            key=lambda item: (
                item.trade_date,
                item.order_id,
                item.trade_id,
            ),
        )
        for trade in ordered:
            if trade.side == OrderSide.BUY:
                open_lots[trade.symbol].append(
                    _OpenLot(
                        trade_id=trade.trade_id,
                        order_id=trade.order_id,
                        symbol=trade.symbol,
                        trade_date=trade.trade_date,
                        remaining_quantity=trade.quantity,
                        unit_cost=(trade.notional + trade.fees.total) / trade.quantity,
                    )
                )
                continue
            remaining = trade.quantity
            net_unit_proceeds = (trade.notional - trade.fees.total) / trade.quantity
            lots = open_lots[trade.symbol]
            match_index = 0
            while remaining and lots:
                lot = lots[0]
                quantity = min(remaining, lot.remaining_quantity)
                entry_cost = lot.unit_cost * quantity
                exit_proceeds = net_unit_proceeds * quantity
                pnl = exit_proceeds - entry_cost
                identifier = hashlib.sha256(
                    f"{lot.trade_id}\x1f{trade.trade_id}\x1f{match_index}".encode()
                ).hexdigest()[:40]
                result.append(
                    BacktestClosedLot(
                        closed_lot_id=f"closed-lot:{identifier}",
                        symbol=trade.symbol,
                        buy_trade_id=lot.trade_id,
                        sell_trade_id=trade.trade_id,
                        buy_order_id=lot.order_id,
                        sell_order_id=trade.order_id,
                        quantity=quantity,
                        entry_trade_date=lot.trade_date,
                        exit_trade_date=trade.trade_date,
                        entry_cost=entry_cost,
                        exit_proceeds=exit_proceeds,
                        pnl=pnl,
                        return_rate=pnl / entry_cost,
                        holding_sessions=sum(
                            lot.trade_date < day <= trade.trade_date
                            for day in sessions
                        ),
                        exit_reason=reasons.get(trade.order_id, "unknown"),
                    )
                )
                remaining -= quantity
                lot.remaining_quantity -= quantity
                match_index += 1
                if lot.remaining_quantity == 0:
                    lots.pop(0)
            if remaining:
                raise PerformanceCalculationError(
                    f"sell trade {trade.trade_id} exceeds FIFO buy inventory"
                )
        return tuple(result)

    @staticmethod
    def _closed_lot_metrics(closed_lots):
        pnl = tuple(item.pnl for item in closed_lots)
        returns = tuple(item.return_rate for item in closed_lots)
        holding = tuple(Decimal(item.holding_sessions) for item in closed_lots)
        wins = tuple(item for item in pnl if item > 0)
        losses = tuple(item for item in pnl if item < 0)
        count = len(closed_lots)
        gross_wins = sum(wins, Decimal("0"))
        gross_losses = sum(losses, Decimal("0"))
        return {
            "closed_lot_count": count,
            "winning_lot_count": len(wins),
            "losing_lot_count": len(losses),
            "breakeven_lot_count": count - len(wins) - len(losses),
            "win_rate": None if not count else Decimal(len(wins)) / count,
            "loss_rate": None if not count else Decimal(len(losses)) / count,
            "profit_loss_ratio": (
                None
                if not wins or not losses
                else _mean(wins) / abs(_mean(losses))
            ),
            "profit_factor": (
                None if not losses else gross_wins / abs(gross_losses)
            ),
            "gross_winning_pnl": gross_wins,
            "gross_losing_pnl": gross_losses,
            "net_closed_pnl": sum(pnl, Decimal("0")),
            "average_closed_lot_pnl": None if not pnl else _mean(pnl),
            "median_closed_lot_pnl": None if not pnl else _median(pnl),
            "average_closed_lot_return": None if not returns else _mean(returns),
            "median_closed_lot_return": None if not returns else _median(returns),
            "maximum_winning_pnl": None if not wins else max(wins),
            "maximum_losing_pnl": None if not losses else min(losses),
            "average_holding_sessions": None if not holding else _mean(holding),
            "median_holding_sessions": None if not holding else _median(holding),
        }

    @staticmethod
    def _cost_metrics(trades, rows, initial_equity):
        fees = sum((item.fees.total for item in trades), Decimal("0"))
        slippage = sum(
            (
                (item.fill_price - item.raw_price) * item.quantity
                if item.side == OrderSide.BUY
                else (item.raw_price - item.fill_price) * item.quantity
                for item in trades
            ),
            Decimal("0"),
        )
        turnovers = tuple(item.turnover for item in rows)
        gross_before_fees = rows[-1].equity - initial_equity + fees
        return {
            "total_turnover": sum(turnovers, Decimal("0")),
            "average_daily_turnover": _mean(turnovers),
            "total_fees": fees,
            "total_slippage_cost": slippage,
            "fee_to_gross_profit_ratio": (
                None if gross_before_fees <= 0 else fees / gross_before_fees
            ),
        }

    @staticmethod
    def _concentration_metrics(rows, positions, industries, warnings):
        gross = tuple(item.gross_exposure for item in rows)
        net = tuple(item.net_exposure for item in rows)
        cash = tuple(item.cash / item.equity for item in rows)
        maximum_stock = max(
            (item.weight for item in positions), default=Decimal("0")
        )
        if not positions:
            maximum_industry: Decimal | None = Decimal("0")
        elif any(item.symbol not in industries for item in positions):
            maximum_industry = None
            warnings.append("INDUSTRY_CLASSIFICATION_INCOMPLETE")
        else:
            grouped: dict[tuple[date, str], Decimal] = defaultdict(Decimal)
            for item in positions:
                grouped[(item.trade_date, industries[item.symbol])] += item.weight
            maximum_industry = max(grouped.values(), default=Decimal("0"))
        return {
            "average_gross_exposure": _mean(gross),
            "maximum_gross_exposure": max(gross),
            "average_net_exposure": _mean(net),
            "maximum_net_exposure": max(net),
            "average_cash_ratio": _mean(cash),
            "minimum_cash_ratio": min(cash),
            "maximum_cash_ratio": max(cash),
            "final_cash_ratio": cash[-1],
            "maximum_stock_concentration": maximum_stock,
            "maximum_industry_concentration": maximum_industry,
        }

    @staticmethod
    def _execution_counts(trades, orders, events):
        rejected = {
            item.order_id
            for item in orders
            if item.status == BrokerOrderStatus.REJECTED
        }
        partial = {
            item.order_id
            for item in orders
            if item.status == BrokerOrderStatus.PARTIALLY_FILLED
        }
        for event in events:
            if event.event_type != "ORDER_EXECUTION_RESULT":
                continue
            order_id = event.data.get("order_id")
            status = event.data.get("status")
            if not order_id:
                continue
            if status == BrokerOrderStatus.REJECTED.value:
                rejected.add(str(order_id))
            elif status == BrokerOrderStatus.PARTIALLY_FILLED.value:
                partial.add(str(order_id))
        return {
            "trade_count": len(trades),
            "rejected_order_count": len(rejected),
            "partially_filled_order_count": len(partial),
        }


def calculate_backtest_performance(**kwargs) -> BacktestPerformanceReport:
    """Functional entry point used by workers and future API adapters."""

    return BacktestPerformanceCalculator().calculate(**kwargs)


def _finite(value: Decimal | None, name: str) -> Decimal:
    if value is None:
        raise PerformanceCalculationError(f"{name} is missing")
    result = Decimal(value)
    if not result.is_finite():
        raise PerformanceCalculationError(f"{name} must be finite")
    return result


def _decimal_power(base: Decimal, exponent: Decimal) -> Decimal:
    if base <= 0:
        raise PerformanceCalculationError("fractional power requires a positive base")
    return base**exponent


def _returns(initial: Decimal, values: Sequence[Decimal]) -> tuple[Decimal, ...]:
    previous = initial
    result: list[Decimal] = []
    for value in values:
        result.append(value / previous - 1)
        previous = value
    return tuple(result)


def _mean(values: Sequence[Decimal]) -> Decimal:
    if not values:
        raise PerformanceCalculationError("mean requires observations")
    return sum(values, Decimal("0")) / len(values)


def _median(values: Sequence[Decimal]) -> Decimal:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _sample_variance(values: Sequence[Decimal]) -> Decimal | None:
    if len(values) < 2:
        return None
    mean = _mean(values)
    return sum(((item - mean) ** 2 for item in values), Decimal("0")) / (
        len(values) - 1
    )


def _sample_std(values: Sequence[Decimal]) -> Decimal | None:
    variance = _sample_variance(values)
    return None if variance is None else variance.sqrt()


def _sample_covariance(left: Sequence[Decimal], right: Sequence[Decimal]) -> Decimal:
    if len(left) != len(right) or len(left) < 2:
        raise PerformanceCalculationError("covariance requires paired observations")
    left_mean = _mean(left)
    right_mean = _mean(right)
    return sum(
        (
            (left_item - left_mean) * (right_item - right_mean)
            for left_item, right_item in zip(left, right)
        ),
        Decimal("0"),
    ) / (len(left) - 1)


def _drawdown(rows, initial):
    peak = initial
    peak_date: date | None = None
    worst = Decimal("0")
    worst_start: date | None = None
    worst_end: date | None = None
    worst_peak = initial
    trough_index: int | None = None
    for index, row in enumerate(rows):
        if row.equity >= peak:
            peak = row.equity
            peak_date = row.trade_date
        drawdown = row.equity / peak - 1
        if drawdown < worst:
            worst = drawdown
            worst_start = peak_date
            worst_end = row.trade_date
            worst_peak = peak
            trough_index = index
    recovery = None
    if trough_index is not None:
        recovery = next(
            (
                row.trade_date
                for row in rows[trough_index + 1 :]
                if row.equity >= worst_peak
            ),
            None,
        )
    return worst, worst_start, worst_end, recovery


def _period_returns(dated_returns, *, monthly):
    grouped: dict[str, list[tuple[date, Decimal]]] = defaultdict(list)
    for trade_date, value in dated_returns:
        key = trade_date.strftime("%Y-%m" if monthly else "%Y")
        grouped[key].append((trade_date, value))
    return tuple(
        BacktestPeriodReturn(
            period=key,
            start_date=items[0][0],
            end_date=items[-1][0],
            return_rate=_compound(tuple(item[1] for item in items)),
        )
        for key, items in sorted(grouped.items())
    )


def _compound(values: Sequence[Decimal]) -> Decimal:
    result = Decimal("1")
    for value in values:
        result *= 1 + value
    return result - 1


def _exit_distribution(trades, reasons):
    sell_orders = {
        item.order_id for item in trades if item.side == OrderSide.SELL
    }
    result: dict[str, int] = defaultdict(int)
    for order_id in sorted(sell_orders):
        result[reasons.get(order_id, "unknown")] += 1
    return dict(sorted(result.items()))
