import enum
from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from app.utils.timezone import now_tz


class FactorCategory(str, enum.Enum):
    PRICE = "price"
    TREND = "trend"
    MOMENTUM = "momentum"
    VOLATILITY = "volatility"
    LIQUIDITY = "liquidity"
    VALUATION = "valuation"
    QUALITY = "quality"
    GROWTH = "growth"
    SENTIMENT = "sentiment"
    CROSS_SECTIONAL = "cross_sectional"


class MissingValuePolicy(str, enum.Enum):
    DROP = "drop"
    FORWARD_FILL = "forward_fill"
    ZERO_FILL = "zero_fill"
    MEAN_FILL = "mean_fill"
    MEDIAN_FILL = "median_fill"


class ParameterSchema(BaseModel):
    name: str
    type: str  # int, float, str, bool
    default: Any
    description: Optional[str] = None


class FactorDefinition(BaseModel):
    """因子定义元数据"""
    factor_id: str
    name: str
    category: FactorCategory
    description: str
    parameters: List[ParameterSchema] = Field(default_factory=list)
    required_history_days: int = 30
    supported_markets: List[str] = Field(default_factory=lambda: ["CN", "HK", "US"])
    direction: int = 1  # 1 多头正向，-1 反向
    missing_policy: MissingValuePolicy = MissingValuePolicy.FORWARD_FILL
    version: str = "1.0.0"
    checksum: Optional[str] = None
    created_at: datetime = Field(default_factory=now_tz)
    updated_at: datetime = Field(default_factory=now_tz)
