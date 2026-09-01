"""
分析相关数据模型
"""

from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Optional, List, Dict, Any
from uuid import uuid4

from pydantic import (
    BaseModel,
    Field,
    ConfigDict,
    StrictInt,
    field_serializer,
    field_validator,
    model_validator,
)
from enum import Enum
from bson import ObjectId
from .user import PyObjectId
from app.utils.timezone import now_tz


class AnalysisStatus(str, Enum):
    """分析状态枚举"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BatchStatus(str, Enum):
    """批次状态枚举"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AnalysisParameters(BaseModel):
    """分析参数模型

    研究深度说明：
    - 快速: 1级 - 快速分析 (2-4分钟)
    - 基础: 2级 - 基础分析 (4-6分钟)
    - 标准: 3级 - 标准分析 (6-10分钟，推荐)
    - 深度: 4级 - 深度分析 (10-15分钟)
    - 全面: 5级 - 全面分析 (15-25分钟)
    """
    profile_id: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
    market_type: str = "A股"
    analysis_date: Optional[datetime] = None
    research_depth: str = "标准"  # 默认使用3级标准分析（推荐）
    selected_analysts: List[str] = Field(default_factory=lambda: ["market", "fundamentals", "news", "social"])
    custom_prompt: Optional[str] = None
    include_sentiment: bool = True
    include_risk: bool = True
    language: str = "zh-CN"
    # 模型配置
    quick_analysis_model: Optional[str] = "qwen-turbo"
    deep_analysis_model: Optional[str] = "qwen-max"


class AnalysisResult(BaseModel):
    """分析结果模型"""
    analysis_id: Optional[str] = None
    summary: Optional[str] = None
    recommendation: Optional[str] = None
    confidence_score: Optional[float] = None
    risk_level: Optional[str] = None
    key_points: List[str] = Field(default_factory=list)
    detailed_analysis: Optional[Dict[str, Any]] = None
    charts: List[str] = Field(default_factory=list)
    tokens_used: int = 0
    execution_time: float = 0.0
    error_message: Optional[str] = None
    model_info: Optional[str] = None  # 🔥 添加模型信息字段


class AnalysisTask(BaseModel):
    """分析任务模型"""
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    task_id: str = Field(..., description="任务唯一标识")
    batch_id: Optional[str] = None
    user_id: PyObjectId
    symbol: str = Field(..., description="6位股票代码")
    stock_code: Optional[str] = Field(None, description="股票代码(已废弃,使用symbol)")
    stock_name: Optional[str] = None
    status: AnalysisStatus = AnalysisStatus.PENDING

    progress: int = Field(default=0, ge=0, le=100, description="任务进度 0-100")

    # 时间戳
    created_at: datetime = Field(default_factory=now_tz)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # 执行信息
    worker_id: Optional[str] = None
    parameters: AnalysisParameters = Field(default_factory=AnalysisParameters)
    result: Optional[AnalysisResult] = None
    
    # 重试机制
    retry_count: int = 0
    max_retries: int = 3
    last_error: Optional[str] = None
    
    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True
    )


class AnalysisBatch(BaseModel):
    """分析批次模型"""
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    batch_id: str = Field(..., description="批次唯一标识")
    user_id: PyObjectId
    title: str = Field(..., description="批次标题")
    description: Optional[str] = None
    status: BatchStatus = BatchStatus.PENDING
    
    # 任务统计
    total_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    cancelled_tasks: int = 0
    progress: int = Field(default=0, ge=0, le=100, description="整体进度 0-100")
    
    # 时间戳
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # 配置参数
    parameters: AnalysisParameters = Field(default_factory=AnalysisParameters)
    
    # 结果摘要
    results_summary: Optional[Dict[str, Any]] = None
    
    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True
    )


