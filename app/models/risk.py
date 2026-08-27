import enum
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from app.utils.timezone import now_tz


class RiskSeverity(str, enum.Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class RiskAction(str, enum.Enum):
    ALLOW = "allow"
    BLOCK_BUY = "block_buy"
    FORCE_REDUCE = "force_reduce"
    HALT_PORTFOLIO = "halt_portfolio"


class RiskDecision(str, enum.Enum):
    APPROVED = "approved"
    APPROVED_WITH_WARNINGS = "approved_with_warnings"
    REJECTED = "rejected"


class RiskConfig(BaseModel):
    """可配置的风控规则指标与阀值列表"""
    portfolio_id: str = "default_portfolio"
    max_stock_weight: float = 0.10             # 单股最大仓位上限 (默认 10%)
    max_sector_weight: float = 0.30            # 单行业最大仓位上限 (默认 30%)
    max_drawdown_limit: float = 0.15           # 组合最大回撤告警/熔断阀值 (默认 15%)
    max_var_95_limit: float = 0.03             # 95% 置信度每日 VaR 风险上限 (默认 3%)
    max_adv_participation_rate: float = 0.05   # 5日日均成交量 ADV 参与度上限 (默认 5%)
    enforce_t_plus_1: bool = True              # 是否强制执行 A 股 T+1 可卖数量约束
    block_limit_up_buy: bool = True            # 涨停板禁止买入
    block_limit_down_sell: bool = True          # 跌停板禁止卖出


class RiskViolation(BaseModel):
    """结构化风控违规记录"""
    rule_id: str
    rule_name: str
    severity: RiskSeverity
    symbol: Optional[str] = None
    current_value: float
    limit_threshold: float
    action_required: RiskAction
    message: str


class RiskEvaluationResult(BaseModel):
    """风控评估汇总决策"""
    evaluation_id: str
    portfolio_id: str
    decision: RiskDecision
    violations: List[RiskViolation] = Field(default_factory=list)
    evaluated_at: datetime = Field(default_factory=now_tz)
