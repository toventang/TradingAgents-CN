import pytest
import pandas as pd
from app.models.backtest import BacktestConfig, CostSlippageModel, BacktestStatus
from app.models.strategy import StrategyVersion, UniverseSnapshot
from app.services.backtest.engine import BacktestExecutionEngine


def test_backtest_engine_execution_flow():
    engine = BacktestExecutionEngine()

    config = BacktestConfig(
        strategy_id="strat_test",
        version_num=1,
        start_date="2026-01-01",
        end_date="2026-01-03",
        initial_capital=100000.0,
        cost_model=CostSlippageModel(commission_rate=0.0003, min_commission=5.0, slippage_rate=0.001)
    )

    univ = UniverseSnapshot(universe_id="u1", user_id="user_1", symbols=["000001.SZ", "600000.SH"])
    strategy_version = StrategyVersion(
        version_id="v1",
        strategy_id="strat_test",
        version_num=1,
        is_published=True,
        parameters={"weights": {"ret_1d": 1.0}},
        rules={"conditions": {"op": ">", "factor_id": "ret_1d", "value": 0.0}, "top_k": 1},
        universe=univ
    )

    # MultiIndex DataFrame for prices
    prices_data = [
        {"date": "2026-01-01", "symbol": "000001.SZ", "close": 10.0},
        {"date": "2026-01-01", "symbol": "600000.SH", "close": 20.0},
        {"date": "2026-01-02", "symbol": "000001.SZ", "close": 10.5},
        {"date": "2026-01-02", "symbol": "600000.SH", "close": 21.0},
        {"date": "2026-01-03", "symbol": "000001.SZ", "close": 11.0},
        {"date": "2026-01-03", "symbol": "600000.SH", "close": 20.5}
    ]
    prices_df = pd.DataFrame(prices_data).set_index(["date", "symbol"])

    # MultiIndex DataFrame for factors (600000.SH higher return on day 1, 000001.SZ higher return on day 2)
    factors_data = [
        {"date": "2026-01-01", "symbol": "000001.SZ", "ret_1d": 0.01},
        {"date": "2026-01-01", "symbol": "600000.SH", "ret_1d": 0.05},
        {"date": "2026-01-02", "symbol": "000001.SZ", "ret_1d": 0.08},
        {"date": "2026-01-02", "symbol": "600000.SH", "ret_1d": 0.02},
        {"date": "2026-01-03", "symbol": "000001.SZ", "ret_1d": 0.03},
        {"date": "2026-01-03", "symbol": "600000.SH", "ret_1d": 0.01}
    ]
    factors_df = pd.DataFrame(factors_data).set_index(["date", "symbol"])

    benchmark_prices = {"2026-01-01": 1000.0, "2026-01-02": 1010.0, "2026-01-03": 1020.0}

    result = engine.run_backtest(
        backtest_id="bt_run_01",
        user_id="user_1",
        config=config,
        strategy_version=strategy_version,
        daily_prices_df=prices_df,
        daily_factors_df=factors_df,
        benchmark_prices=benchmark_prices
    )

    assert result.status == BacktestStatus.COMPLETED
    assert len(result.equity_curve) == 3
    assert len(result.fills) > 0
    assert result.metrics is not None
    assert result.metrics.total_return != 0.0
