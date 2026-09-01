from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models.backtest import (
    BacktestPerformanceConfig,
    BrokerOrderStatus,
    FeeBreakdown,
    OrderSide,
)
from app.models.symbol import Market
from app.services.backtest.ledger import (
    BacktestEquityDailyRecord,
    BacktestEventRecord,
    BacktestOrderRecord,
    BacktestPositionDailyRecord,
    BacktestTradeRecord,
)
from app.services.backtest.performance import (
    FORMULAS,
    BacktestPerformanceCalculator,
    PerformanceCalculationError,
)


DATES = (
    date(2023, 12, 29),
    date(2024, 1, 2),
    date(2024, 1, 3),
    date(2024, 1, 4),
)


def close(actual: Decimal | None, expected: Decimal, tolerance="1e-15"):
    assert actual is not None
    assert abs(actual - expected) <= Decimal(tolerance)


def equity_rows(values=("110", "88", "110", "121"), benchmarks=("100", "105", "105", "110")):
    cash = ("50", "48", "60", "121")
    market_value = ("60", "40", "50", "0")
    turnover = ("0.2", "0.1", "0.3", "0")
    return tuple(
        BacktestEquityDailyRecord(
            run_id="run-performance",
            user_id="owner",
            trade_date=trade_date,
            cash=Decimal(cash[index]),
            market_value=Decimal(market_value[index]),
            equity=Decimal(value),
            daily_return=None,
            cumulative_return=Decimal(value) / Decimal("100") - 1,
            drawdown=Decimal("0"),
            benchmark_equity=(
                None if benchmarks[index] is None else Decimal(benchmarks[index])
            ),
            turnover=Decimal(turnover[index]),
            gross_exposure=Decimal(market_value[index]) / Decimal(value),
            net_exposure=Decimal(market_value[index]) / Decimal(value),
        )
        for index, (trade_date, value) in enumerate(zip(DATES, values))
    )


def trade(
    trade_id,
    order_id,
    day,
    side,
    quantity,
    raw_price,
    fill_price,
    fee,
):
    fill_price = Decimal(fill_price)
    return BacktestTradeRecord(
        trade_id=trade_id,
        order_id=order_id,
        run_id="run-performance",
        user_id="owner",
        market=Market.CN,
        symbol="600000",
        side=side,
        quantity=quantity,
        raw_price=Decimal(raw_price),
        slippage=fill_price - Decimal(raw_price),
        fill_price=fill_price,
        notional=fill_price * quantity,
        fees=FeeBreakdown(commission=Decimal(fee)),
        trade_date=day,
    )


def order(order_id, day, side, quantity, status=BrokerOrderStatus.FILLED):
    filled = quantity if status == BrokerOrderStatus.FILLED else 0
    return BacktestOrderRecord(
        order_id=order_id,
        run_id="run-performance",
        user_id="owner",
        signal_id=f"signal-{order_id}",
        market=Market.CN,
        symbol="600000",
        side=side,
        requested_qty=quantity,
        filled_qty=filled,
        remaining_qty=quantity - filled,
        order_type="next_open",
        created_trade_date=day,
        expire_date=DATES[-1],
        status=status,
        execution_attempts=1,
    )


def position(day, symbol, market_value, equity, weight):
    return BacktestPositionDailyRecord(
        run_id="run-performance",
        user_id="owner",
        trade_date=day,
        market=Market.CN,
        symbol=symbol,
        quantity=10,
        available_qty=10,
        avg_cost=Decimal(market_value) / 10,
        close=Decimal(market_value) / 10,
        market_value=Decimal(market_value),
        unrealized_pnl=Decimal("0"),
        weight=Decimal(weight),
        holding_days=1,
    )


def ledger_fixture():
    trades = (
        trade("buy-1", "order-buy-1", DATES[0], OrderSide.BUY, 10, "9.9", "10", "2"),
        trade("buy-2", "order-buy-2", DATES[1], OrderSide.BUY, 10, "11.1", "11", "2"),
        trade("sell-1", "order-sell-1", DATES[2], OrderSide.SELL, 15, "13.1", "13", "3"),
        trade("sell-2", "order-sell-2", DATES[3], OrderSide.SELL, 5, "10.1", "10", "1"),
    )
    orders = (
        order("order-buy-1", DATES[0], OrderSide.BUY, 10),
        order("order-buy-2", DATES[1], OrderSide.BUY, 10),
        order("order-sell-1", DATES[2], OrderSide.SELL, 15),
        order("order-sell-2", DATES[3], OrderSide.SELL, 5),
        order(
            "order-rejected",
            DATES[1],
            OrderSide.BUY,
            10,
            BrokerOrderStatus.REJECTED,
        ),
    )
    events = (
        BacktestEventRecord(
            event_id="event-partial",
            run_id="run-performance",
            user_id="owner",
            trade_date=DATES[2],
            sequence=1,
            step=6,
            event_type="ORDER_EXECUTION_RESULT",
            data={"order_id": "order-sell-1", "status": "partially_filled"},
        ),
    )
    positions = (
        position(DATES[0], "600000", "40", "110", Decimal("4") / 11),
        position(DATES[0], "000001", "20", "110", Decimal("2") / 11),
        position(DATES[1], "600000", "40", "88", Decimal("5") / 11),
        position(DATES[2], "600000", "50", "110", Decimal("5") / 11),
    )
    return trades, orders, events, positions


