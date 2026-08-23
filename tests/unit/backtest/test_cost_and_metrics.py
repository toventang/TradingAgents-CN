import pytest
from app.models.backtest import CostSlippageModel, EquityPoint
from app.services.backtest.cost_model import CostModelService
from app.services.backtest.metrics import MetricsCalculator


def test_cost_model_custom_broker_and_account():
    # Broker A: High commission (0.05%), Min 10 RMB, Stamp Duty 0.05%
    broker_a_model = CostSlippageModel(
        broker_id="broker_a",
        account_id="acc_001",
        commission_rate=0.0005,
        min_commission=10.0,
        stamp_duty_rate=0.0005,
        slippage_rate=0.0010
    )

    # Buy transaction: 1000 shares @ 10.0 RMB
    fill_buy = CostModelService.calculate_fill(
        backtest_id="bt_1",
        trade_date="2026-01-02",
        symbol="000001.SZ",
        side="buy",
        quantity=1000,
        price=10.0,
        cost_model=broker_a_model
    )

    # Execution price with 0.1% slippage = 10.01
    assert fill_buy.execution_price == 10.01
    assert fill_buy.turnover == 10010.0
    # Commission = 10010 * 0.0005 = 5.005 -> Min commission = 10.0
    assert fill_buy.commission == 10.0
    assert fill_buy.stamp_duty == 0.0

    # Sell transaction: 1000 shares @ 12.0 RMB
    fill_sell = CostModelService.calculate_fill(
        backtest_id="bt_1",
        trade_date="2026-01-05",
        symbol="000001.SZ",
        side="sell",
        quantity=1000,
        price=12.0,
        cost_model=broker_a_model
    )

    # Execution price with 0.1% downward slippage = 11.988
    assert fill_sell.execution_price == 11.988
    assert fill_sell.stamp_duty > 0.0


def test_performance_metrics_calculation():
    equity_curve = [
        EquityPoint(trade_date="2026-01-01", cash=100000.0, market_value=0.0, total_equity=100000.0, benchmark_equity=1000.0, daily_return=0.0, benchmark_return=0.0),
        EquityPoint(trade_date="2026-01-02", cash=100000.0, market_value=10000.0, total_equity=110000.0, benchmark_equity=1010.0, daily_return=0.10, benchmark_return=0.01),
        EquityPoint(trade_date="2026-01-03", cash=100000.0, market_value=5000.0, total_equity=105000.0, benchmark_equity=1020.0, daily_return=-0.0455, benchmark_return=0.0099),
        EquityPoint(trade_date="2026-01-04", cash=100000.0, market_value=20000.0, total_equity=120000.0, benchmark_equity=1030.0, daily_return=0.1429, benchmark_return=0.0098)
    ]

    metrics = MetricsCalculator.calculate_metrics(
        equity_curve=equity_curve,
        fills=[],
        initial_capital=100000.0
    )

    assert metrics.total_return == 0.20
    assert metrics.benchmark_return == 0.03
    assert metrics.excess_return == 0.17
    assert metrics.max_drawdown > 0.0
