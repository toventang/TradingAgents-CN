import enum
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from app.utils.timezone import now_tz


class CauseCategory(str, enum.Enum):
    MARKET_TREND = "market_trend"
    INDUSTRY_ROTATION = "industry_rotation"
    EXECUTION_SLIPPAGE = "execution_slippage"
    FACTOR_TIMING = "factor_timing"
    RISK_EXIT_TRIGGERED = "risk_exit_triggered"
    OTHER = "other"


class ExcursionMetrics(BaseModel):
    """MAE / MFE 价格偏移指标"""
    mae_pct: float                             # Maximum Adverse Excursion (最大不利漂移 %)
    mfe_pct: float                             # Maximum Favorable Excursion (最大有利漂移 %)
    holding_days: int
    realized_pnl_pct: float
    benchmark_return_pct: float
    excess_return_pct: float
    slippage_cost_pct: float


class TradeReviewInput(BaseModel):
    """交易归因分析输入数据"""
    trade_id: str
    symbol: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    quantity: int
    side: str = "buy"                          # buy / sell
    daily_prices: List[float]                  # 动买到出场期间每日收盘价列表
    daily_benchmark_prices: List[float]        # 同期基准价格列表
    execution_slippage: float = 0.0            # 成交滑点成本


class TradeAttributionResult(BaseModel):
    """确定性交易归因分析结果"""
    review_id: str
    trade_id: str
    symbol: str
    metrics: ExcursionMetrics
    primary_cause: CauseCategory
    cause_breakdown: Dict[CauseCategory, float] # 各原因贡献度比例
    reviewed_at: datetime = Field(default_factory=now_tz)
