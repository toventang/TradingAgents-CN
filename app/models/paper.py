import enum
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from app.utils.timezone import now_tz


class LedgerEntryType(str, enum.Enum):
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    TRADE_BUY = "trade_buy"
    TRADE_SELL = "trade_sell"
    COMMISSION = "commission"
    STAMP_DUTY = "stamp_duty"
    TRANSFER_FEE = "transfer_fee"


class PaperPortfolio(BaseModel):
    """隔离盘前/模拟组合模型"""
    portfolio_id: str
    user_id: str
    name: str
    currency: str = "CNY"
    initial_capital: float = 1000000.0
    cash: float = 1000000.0
    frozen_cash: float = 0.0
    market_value: float = 0.0
    total_equity: float = 1000000.0
    created_at: datetime = Field(default_factory=now_tz)
    updated_at: datetime = Field(default_factory=now_tz)


class PositionLot(BaseModel):
    """个股持仓 Lot (Tax-lot) 跟踪"""
    lot_id: str
    portfolio_id: str
    symbol: str
    quantity: int
    t_plus_1_sellable_qty: int
    buy_price: float
    current_price: float
    bought_at: datetime = Field(default_factory=now_tz)


class OrderEvent(BaseModel):
    """模拟订单状态事件"""
    event_id: str
    order_id: str
    portfolio_id: str
    symbol: str
    side: str                                 # buy / sell
    status: str                               # submitted / filled / rejected / cancelled
    quantity: int
    price: float
    total_cost: float = 0.0
    reason_code: str = "OK"
    created_at: datetime = Field(default_factory=now_tz)


class LedgerEntry(BaseModel):
    """复式记账明细分录"""
    entry_id: str
    portfolio_id: str
    entry_type: LedgerEntryType
    amount: float                            # 正数为入账，负数为出账
    balance_after: float
    reference_id: Optional[str] = None        # order_id / fill_id
    description: str = ""
    created_at: datetime = Field(default_factory=now_tz)


class PortfolioReconciliation(BaseModel):
    """资金与持仓对账结果"""
    portfolio_id: str
    is_balanced: bool
    calculated_equity: float
    recorded_equity: float
    equity_discrepancy: float
    calculated_cash_balance: float
    recorded_cash_balance: float
    cash_discrepancy: float
    reconciled_at: datetime = Field(default_factory=now_tz)
