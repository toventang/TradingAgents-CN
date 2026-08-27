import enum
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from app.utils.timezone import now_tz


class AnalysisDepth(str, enum.Enum):
    QUICK = "quick"
    STANDARD = "standard"
    DEEP = "deep"


class RiskPreference(str, enum.Enum):
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"


class InvestmentHorizon(str, enum.Enum):
    SHORT_TERM = "short_term"
    MEDIUM_TERM = "medium_term"
    LONG_TERM = "long_term"


class AnalysisProfileVersion(BaseModel):
    """不可变的分析 Profile 版本模型"""
    version_id: str
    profile_id: str
    version_num: int = 1
    analysts: List[str] = Field(default_factory=lambda: ["market_analyst", "fundamentals_analyst", "technical_analyst", "risk_analyst"])
    depth: AnalysisDepth = AnalysisDepth.STANDARD
    model_refs: Dict[str, str] = Field(default_factory=dict)  # provider/model name, NO secrets
    risk_preference: RiskPreference = RiskPreference.BALANCED
    horizon: InvestmentHorizon = InvestmentHorizon.MEDIUM_TERM
    future_skill_refs: List[str] = Field(default_factory=list)
    factor_context_limits: int = 20
    strategy_context: Optional[Dict[str, Any]] = None
    debate_limits: Dict[str, int] = Field(default_factory=lambda: {"max_rounds": 3, "max_tokens": 4096})
    output_schema_version: str = "v1"
    is_published: bool = True
    created_at: datetime = Field(default_factory=now_tz)


class AnalysisProfile(BaseModel):
    """分析 Profile 主体模型"""
    profile_id: str
    user_id: str
    name: str
    description: str = ""
    is_system_template: bool = False
    latest_version_num: int = 1
    created_at: datetime = Field(default_factory=now_tz)
    updated_at: datetime = Field(default_factory=now_tz)
