import enum
from datetime import datetime, date
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from app.utils.timezone import now_tz


class DataQualityStatus(str, enum.Enum):
    VALID = "valid"
    PARTIAL = "partial"
    STALE = "stale"
    SUSPENDED = "suspended"
    INVALID = "invalid"
    UNAVAILABLE = "unavailable"


class DataQualityInfo(BaseModel):
    """数据质量信息"""
    status: DataQualityStatus = DataQualityStatus.VALID
    reason_code: str = "OK"
    message: Optional[str] = None
    missing_fields: List[str] = Field(default_factory=list)
    as_of: datetime = Field(default_factory=now_tz)
    source_version: str = "1.0.0"


class DailyBar(BaseModel):
    """标准化日 K 线数据"""
    symbol: str
    market: str  # CN / HK / US
    trade_date: str  # YYYY-MM-DD
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float
    pct_chg: float
    pre_close: Optional[float] = None
    turnover_rate: Optional[float] = None
    vwap: Optional[float] = None
    source: str = "default"
    source_version: str = "1.0.0"


class PointInTimeFact(BaseModel):
    """Point-in-Time 财务观测数据"""
    fact_id: str
    symbol: str
    market: str
    report_period: str  # YYYYQ1 / YYYYQ2 / YYYYQ3 / YYYYQ4
    publish_at: datetime  # 关键：真实发布可见时间戳
    ingested_at: datetime = Field(default_factory=now_tz)
    fact_type: str  # financial / balance_sheet / income / cash_flow
    data: Dict[str, Any] = Field(default_factory=dict)
    source: str = "default"
    source_version: str = "1.0.0"

    def is_visible_at(self, as_of: datetime) -> bool:
        """检查发布时间戳是否在 cutoff 时间之前（防 Look-ahead Bias）"""
        return self.publish_at <= as_of


class NewsSocialInput(BaseModel):
    """新闻/社交媒体结构化输入"""
    news_id: str
    symbol: str
    market: str
    published_at: datetime  # 发布时间
    ingested_at: datetime = Field(default_factory=now_tz)  # 入库时间
    title: str
    content_summary: Optional[str] = None
    sentiment_score: Optional[float] = None
    source: str = "default"
    source_version: str = "1.0.0"

    def is_visible_at(self, as_of: datetime) -> bool:
        return self.published_at <= as_of


class BenchmarkSeries(BaseModel):
    """基准指数时间序列"""
    benchmark_id: str  # e.g., 000300.SH / HSI / SPX
    market: str
    trade_date: str
    close: float
    pct_chg: float


class MarketDataBatch(BaseModel):
    """市场数据批次响应包"""
    items: List[Any] = Field(default_factory=list)
    as_of: datetime = Field(default_factory=now_tz)
    source_version: str = "1.0.0"
    quality: DataQualityInfo = Field(default_factory=DataQualityInfo)