def test_all_metric_groups_match_hand_calculated_fixture():
    trades, orders, events, positions = ledger_fixture()
    report = BacktestPerformanceCalculator().calculate(
        initial_equity=Decimal("100"),
        equity=equity_rows(),
        trades=trades,
        orders=orders,
        positions=positions,
        events=events,
        config=BacktestPerformanceConfig(
            annualization_periods=4,
            minimum_return_observations=4,
            minimum_trade_count=4,
        ),
        industry_by_symbol={"600000": "bank", "000001": "bank"},
        exit_reason_by_order_id={
            "order-sell-1": "signal_exit",
            "order-sell-2": "time_exit",
        },
    )

    assert report.initial_equity == 100
    assert report.final_equity == 121
    assert report.total_return == Decimal("0.21")
    assert report.cagr == Decimal("0.21")
    assert report.mean_daily_return == Decimal("0.0625")
    close(report.annualized_volatility, Decimal("0.3774917217635374959401424606621158504644"))
    close(report.sharpe_ratio, Decimal("0.6622661785325219092600476434072207902885"))
    assert report.annualized_downside_deviation == Decimal("0.2")
    assert report.sortino_ratio == Decimal("1.25")
    assert report.max_drawdown == Decimal("-0.2")
    assert report.max_drawdown_start_date == DATES[0]
    assert report.max_drawdown_end_date == DATES[1]
    assert report.max_drawdown_recovery_date == DATES[2]
    assert report.calmar_ratio == Decimal("1.05")

    assert report.benchmark_total_return == Decimal("0.1")
    assert report.relative_total_return == Decimal("0.11")
    close(report.beta, Decimal("-4.754010695187165775401069518716577540066"))
    close(report.annualized_alpha, Decimal("0.7140819964349376114081996434937611408176"))
    close(report.tracking_error, Decimal("0.4194262358829485233924458572217741125416"))
    close(report.information_ratio, Decimal("0.3633081084214248617165810982895491152711"))

    assert report.closed_lot_count == 3
    assert [item.pnl for item in report.closed_lots] == [
        Decimal("26"),
        Decimal("8"),
        Decimal("-7"),
    ]
    assert [item.holding_sessions for item in report.closed_lots] == [2, 1, 2]
    close(report.win_rate, Decimal(2) / 3)
    close(report.loss_rate, Decimal(1) / 3)
    close(report.profit_loss_ratio, Decimal(17) / 7)
    close(report.profit_factor, Decimal(34) / 7)
    assert report.net_closed_pnl == 27
    assert report.average_closed_lot_pnl == 9
    assert report.median_closed_lot_pnl == 8
    close(
        report.average_closed_lot_return,
        (Decimal(13) / 51 + Decimal(1) / 7 - Decimal(1) / 8) / 3,
    )
    close(report.median_closed_lot_return, Decimal(1) / 7)
    assert report.maximum_winning_pnl == 26
    assert report.maximum_losing_pnl == -7
    close(report.average_holding_sessions, Decimal(5) / 3)
    assert report.median_holding_sessions == 2

    assert report.total_turnover == Decimal("0.6")
    assert report.average_daily_turnover == Decimal("0.15")
    assert report.total_fees == 8
    assert report.total_slippage_cost == 2
    close(report.fee_to_gross_profit_ratio, Decimal(8) / 29)
    close(report.average_gross_exposure, Decimal(4) / 11)
    close(report.maximum_gross_exposure, Decimal(6) / 11)
    close(report.average_net_exposure, Decimal(4) / 11)
    close(report.maximum_net_exposure, Decimal(6) / 11)
    close(report.average_cash_ratio, Decimal(7) / 11)
    close(report.minimum_cash_ratio, Decimal(5) / 11)
    assert report.maximum_cash_ratio == 1
    assert report.final_cash_ratio == 1
    close(report.maximum_stock_concentration, Decimal(5) / 11)
    close(report.maximum_industry_concentration, Decimal(6) / 11)
    assert report.trade_count == 4
    assert report.rejected_order_count == 1
    assert report.partially_filled_order_count == 1
    assert report.exit_reason_distribution == {"signal_exit": 1, "time_exit": 1}
    assert [(item.period, item.return_rate) for item in report.monthly_returns] == [
        ("2023-12", Decimal("0.1")),
        ("2024-01", Decimal("0.1")),
    ]
    assert [(item.period, item.return_rate) for item in report.yearly_returns] == [
        ("2023", Decimal("0.1")),
        ("2024", Decimal("0.1")),
    ]
    assert report.warnings == ()
    required_formula_keys = {
        "total_return",
        "cagr",
        "annualized_volatility",
        "sharpe_ratio",
        "annualized_downside_deviation",
        "sortino_ratio",
        "max_drawdown",
        "calmar_ratio",
        "benchmark_total_return",
        "relative_total_return",
        "beta",
        "annualized_alpha",
        "tracking_error",
        "information_ratio",
        "win_rate",
        "loss_rate",
        "profit_loss_ratio",
        "profit_factor",
        "average_closed_lot_return",
        "median_closed_lot_return",
        "maximum_winning_pnl",
        "maximum_losing_pnl",
        "average_holding_sessions",
        "median_holding_sessions",
        "total_turnover",
        "total_fees",
        "total_slippage_cost",
        "fee_to_gross_profit_ratio",
        "average_gross_exposure",
        "average_cash_ratio",
        "stock_concentration",
        "industry_concentration",
        "monthly_returns",
        "yearly_returns",
        "exit_reason_distribution",
    }
    assert required_formula_keys.issubset(report.formulas)