class StockInfo(BaseModel):
    """股票信息模型"""
    symbol: str = Field(..., description="6位股票代码")
    code: Optional[str] = Field(None, description="股票代码(已废弃,使用symbol)")
    name: str = Field(..., description="股票名称")
    market: str = Field(..., description="市场类型")
    industry: Optional[str] = None
    sector: Optional[str] = None
    market_cap: Optional[float] = None
    price: Optional[float] = None
    change_percent: Optional[float] = None


# API请求/响应模型

class SingleAnalysisRequest(BaseModel):
    """单股分析请求"""
    symbol: Optional[str] = Field(None, description="6位股票代码")
    stock_code: Optional[str] = Field(None, description="股票代码(已废弃,使用symbol)")
    parameters: Optional[AnalysisParameters] = None

    def get_symbol(self) -> str:
        """获取股票代码(兼容旧字段)"""
        return self.symbol or self.stock_code or ""


class BatchAnalysisRequest(BaseModel):
    """批量分析请求"""
    title: str = Field(..., description="批次标题")
    description: Optional[str] = None
    symbols: Optional[List[str]] = Field(None, min_items=1, max_items=10, description="股票代码列表（最多10个）")
    stock_codes: Optional[List[str]] = Field(None, min_items=1, max_items=10, description="股票代码列表(已废弃,使用symbols，最多10个)")
    parameters: Optional[AnalysisParameters] = None

    def get_symbols(self) -> List[str]:
        """获取股票代码列表(兼容旧字段)"""
        return self.symbols or self.stock_codes or []


class AnalysisTaskResponse(BaseModel):
    """分析任务响应"""
    task_id: str
    batch_id: Optional[str]
    symbol: str
    stock_code: Optional[str] = None  # 兼容字段
    stock_name: Optional[str]
    status: AnalysisStatus
    progress: int
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    result: Optional[AnalysisResult]

    @field_serializer('created_at', 'started_at', 'completed_at')
    def serialize_datetime(self, dt: Optional[datetime], _info) -> Optional[str]:
        """序列化 datetime 为 ISO 8601 格式，保留时区信息"""
        if dt:
            return dt.isoformat()
        return None


class AnalysisBatchResponse(BaseModel):
    """分析批次响应"""
    batch_id: str
    title: str
    description: Optional[str]
    status: BatchStatus
    total_tasks: int
    completed_tasks: int
    failed_tasks: int
    progress: int
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    parameters: AnalysisParameters

    @field_serializer('created_at', 'started_at', 'completed_at')
    def serialize_datetime(self, dt: Optional[datetime], _info) -> Optional[str]:
        """序列化 datetime 为 ISO 8601 格式，保留时区信息"""
        if dt:
            return dt.isoformat()
        return None


class AnalysisHistoryQuery(BaseModel):
    """分析历史查询参数"""
    status: Optional[AnalysisStatus] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    symbol: Optional[str] = None
    stock_code: Optional[str] = None  # 兼容字段
    batch_id: Optional[str] = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)

    def get_symbol(self) -> Optional[str]:
        """获取股票代码(兼容旧字段)"""
        return self.symbol or self.stock_code


# Versioned AnalysisProfile models.  They live in this existing domain module
# so legacy requests and the new compatibility layer share one validation
# boundary without changing routers before J24.

ANALYSIS_PROFILE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"
MAX_ANALYSIS_FACTORS = 50
MAX_DEBATE_ROUNDS = 5
MAX_RISK_DEBATE_ROUNDS = 5


def _analysis_id() -> str:
    return str(uuid4())


