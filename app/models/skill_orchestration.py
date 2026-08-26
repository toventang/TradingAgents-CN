import enum
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from app.utils.timezone import now_tz


class SkillBudgetConfig(BaseModel):
    """Skill 编排与预算控制"""
    max_total_timeout_sec: float = 30.0        # 总执行超时时间 (默认 30s)
    max_steps_limit: int = 10                  # 最大单次编排步骤数 (默认 10)
    enable_cache: bool = True                  # 是否启用步长缓存
    allow_fallback: bool = True                # 非关键步骤失败时是否允许降级继续


class SkillDAGStep(BaseModel):
    """Skill DAG 单步节点"""
    step_id: str
    skill_id: str
    version_num: Optional[int] = None           # None 表示使用最新已发布版本
    depends_on: List[str] = Field(default_factory=list) # 依赖的 upstream step_ids
    input_mapping: Dict[str, str] = Field(default_factory=dict) # upstream_step.field -> current_input_field
    static_inputs: Dict[str, Any] = Field(default_factory=dict)
    is_critical: bool = False                  # 关键步骤失败将终止整个 DAG


class SkillOrchestrationPlan(BaseModel):
    """Skill DAG 编排计划"""
    plan_id: str
    steps: List[SkillDAGStep]
    budget: SkillBudgetConfig = Field(default_factory=SkillBudgetConfig)


class SkillOrchestrationResult(BaseModel):
    """Skill 编排执行结果"""
    orchestration_id: str
    plan_id: str
    success: bool
    step_results: Dict[str, Any] = Field(default_factory=dict) # step_id -> result
    failed_steps: List[str] = Field(default_factory=list)
    total_execution_time_ms: float = 0.0
    error_message: Optional[str] = None
    executed_at: datetime = Field(default_factory=now_tz)