def test_zero_trades_short_sample_zero_volatility_and_no_drawdown_are_explicit():
    rows = tuple(
        item.model_copy(
            update={
                "cash": Decimal("100"),
                "market_value": Decimal("0"),
                "equity": Decimal("100"),
                "benchmark_equity": Decimal("100"),
                "turnover": Decimal("0"),
                "gross_exposure": Decimal("0"),
                "net_exposure": Decimal("0"),
            }
        )
        for item in equity_rows()
    )
    report = BacktestPerformanceCalculator().calculate(
        initial_equity=Decimal("100"), equity=rows
    )

    assert report.total_return == 0
    assert report.cagr == 0
    assert report.annualized_volatility == 0
    assert report.sharpe_ratio is None
    assert report.annualized_downside_deviation == 0
    assert report.sortino_ratio is None
    assert report.max_drawdown == 0
    assert report.max_drawdown_start_date is None
    assert report.max_drawdown_end_date is None
    assert report.max_drawdown_recovery_date is None
    assert report.calmar_ratio is None
    assert report.beta is None
    assert report.annualized_alpha is None
    assert report.tracking_error == 0
    assert report.information_ratio is None
    assert report.closed_lot_count == 0
    assert report.win_rate is None
    assert report.profit_factor is None
    assert report.trade_count == 0
    assert report.maximum_stock_concentration == 0
    assert report.maximum_industry_concentration == 0
    assert "RETURN_SAMPLE_INSUFFICIENT:4<30" in report.warnings
    assert "TRADE_SAMPLE_INSUFFICIENT:0<10" in report.warnings
    assert "ZERO_RETURN_VOLATILITY" in report.warnings
    assert "NO_DOWNSIDE_DEVIATION" in report.warnings
    assert "NO_DRAWDOWN" in report.warnings
    assert "BENCHMARK_ZERO_VARIANCE" in report.warnings


def test_negative_or_unreconciled_equity_is_rejected_even_for_unvalidated_copies():
    negative = equity_rows()[0].model_copy(
        update={
            "cash": Decimal("-1"),
            "market_value": Decimal("0"),
            "equity": Decimal("-1"),
        }
    )
    with pytest.raises(PerformanceCalculationError, match="remain positive"):
        BacktestPerformanceCalculator().calculate(
            initial_equity=Decimal("100"), equity=(negative,)
        )

    mismatched = equity_rows()[0].model_copy(update={"cash": Decimal("49")})
    with pytest.raises(PerformanceCalculationError, match="does not reconcile"):
        BacktestPerformanceCalculator().calculate(
            initial_equity=Decimal("100"), equity=(mismatched,)
        )


def test_fifo_rejects_sell_quantity_without_prior_inventory():
    unmatched = trade(
        "unmatched-sell",
        "unmatched-order",
        DATES[0],
        OrderSide.SELL,
        10,
        "10",
        "10",
        "1",
    )
    with pytest.raises(PerformanceCalculationError, match="exceeds FIFO buy inventory"):
        BacktestPerformanceCalculator().calculate(
            initial_equity=Decimal("100"),
            equity=equity_rows(),
            trades=(unmatched,),
        )


def test_incomplete_benchmark_and_industry_classification_do_not_invent_metrics():
    rows = equity_rows(benchmarks=("100", None, "105", "110"))
    positions = (position(DATES[0], "600000", "60", "110", Decimal(6) / 11),)
    report = BacktestPerformanceCalculator().calculate(
        initial_equity=Decimal("100"),
        equity=rows,
        positions=positions,
    )

    assert report.benchmark_observations == 3
    assert report.benchmark_total_return is None
    assert report.beta is None
    assert report.maximum_industry_concentration is None
    assert "BENCHMARK_INCOMPLETE" in report.warnings
    assert "INDUSTRY_CLASSIFICATION_INCOMPLETE" in report.warnings
