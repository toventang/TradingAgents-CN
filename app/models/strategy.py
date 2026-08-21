import enum
import hashlib
import json
from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from app.utils.timezone import now_tz


class StrategyStatus(str, enum.Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class StrategyType(str, enum.Enum):
    FACTOR_MODEL = "factor_model"
    TECHNICAL_RULES = "technical_rules"
    SYSTEM_TEMPLATE = "system_template"


def compute_checksum(data: Any) -> str:
    raw_bytes = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw_bytes).hexdigest()


class UniverseSnapshot(BaseModel):
    """选股宇宙不可变快照"""
    universe_id: str
    user_id: str
    name: str = "default_universe"
    market: str = "CN"
    symbols: List[str] = Field(default_factory=list)
    checksum: str = ""
    as_of: datetime = Field(default_factory=now_tz)
    created_at: datetime = Field(default_factory=now_tz)

    def __init__(self, **data):
        super().__init__(**data)
        if not self.checksum:
            self.checksum = compute_checksum({"market": self.market, "symbols": sorted(self.symbols)})


class StrategyVersion(BaseModel):
    """不可变的策略版本模型"""
    version_id: str
    strategy_id: str
    version_num: int = 1
    is_published: bool = False
    parameters: Dict[str, Any] = Field(default_factory=dict)
    rules: Dict[str, Any] = Field(default_factory=dict)
    universe: UniverseSnapshot = Field(default_factory=lambda: UniverseSnapshot(universe_id="univ_default", user_id="system"))
    parent_strategy_id: Optional[str] = None
    parent_version_num: Optional[int] = None
    commit_message: str = ""
    checksum: str = ""
    published_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=now_tz)

    def __init__(self, **data):
        super().__init__(**data)
        if not self.checksum:
            payload = {
                "strategy_id": self.strategy_id,
                "version_num": self.version_num,
                "parameters": self.parameters,
                "rules": self.rules,
                "universe_checksum": self.universe.checksum if self.universe else ""
            }
            self.checksum = compute_checksum(payload)


class Strategy(BaseModel):
    """策略主体模型"""
    strategy_id: str
    user_id: str
    name: str
    description: str = ""
    strategy_type: StrategyType = StrategyType.FACTOR_MODEL
    is_system_template: bool = False
    status: StrategyStatus = StrategyStatus.DRAFT
    latest_version_num: int = 1
    published_version_num: Optional[int] = None
    created_at: datetime = Field(default_factory=now_tz)
    updated_at: datetime = Field(default_factory=now_tz)


class StrategySignal(BaseModel):
    """策略交易信号"""
    signal_id: str
    strategy_id: str
    version_num: int
    user_id: str
    symbol: str
    market: str = "CN"
    score: float = 0.0
    rank: int = 1
    target_weight: float = 0.0
    signal_type: str = "hold"  # buy / sell / hold
    reason_code: str = "OK"
    created_at: datetime = Field(default_factory=now_tz)
