import pytest
import pandas as pd
from app.services.factors.engine import FactorExecutionEngine
from app.services.factors.dag import FactorDAGPlanner

def test_factor_dag_planner():
    planner = FactorDAGPlanner()
    order = planner.plan_execution_order(["ret_1d", "sma_5"])
    assert "ret_1d" in order
    assert "sma_5" in order

@pytest.mark.asyncio
async def test_factor_execution_engine_chunking():
    engine = FactorExecutionEngine(chunk_size=10)

    async def mock_provider(sym, mkt):
        dates = pd.date_range("2025-01-01", periods=20, freq="B")
        close = pd.Series([10.0 + i * 0.1 for i in range(20)], index=dates)
        return pd.DataFrame({"close": close, "open": close, "high": close, "low": close})

    symbols = [f"00000{i}" for i in range(25)]
    results = await engine.compute_universe_batch(
        symbols=symbols,
        market="CN",
        factor_ids=["ret_1d", "sma_5"],
        data_provider=mock_provider
    )

    assert len(results) == 25
    assert "ret_1d" in results["000000"]
