"""Durable domain-task adapter for leakage-safe factor research."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError
from pymongo.errors import PyMongoError

from app.models.domain_task import DomainTaskResultRef, DomainTaskType
from app.models.factor import FactorAnalysisTaskPayload
from app.repositories.factor_repository import FactorAnalysisConflict
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
from app.services.factors.analysis import (
    FactorAnalysisError,
    FactorAnalysisService,
)


class FactorAnalysisTaskHandler:
    def __init__(self, service: FactorAnalysisService):
        self.service = service

    async def __call__(
        self,
        payload: Mapping[str, Any],
        context: DomainTaskContext,
        report_progress: ProgressCallback,
        is_cancelled: CancellationChecker,
    ) -> DomainTaskResultRef:
        try:
            parsed = FactorAnalysisTaskPayload.model_validate(dict(payload))
        except ValidationError as exc:
            raise TerminalTaskError(
                "Invalid factor analysis payload",
                code="FACTOR_ANALYSIS_REQUEST_INVALID",
                details={"errors": exc.errors(include_input=False, include_url=False)},
            ) from exc
        if await is_cancelled():
            raise TaskCancellationRequested("factor analysis was cancelled")
        try:
            result = await self.service.analyze(
                user_id=context.user_id,
                task_id=context.task_id,
                analysis_id=parsed.analysis_id,
                request=parsed.request,
                report_progress=report_progress,
                is_cancelled=is_cancelled,
            )
        except TaskCancellationRequested:
            raise
        except FactorAnalysisError as exc:
            raise TerminalTaskError(
                str(exc),
                code=exc.code,
                details=exc.details,
            ) from exc
        except FactorAnalysisConflict as exc:
            raise TerminalTaskError(
                "Factor analysis immutable result conflict",
                code="FACTOR_ANALYSIS_RESULT_CONFLICT",
            ) from exc
        except PyMongoError as exc:
            raise RetryableTaskError(
                "Factor analysis storage is temporarily unavailable",
                code="FACTOR_ANALYSIS_STORE_RETRYABLE",
            ) from exc
        except Exception as exc:
            raise RetryableTaskError(
                "Factor analysis failed before result publication",
                code="FACTOR_ANALYSIS_RETRYABLE",
                details={"exception_type": type(exc).__name__},
            ) from exc
        return DomainTaskResultRef(
            collection="factor_analysis_results",
            id=result.analysis_id,
        )


def register_factor_analysis_handler(
    service: FactorAnalysisService,
    *,
    registry: DomainTaskHandlerRegistry = domain_task_handler_registry,
) -> FactorAnalysisTaskHandler:
    handler = FactorAnalysisTaskHandler(service)
    registry.register(DomainTaskType.FACTOR_ANALYSIS, handler)
    return handler