def _analysis_utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalized_analysis_time(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _analysis_checksum(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class AnalysisProfileVersionStatus(str, Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    DEPRECATED = "deprecated"


class AnalysisProfileSource(str, Enum):
    VERSIONED = "versioned"
    LEGACY_TEMPORARY = "legacy_temporary"


class AnalysisAnalyst(str, Enum):
    MARKET = "market"
    FUNDAMENTALS = "fundamentals"
    NEWS = "news"
    SOCIAL = "social"


class AnalysisResearchDepth(str, Enum):
    QUICK = "快速"
    BASIC = "基础"
    STANDARD = "标准"
    DEEP = "深度"
    COMPREHENSIVE = "全面"


class AnalysisRiskPreference(str, Enum):
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"


class AnalysisInvestmentHorizon(str, Enum):
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


class AnalysisModelReference(BaseModel):
    """Reference to separately managed model configuration, never credentials."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    config_id: str = Field(pattern=ANALYSIS_PROFILE_ID_PATTERN)
    model_name: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("config_id", "model_name")
    @classmethod
    def reject_secret_material(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value != value.strip():
            raise ValueError("model references must be trimmed")
        lowered = value.lower()
        if (
            any(marker in lowered for marker in ("api_key", "apikey", "secret", "bearer "))
            or re.search(r"(?:^|[^a-z0-9])sk-[a-z0-9]", lowered)
        ):
            raise ValueError("model references cannot contain credentials")
        return value


class AnalysisFactorContext(BaseModel):
    """Bounded structured-summary request; raw time-series has no field here."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    factor_ids: tuple[str, ...] = Field(default=(), max_length=MAX_ANALYSIS_FACTORS)
    summary_schema_version: str = Field(
        default="factor-summary-v1", pattern=ANALYSIS_PROFILE_ID_PATTERN
    )
    max_evidence_items_per_factor: StrictInt = Field(default=3, ge=0, le=10)

    @field_validator("factor_ids")
    @classmethod
    def validate_factor_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("factor_context factor_ids must be unique")
        if any(not re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", item) for item in value):
            raise ValueError("factor_context contains an invalid factor ID")
        return value


class AnalysisProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str = Field(default_factory=_analysis_id, pattern=ANALYSIS_PROFILE_ID_PATTERN)
    user_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    current_draft_version_id: str | None = Field(
        default=None, pattern=ANALYSIS_PROFILE_ID_PATTERN
    )
    latest_published_version_id: str | None = Field(
        default=None, pattern=ANALYSIS_PROFILE_ID_PATTERN
    )
    version_sequence: StrictInt = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=_analysis_utc_now)
    updated_at: datetime = Field(default_factory=_analysis_utc_now)
    archived_at: datetime | None = None

    @field_validator("user_id", "name")
    @classmethod
    def require_trimmed_profile_text(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("profile text fields must be trimmed")
        return value

    @field_validator("created_at", "updated_at", "archived_at")
    @classmethod
    def normalize_profile_times(cls, value: datetime | None) -> datetime | None:
        return _normalized_analysis_time(value)

    @model_validator(mode="after")
    def validate_profile_lifecycle(self) -> "AnalysisProfile":
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        if self.archived_at is not None and self.archived_at < self.created_at:
            raise ValueError("archived_at cannot precede created_at")
        return self


class AnalysisProfileVersion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    profile_version_id: str = Field(
        default_factory=_analysis_id, pattern=ANALYSIS_PROFILE_ID_PATTERN
    )
    profile_id: str = Field(pattern=ANALYSIS_PROFILE_ID_PATTERN)
    user_id: str = Field(min_length=1, max_length=128)
    version: StrictInt = Field(ge=1)
    status: AnalysisProfileVersionStatus = AnalysisProfileVersionStatus.DRAFT
    selected_analysts: tuple[AnalysisAnalyst, ...] = Field(min_length=1, max_length=4)
    research_depth: AnalysisResearchDepth
    quick_model_ref: AnalysisModelReference
    deep_model_ref: AnalysisModelReference
    risk_preference: AnalysisRiskPreference = AnalysisRiskPreference.BALANCED
    investment_horizon: AnalysisInvestmentHorizon = AnalysisInvestmentHorizon.MEDIUM
    enabled_skill_versions: tuple[str, ...] = ()
    factor_context: AnalysisFactorContext = Field(default_factory=AnalysisFactorContext)
    strategy_context: str | None = Field(
        default=None, pattern=ANALYSIS_PROFILE_ID_PATTERN
    )
    debate_rounds: StrictInt = Field(default=2, ge=0, le=MAX_DEBATE_ROUNDS)
    risk_debate_rounds: StrictInt = Field(
        default=1, ge=0, le=MAX_RISK_DEBATE_ROUNDS
    )
    output_schema_version: str = Field(
        default="analysis-report-v1", pattern=ANALYSIS_PROFILE_ID_PATTERN
    )
    disclaimer_profile: str = Field(
        default="standard-cn-v1", pattern=ANALYSIS_PROFILE_ID_PATTERN
    )
    checksum: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    created_at: datetime = Field(default_factory=_analysis_utc_now)
    created_by: str = Field(min_length=1, max_length=128)
    published_at: datetime | None = None
    change_summary: str = Field(default="", max_length=2000)
    parent_version_id: str | None = Field(
        default=None, pattern=ANALYSIS_PROFILE_ID_PATTERN
    )

    @field_validator("selected_analysts")
    @classmethod
    def require_unique_analysts(
        cls, value: tuple[AnalysisAnalyst, ...]
    ) -> tuple[AnalysisAnalyst, ...]:
        if len(set(value)) != len(value):
            raise ValueError("selected_analysts must be unique")
        return value

    @field_validator("enabled_skill_versions")
    @classmethod
    def validate_skill_version_refs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("enabled_skill_versions must be unique")
        if any(not re.fullmatch(ANALYSIS_PROFILE_ID_PATTERN, item) for item in value):
            raise ValueError("enabled_skill_versions contains an invalid reference")
        return value

    @field_validator("user_id", "created_by", "change_summary")
    @classmethod
    def require_trimmed_version_text(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("profile version text fields must be trimmed")
        return value

    @field_validator("created_at", "published_at")
    @classmethod
    def normalize_version_times(cls, value: datetime | None) -> datetime | None:
        return _normalized_analysis_time(value)

    @model_validator(mode="after")
    def validate_version_lifecycle(self) -> "AnalysisProfileVersion":
        if self.version == 1 and self.parent_version_id is not None:
            raise ValueError("profile version 1 cannot have a parent")
        if self.version > 1 and self.parent_version_id is None:
            raise ValueError("later profile versions require parent provenance")
        if self.parent_version_id == self.profile_version_id:
            raise ValueError("a profile version cannot be its own parent")
        if self.status in {
            AnalysisProfileVersionStatus.PUBLISHED,
            AnalysisProfileVersionStatus.DEPRECATED,
        }:
            if self.published_at is None:
                raise ValueError("published profile versions require published_at")
        elif self.published_at is not None:
            raise ValueError("draft profile versions cannot have published_at")
        expected = self.content_checksum()
        if self.checksum is not None and self.checksum != expected:
            raise ValueError("checksum does not match profile version content")
        object.__setattr__(self, "checksum", expected)
        return self

    def content_checksum(self) -> str:
        payload = self.model_dump(
            mode="json", exclude={"checksum", "status", "published_at"}
        )
        return _analysis_checksum(payload)


class ResolvedAnalysisProfile(BaseModel):
    """Single validated runtime shape consumed by future analysis execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: AnalysisProfileSource
    profile_id: str | None = None
    profile_version_id: str | None = None
    profile_version: int | None = None
    selected_analysts: tuple[AnalysisAnalyst, ...] = Field(min_length=1, max_length=4)
    research_depth: AnalysisResearchDepth
    quick_model_ref: AnalysisModelReference
    deep_model_ref: AnalysisModelReference
    risk_preference: AnalysisRiskPreference
    investment_horizon: AnalysisInvestmentHorizon
    enabled_skill_versions: tuple[str, ...]
    factor_context: AnalysisFactorContext
    strategy_context: str | None = None
    debate_rounds: StrictInt = Field(ge=0, le=MAX_DEBATE_ROUNDS)
    risk_debate_rounds: StrictInt = Field(ge=0, le=MAX_RISK_DEBATE_ROUNDS)
    output_schema_version: str
    disclaimer_profile: str
