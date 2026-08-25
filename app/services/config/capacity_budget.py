from typing import Dict, Any, List, Optional


class CapacityBudgetExceededError(Exception):
    """容量与性能预算超限异常"""
    def __init__(self, resource: str, current_val: Any, limit_val: Any, message: str):
        super().__init__(message)
        self.resource = resource
        self.current_val = current_val
        self.limit_val = limit_val
        self.message = message


class CapacityBudgetConfig:
    """系统容量与性能预算配置常量"""
    MAX_FACTOR_CHUNK_SYMBOLS: int = 100        # 单并行块最大 100 标的
    MAX_BACKTEST_TRADING_DAYS: int = 500       # 单回测最大 500 交易日
    MAX_ACTIVE_QUEUED_TASKS: int = 20          # 队列最大 20 个活动任务
    MAX_SKILL_DAG_STEPS: int = 10              # Skill DAG 最大 10 步
    MAX_SKILL_DAG_TIMEOUT_SEC: float = 30.0    # Skill DAG 最大 30s 超时
    MAX_USER_ACTIVE_CAMPAIGNS: int = 10        # 单用户最大 10 个激活 Campaign


class CapacityBudgetService:
    """容量与性能预算校验服务"""

    @classmethod
    def validate_factor_symbols(cls, symbol_count: int):
        if symbol_count > CapacityBudgetConfig.MAX_FACTOR_CHUNK_SYMBOLS:
            raise CapacityBudgetExceededError(
                resource="factor_symbols",
                current_val=symbol_count,
                limit_val=CapacityBudgetConfig.MAX_FACTOR_CHUNK_SYMBOLS,
                message=f"Factor chunk symbol count {symbol_count} exceeds capacity limit {CapacityBudgetConfig.MAX_FACTOR_CHUNK_SYMBOLS}"
            )

    @classmethod
    def validate_backtest_days(cls, trading_days: int):
        if trading_days > CapacityBudgetConfig.MAX_BACKTEST_TRADING_DAYS:
            raise CapacityBudgetExceededError(
                resource="backtest_days",
                current_val=trading_days,
                limit_val=CapacityBudgetConfig.MAX_BACKTEST_TRADING_DAYS,
                message=f"Backtest trading days {trading_days} exceeds capacity limit {CapacityBudgetConfig.MAX_BACKTEST_TRADING_DAYS}"
            )

    @classmethod
    def validate_active_campaign_count(cls, active_count: int):
        if active_count >= CapacityBudgetConfig.MAX_USER_ACTIVE_CAMPAIGNS:
            raise CapacityBudgetExceededError(
                resource="active_campaigns",
                current_val=active_count,
                limit_val=CapacityBudgetConfig.MAX_USER_ACTIVE_CAMPAIGNS,
                message=f"User active campaign count {active_count} reached capacity limit {CapacityBudgetConfig.MAX_USER_ACTIVE_CAMPAIGNS}"
            )
