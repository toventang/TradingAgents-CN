"""Durable domain-task adapter for one alert evaluation batch."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.models.alert import AlertMarket
from app.models.domain_task import DomainTaskResultRef, DomainTaskType
from app.services.alerts.evaluator import (
    AlertBatchCancelled,
    AlertEvaluationBatchService,
)
from app.services.domain_tasks import (
    CancellationChecker,
    DomainTaskContext,
    DomainTaskHandlerRegistry,
    ProgressCallback,
    RetryableTaskError,
    TaskCancellationRequested,
    TerminalTaskError,
    domain_task_handler_registry,
)


class AlertEvaluationTaskPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    market: AlertMarket
    frequency_seconds: int = Field(ge=30, le=86_400)
    evaluated_at: datetime
    holidays: tuple[str, ...] = ()

    @field_validator("evaluated_at")
    @classmethod
    def normalize_evaluated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")
        return value.astimezone(timezone.utc)


class AlertEvaluationTaskHandler:
    def __init__(self, service: AlertEvaluationBatchService):
        self.service = service

    async def __call__(
        self,
        payload: Mapping[str, Any],
        context: DomainTaskContext,
        report_progress: ProgressCallback,
        is_cancelled: CancellationChecker,
    ) -> DomainTaskResultRef:
        try:
            request = AlertEvaluationTaskPayload.model_validate(dict(payload))
        except ValidationError as exc:
            raise TerminalTaskError(
                "Invalid alert evaluation payload",
                code="ALERT_EVALUATION_REQUEST_INVALID",
                details={"errors": exc.errors(include_input=False, include_url=False)},
            ) from exc
        if await is_cancelled():
            raise TaskCancellationRequested("alert evaluation was cancelled")
        try:
            result = await self.service.execute(
                task_id=context.task_id,
                market=request.market,
                frequency_seconds=request.frequency_seconds,
                evaluated_at=request.evaluated_at,
                holidays=request.holidays,
                report_progress=report_progress,
                is_cancelled=is_cancelled,
            )
        except AlertBatchCancelled as exc:
            raise TaskCancellationRequested(str(exc)) from exc
        except (ValueError, TypeError) as exc:
            raise TerminalTaskError(
                "Alert evaluation request is not executable",
                code="ALERT_EVALUATION_NOT_EXECUTABLE",
                details={"exception_type": type(exc).__name__},
            ) from exc
        except TaskCancellationRequested:
            raise
        except Exception as exc:
            raise RetryableTaskError(
                "Alert evaluation batch failed",
                code="ALERT_EVALUATION_RETRYABLE",
                details={"exception_type": type(exc).__name__},
            ) from exc
        assert result.run_id is not None
        return DomainTaskResultRef(
            collection="alert_evaluation_runs",
            id=result.run_id,
        )


def register_alert_evaluation_handler(
    service: AlertEvaluationBatchService,
    *,
    registry: DomainTaskHandlerRegistry = domain_task_handler_registry,
) -> AlertEvaluationTaskHandler:
    handler = AlertEvaluationTaskHandler(service)
    registry.register(DomainTaskType.ALERT_EVAL, handler)
    return handler
