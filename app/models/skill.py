import enum
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from app.utils.timezone import now_tz


class SkillType(str, enum.Enum):
    MARKET = "market"
    FUNDAMENTALS = "fundamentals"
    TECHNICAL = "technical"
    SENTIMENT = "sentiment"
    RISK = "risk"
    COMPOSITE = "composite"


class SkillStatus(str, enum.Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    DEPRECATED = "deprecated"


class SkillIOContract(BaseModel):
    """Skill 输入输出 Schema 契约"""
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    output_schema: Dict[str, Any] = Field(default_factory=dict)


class SkillVersion(BaseModel):
    """不可变 Skill 版本"""
    version_id: str
    skill_id: str
    version_num: int = 1
    code: str                                 # Python 代码片段
    contract: SkillIOContract = Field(default_factory=SkillIOContract)
    checksum: str = ""
    is_published: bool = False
    commit_message: str = ""
    created_at: datetime = Field(default_factory=now_tz)


class Skill(BaseModel):
    """Skill 主体模型"""
    skill_id: str
    user_id: str
    name: str
    description: str = ""
    skill_type: SkillType = SkillType.MARKET
    is_system_skill: bool = False
    status: SkillStatus = SkillStatus.DRAFT
    latest_version_num: int = 1
    published_version_num: Optional[int] = None
    created_at: datetime = Field(default_factory=now_tz)
    updated_at: datetime = Field(default_factory=now_tz)


class SkillExecutionResult(BaseModel):
    """Skill 执行结果"""
    execution_id: str
    skill_id: str
    version_num: int
    success: bool
    result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    execution_time_ms: float = 0.0
    executed_at: datetime = Field(default_factory=now_tz)
