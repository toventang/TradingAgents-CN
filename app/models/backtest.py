import enum
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from app.utils.timezone import now_tz


class BacktestStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class CostSlippageModel(BaseModel):
    """可配置的券商/账户交易成本与滑点模型"""
    broker_id: str = "default_broker"
    account_id: str = "default_account"
    commission_rate: float = 0.0003          # 佣金比例 (默认 0.03%)
    min_commission: float = 5.0              # 最低佣金 (默认 5 元)
    stamp_duty_rate: float = 0.0005          # 印花税 (卖出时收取，默认 0.05%)
    transfer_fee_rate: float = 0.00001       # 过户费 (默认 0.001%)
    slippage_rate: float = 0.0010            # 滑点比例 (默认 0.1%)


class BacktestConfig(BaseModel):
    """回测配置参数"""
    strategy_id: str
    version_num: int = 1
    start_date: str                           # YYYY-MM-DD
    end_date: str                             # YYYY-MM-DD
    initial_capital: float = 1000000.0        # 初始资金
    benchmark: str = "000300.SH"
    rebalance_frequency: str = "daily"        # daily / weekly / monthly
    cost_model: CostSlippageModel = Field(default_factory=CostSlippageModel)


class TradeFill(BaseModel):
    """成交撮合记录"""
    fill_id: str
    backtest_id: str
    trade_date: str
    symbol: str
    side: str                                 # buy / sell
    quantity: int
    price: float                             # 撮合基准价
    execution_price: float                   # 含滑点的实际成交价
    turnover: float                          # 成交额
    commission: float                        # 佣金
    stamp_duty: float                        # 印花税
    transfer_fee: float                      # 过户费
    total_cost: float                        # 总交易成本
    created_at: datetime = Field(default_factory=now_tz)


class EquityPoint(BaseModel):
    """每日权益点记录"""
    trade_date: str
    cash: float
    market_value: float
    total_equity: float
    benchmark_equity: float
    daily_return: float
    benchmark_return: float


class PerformanceMetrics(BaseModel):
    """回测绩效评估指标"""
    total_return: float = 0.0
    annualized_return: float = 0.0
    benchmark_return: float = 0.0
    excess_return: float = 0.0               # Alpha
    max_drawdown: float = 0.0
    max_drawdown_duration_days: int = 0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    information_ratio: float = 0.0
    win_rate: float = 0.0
    profit_loss_ratio: float = 0.0
    total_trades: int = 0
    turnover_rate: float = 0.0


class BacktestRequest(BaseModel):
    """发起回测请求"""
    config: BacktestConfig
    user_id: str


class BacktestResult(BaseModel):
    """回测最终结果"""
    backtest_id: str
    user_id: str
    config: BacktestConfig
    status: BacktestStatus = BacktestStatus.PENDING
    error_message: Optional[str] = None
    equity_curve: List[EquityPoint] = Field(default_factory=list)
    fills: List[TradeFill] = Field(default_factory=list)
    metrics: Optional[PerformanceMetrics] = None
    created_at: datetime = Field(default_factory=now_tz)
    completed_at: Optional[datetime] = None
