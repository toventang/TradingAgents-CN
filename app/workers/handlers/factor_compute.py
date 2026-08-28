"""Durable domain-task adapter for factor snapshot computation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from app.models.domain_task import DomainTaskResultRef, DomainTaskType
from app.models.factor import FactorComputeRequest
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
from app.services.factors.engine import FactorComputationInProgress, FactorEngine


class FactorComputeTaskHandler:
    def __init__(self, engine: FactorEngine):
        self.engine = engine

    async def __call__(
        self,
        payload: Mapping[str, Any],
        context: DomainTaskContext,
        report_progress: ProgressCallback,
        is_cancelled: CancellationChecker,
    ) -> DomainTaskResultRef:
        try:
            request = FactorComputeRequest.model_validate(dict(payload))
        except ValidationError as exc:
            raise TerminalTaskError(
                "Invalid factor computation payload",
                code="FACTOR_REQUEST_INVALID",
                details={"errors": exc.errors(include_input=False, include_url=False)},
            ) from exc
        if await is_cancelled():
            raise TaskCancellationRequested("factor computation was cancelled")
        try:
            result = await self.engine.compute(
                user_id=context.user_id,
                task_id=context.task_id,
                request=request,
                report_progress=report_progress,
                is_cancelled=is_cancelled,
            )
        except TaskCancellationRequested:
            raise
        except FactorComputationInProgress as exc:
            raise RetryableTaskError(
                "Identical factor computation is still in progress",
                code="FACTOR_REQUEST_IN_PROGRESS",
            ) from exc
        except (ValueError, KeyError) as exc:
            raise TerminalTaskError(
                "Factor computation request is not executable",
                code="FACTOR_REQUEST_NOT_EXECUTABLE",
                details={"exception_type": type(exc).__name__},
            ) from exc
        except Exception as exc:
            raise RetryableTaskError(
                "Factor computation failed before snapshot publication",
                code="FACTOR_COMPUTE_RETRYABLE",
                details={"exception_type": type(exc).__name__},
            ) from exc
        return DomainTaskResultRef(
            collection="factor_snapshots", id=result.snapshot.snapshot_id
        )


def register_factor_compute_handler(
    engine: FactorEngine,
    *,
    registry: DomainTaskHandlerRegistry = domain_task_handler_registry,
) -> FactorComputeTaskHandler:
    """Register one explicit handler; no payload-selected imports are allowed."""
    handler = FactorComputeTaskHandler(engine)
    registry.register(DomainTaskType.FACTOR_COMPUTE, handler)
    return handler
