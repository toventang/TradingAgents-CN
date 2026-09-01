"""Durable domain-task adapter for restart-safe backtest execution."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pymongo.errors import PyMongoError

from app.models.domain_task import DomainTaskResultRef, DomainTaskType
from app.repositories.backtest_repository import BacktestPersistenceConflict
from app.services.backtest.engine import BacktestEngine, BacktestEngineError
from app.services.backtest.ledger import BacktestRunStatus
from app.services.backtest.portfolio import PortfolioReconciliationError
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


class BacktestTaskPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(min_length=1, max_length=128)


class BacktestTaskHandler:
    def __init__(self, engine: BacktestEngine):
        self.engine = engine

    async def __call__(
        self,
        payload: Mapping[str, Any],
        context: DomainTaskContext,
        report_progress: ProgressCallback,
        is_cancelled: CancellationChecker,
    ) -> DomainTaskResultRef:
        try:
            parsed = BacktestTaskPayload.model_validate(dict(payload))
        except ValidationError as exc:
            raise TerminalTaskError(
                "Invalid backtest task payload",
                code="BACKTEST_REQUEST_INVALID",
                details={"errors": exc.errors(include_input=False, include_url=False)},
            ) from exc
        if context.task_type != DomainTaskType.BACKTEST:
            raise TerminalTaskError(
                "Backtest handler received another task type",
                code="BACKTEST_TASK_TYPE_INVALID",
            )
        try:
            run = await self.engine.repository.get_run(
                parsed.run_id, user_id=context.user_id
            )
        except PyMongoError as exc:
            raise RetryableTaskError(
                "Backtest persistence is temporarily unavailable",
                code="BACKTEST_STORE_RETRYABLE",
            ) from exc
        except Exception as exc:
            raise RetryableTaskError(
                "Backtest run could not be loaded",
                code="BACKTEST_EXECUTION_RETRYABLE",
                details={"exception_type": type(exc).__name__},
            ) from exc
        if run is None:
            raise TerminalTaskError(
                "Backtest run does not exist for the task owner",
                code="BACKTEST_RUN_NOT_FOUND",
            )
        if run.task_id != context.task_id:
            raise TerminalTaskError(
                "Backtest run belongs to another durable task",
                code="BACKTEST_TASK_ID_MISMATCH",
            )
        if run.status == BacktestRunStatus.SUCCEEDED:
            return DomainTaskResultRef(collection="backtest_runs", id=run.run_id)
        if await is_cancelled():
            if run.status in {
                BacktestRunStatus.QUEUED,
                BacktestRunStatus.RUNNING,
            }:
                try:
                    await self.engine.repository.mark_run_cancelled(
                        parsed.run_id, user_id=context.user_id
                    )
                except PyMongoError as exc:
                    raise RetryableTaskError(
                        "Backtest cancellation could not be persisted",
                        code="BACKTEST_STORE_RETRYABLE",
                    ) from exc
            raise TaskCancellationRequested("backtest was cancelled")
        try:
            result = await self.engine.run(
                run_id=parsed.run_id,
                user_id=context.user_id,
                task_id=context.task_id,
                report_progress=report_progress,
                is_cancelled=is_cancelled,
            )
        except TaskCancellationRequested:
            raise
        except PyMongoError as exc:
            raise RetryableTaskError(
                "Backtest persistence is temporarily unavailable",
                code="BACKTEST_STORE_RETRYABLE",
            ) from exc
        except (
            BacktestEngineError,
            BacktestPersistenceConflict,
            PortfolioReconciliationError,
            ValueError,
            KeyError,
        ) as exc:
            try:
                run = await self.engine.repository.get_run(
                    parsed.run_id, user_id=context.user_id
                )
                if run is not None and run.status == BacktestRunStatus.RUNNING:
                    await self.engine.repository.mark_run_failed(
                        parsed.run_id,
                        user_id=context.user_id,
                        error={
                            "code": getattr(
                                exc, "code", "BACKTEST_NOT_EXECUTABLE"
                            ),
                            "message": str(exc),
                            "exception_type": type(exc).__name__,
                        },
                    )
            except PyMongoError as store_exc:
                raise RetryableTaskError(
                    "Backtest failure state could not be persisted",
                    code="BACKTEST_STORE_RETRYABLE",
                ) from store_exc
            raise TerminalTaskError(
                "Backtest request is not executable",
                code=getattr(exc, "code", "BACKTEST_NOT_EXECUTABLE"),
                details={"exception_type": type(exc).__name__},
            ) from exc
        except Exception as exc:
            raise RetryableTaskError(
                "Backtest execution was interrupted after its last durable checkpoint",
                code="BACKTEST_EXECUTION_RETRYABLE",
                details={"exception_type": type(exc).__name__},
            ) from exc
        return DomainTaskResultRef(collection="backtest_runs", id=result.run_id)


def register_backtest_handler(
    engine: BacktestEngine,
    *,
    registry: DomainTaskHandlerRegistry = domain_task_handler_registry,
) -> BacktestTaskHandler:
    handler = BacktestTaskHandler(engine)
    registry.register(DomainTaskType.BACKTEST, handler)
    return handler
