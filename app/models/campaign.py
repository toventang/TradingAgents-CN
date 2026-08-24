import enum
from datetime import datetime, date
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from app.utils.timezone import now_tz


class CampaignStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVATED = "activated"
    PAUSED = "paused"
    STOPPED = "stopped"


class CampaignRevision(BaseModel):
    """Campaign 非冻结配置修订版本"""
    revision_id: str
    campaign_id: str
    revision_num: int = 1
    rebalance_frequency: str = "daily"
    risk_config_override: Dict[str, Any] = Field(default_factory=dict)
    commit_message: str = ""
    created_at: datetime = Field(default_factory=now_tz)


class Campaign(BaseModel):
    """实盘/模拟 Campaign 主体模型"""
    campaign_id: str
    user_id: str
    name: str
    description: str = ""
    status: CampaignStatus = CampaignStatus.DRAFT

    # 激活后冻结不可变的核心字段
    strategy_id: str
    strategy_version_num: int
    portfolio_id: str
    initial_allocation_cash: float
    start_date: str                           # YYYY-MM-DD

    # 可修订状态字段
    current_revision_num: int = 1
    rebalance_frequency: str = "daily"
    risk_config_override: Dict[str, Any] = Field(default_factory=dict)

    activated_at: Optional[datetime] = None
    paused_at: Optional[datetime] = None
    stopped_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=now_tz)
    updated_at: datetime = Field(default_factory=now_tz)


class CampaignValidationResult(BaseModel):
    """Campaign 激活校验结果"""
    is_valid: bool
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class CandidateRecord(BaseModel):
    """选股候选/排除明细记录"""
    candidate_id: str
    cycle_id: str
    campaign_id: str
    symbol: str
    score: float
    rank: int
    selected: bool
    rejection_reason: Optional[str] = None
    target_weight: float = 0.0


class CampaignCycleStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class CampaignCycleRecord(BaseModel):
    """Campaign 周期调仓运行记录"""
    cycle_id: str
    campaign_id: str
    cycle_date: str                           # YYYY-MM-DD
    status: CampaignCycleStatus = CampaignCycleStatus.PENDING
    idempotency_key: str                      # campaign_id + cycle_date
    candidates_count: int = 0
    orders_count: int = 0
    error_message: Optional[str] = None
    executed_at: datetime = Field(default_factory=now_tz)
