from typing import Dict, Any
import pandas as pd

from app.models.domain_task import TaskType
from app.models.backtest import BacktestConfig
from app.services.domain_tasks.handler_registry import TaskContext, global_handler_registry
from app.services.backtest.engine import BacktestExecutionEngine
from app.repositories.strategy_repository import StrategyRepository


class BacktestTaskHandler:
    """异步 Backtest 任务 Worker Handler"""

    def __init__(self, repo: Optional[StrategyRepository] = None, engine: Optional[BacktestExecutionEngine] = None):
        self.repo = repo or StrategyRepository()
        self.engine = engine or BacktestExecutionEngine()

    async def handle_task(self, context: TaskContext) -> Dict[str, Any]:
        """执行异步回测流程"""
        params = context.task.payload or {}
        config_data = params.get("config", {})
        config = BacktestConfig(**config_data)

        strategy = await self.repo.get_strategy(config.strategy_id)
        if not strategy:
            raise ValueError(f"Strategy {config.strategy_id} not found")

        versions = await self.repo.list_versions(config.strategy_id)
        target_version = next((v for v in versions if v.version_num == config.version_num), None)
        if not target_version:
            raise ValueError(f"Strategy version {config.version_num} not found")

        # 从 payload 获取价格与因子数据 DataFrame
        prices_data = params.get("prices_data", [])
        factors_data = params.get("factors_data", [])
        bm_prices = params.get("benchmark_prices", {})

        prices_df = pd.DataFrame(prices_data)
        if not prices_df.empty and "date" in prices_df.columns and "symbol" in prices_df.columns:
            prices_df.set_index(["date", "symbol"], inplace=True)

        factors_df = pd.DataFrame(factors_data)
        if not factors_df.empty and "date" in factors_df.columns and "symbol" in factors_df.columns:
            factors_df.set_index(["date", "symbol"], inplace=True)

        result = self.engine.run_backtest(
            backtest_id=context.task.task_id,
            user_id=context.task.user_id,
            config=config,
            strategy_version=target_version,
            daily_prices_df=prices_df,
            daily_factors_df=factors_df,
            benchmark_prices=bm_prices
        )

        return result.model_dump()


# 注册 Handler
from typing import Optional
global_handler_registry.register(TaskType.BACKTEST_SIMULATION, BacktestTaskHandler().handle_task)
