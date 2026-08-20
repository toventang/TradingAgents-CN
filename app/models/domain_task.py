import enum
from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from app.utils.timezone import now_tz


class TaskStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    RETRY_WAIT = "retry_wait"
    FAILED = "failed"


class TaskType(str, enum.Enum):
    FACTOR_COMPUTE = "factor_compute"
    STRATEGY_RUN = "strategy_run"
    BACKTEST = "backtest"
    ALERT_EVAL = "alert_eval"
    CAMPAIGN_EVAL = "campaign_eval"
    ATTRIBUTION = "attribution"


class InvalidTaskTransitionError(ValueError):
    """非法任务状态转换异常"""
    pass


LEGAL_TRANSITIONS: Dict[TaskStatus, List[TaskStatus]] = {
    TaskStatus.QUEUED: [TaskStatus.RUNNING, TaskStatus.CANCELLED],
    TaskStatus.RUNNING: [TaskStatus.SUCCEEDED, TaskStatus.CANCELLING, TaskStatus.RETRY_WAIT, TaskStatus.FAILED, TaskStatus.QUEUED, TaskStatus.CANCELLED],
    TaskStatus.CANCELLING: [TaskStatus.CANCELLED, TaskStatus.FAILED],
    TaskStatus.RETRY_WAIT: [TaskStatus.QUEUED, TaskStatus.FAILED],
    TaskStatus.SUCCEEDED: [],
    TaskStatus.CANCELLED: [],
    TaskStatus.FAILED: [],
}


def validate_task_transition(from_status: TaskStatus, to_status: TaskStatus) -> bool:
    """验证状态转换合法性"""
    if from_status == to_status:
        return True
    allowed = LEGAL_TRANSITIONS.get(from_status, [])
    if to_status not in allowed:
        raise InvalidTaskTransitionError(
            f"Illegal state transition from {from_status.value} to {to_status.value}"
        )
    return True


class DomainTask(BaseModel):
    """通用持久任务模型"""
    task_id: str
    user_id: str
    task_type: TaskType
    status: TaskStatus = TaskStatus.QUEUED
    priority: int = 0
    payload: Dict[str, Any] = Field(default_factory=dict)
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    stage: str = "queued"
    message: Optional[str] = None
    result_ref: Optional[Dict[str, Any]] = None
    attempt: int = 0
    max_attempts: int = 3
    worker_id: Optional[str] = None
    heartbeat_at: Optional[datetime] = None
    lease_expires_at: Optional[datetime] = None
    cancel_requested_at: Optional[datetime] = None
    error: Optional[Dict[str, Any]] = None
    created_at: datetime = Field(default_factory=now_tz)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=now_tz)
    idempotency_key: Optional[str] = None
    request_hash: Optional[str] = None


class DomainTaskEvent(BaseModel):
    """任务进度与状态事件"""
    event_id: str
    task_id: str
    user_id: str
    stage: str
    progress: float
    message: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    created_at: datetime = Field(default_factory=now_tz)
