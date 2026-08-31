"""Persistent domain-task and append-only event models."""

from datetime import datetime, timezone
from enum import Enum, IntEnum
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class DomainTaskType(str, Enum):
    FACTOR_COMPUTE = "factor_compute"
    FACTOR_ANALYSIS = "factor_analysis"
    STRATEGY_RUN = "strategy_run"
    BACKTEST = "backtest"
    ALERT_EVAL = "alert_eval"
    CAMPAIGN_EVAL = "campaign_eval"
    ATTRIBUTION = "attribution"


class DomainTaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    RETRY_WAIT = "retry_wait"
    FAILED = "failed"


class DomainTaskPriority(IntEnum):
    NORMAL = 0
    INTERACTIVE = 10
    SYSTEM_URGENT = 20


class DomainTaskResultRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    collection: str = Field(min_length=1, max_length=120)
    id: str = Field(min_length=1, max_length=200)


class DomainTaskError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=2000)
    retryable: bool
    details: dict[str, Any] = Field(default_factory=dict)


class DomainTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    user_id: str = Field(min_length=1)
    task_type: DomainTaskType
    status: DomainTaskStatus = DomainTaskStatus.QUEUED
    priority: int = Field(default=DomainTaskPriority.NORMAL, ge=0, le=20)
    payload: dict[str, Any]
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    stage: str = Field(default="queued", min_length=1, max_length=120)
    message: Optional[str] = Field(default=None, max_length=2000)
    result_ref: Optional[DomainTaskResultRef] = None
    attempt: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=3, ge=1, le=100)
    worker_id: Optional[str] = Field(default=None, min_length=1, max_length=200)
    heartbeat_at: Optional[datetime] = None
    lease_expires_at: Optional[datetime] = None
    cancel_requested_at: Optional[datetime] = None
    error: Optional[DomainTaskError] = None
    created_at: datetime = Field(default_factory=utc_now)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=utc_now)
    idempotency_key: Optional[str] = Field(default=None, min_length=1, max_length=200)
    request_hash: Optional[str] = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    _utc_datetimes = field_validator(
        "heartbeat_at",
        "lease_expires_at",
        "cancel_requested_at",
        "created_at",
        "started_at",
        "finished_at",
        "updated_at",
        mode="before",
    )(_normalize_utc)

    @field_validator("task_id")
    @classmethod
    def validate_task_uuid(cls, value: str) -> str:
        try:
            return str(UUID(value))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("task_id must be a UUID string") from exc

    @field_validator("user_id", "stage")
    @classmethod
    def validate_non_whitespace_fields(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must contain non-whitespace characters")
        return value

    @model_validator(mode="after")
    def validate_task_invariants(self) -> "DomainTask":
        if (self.idempotency_key is None) != (self.request_hash is None):
            raise ValueError(
                "idempotency_key and request_hash must both be set or both be absent"
            )
        if self.attempt > self.max_attempts:
            raise ValueError("attempt cannot exceed max_attempts")
        if self.status in {
            DomainTaskStatus.RUNNING,
            DomainTaskStatus.CANCELLING,
        } and (not self.worker_id or not self.lease_expires_at):
            raise ValueError(
                "running and cancelling tasks require worker_id and lease"
            )
        if self.status in {
            DomainTaskStatus.SUCCEEDED,
            DomainTaskStatus.CANCELLED,
            DomainTaskStatus.FAILED,
        } and self.finished_at is None:
            raise ValueError("terminal tasks require finished_at")
        return self


class DomainTaskEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    task_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1, max_length=120)
    status: DomainTaskStatus
    message: Optional[str] = Field(default=None, max_length=2000)
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)

    _created_at_utc = field_validator("created_at", mode="before")(_normalize_utc)

    @field_validator("event_id")
    @classmethod
    def validate_event_uuid(cls, value: str) -> str:
        try:
            return str(UUID(value))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("event_id must be a UUID string") from exc
