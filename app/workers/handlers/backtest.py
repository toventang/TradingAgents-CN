"""Durable domain-task adapter for restart-safe backtest execution."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from pymongo.errors import PyMongoError

from app.models.domain_task import DomainTaskResultRef, DomainTaskType
from app.repositories.backtest_repository import BacktestPersistenceConflict
from app.services.backtest.engine import BacktestEngine, BacktestEngineError
from app.services.backtest.ledger import BacktestRunStatus
from app.services.backtest.parameter_search import (
    ParameterSearchConflict,
    ParameterSearchNotFound,
    ParameterSearchRecord,
    ParameterSearchValidationError,
    result_ref as parameter_search_result_ref,
)
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

    run_id: str | None = Field(default=None, min_length=1, max_length=128)
    parameter_search_id: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def exactly_one_workload(self) -> "BacktestTaskPayload":
        if (self.run_id is None) == (self.parameter_search_id is None):
            raise ValueError("exactly one backtest workload identifier is required")
        return self


ParameterSearchExecutor = Callable[..., Awaitable[ParameterSearchRecord]]


class BacktestTaskHandler:
    def __init__(
        self,
        engine: BacktestEngine,
        *,
        parameter_search_executor: ParameterSearchExecutor | None = None,
    ):
        self.engine = engine
        self.parameter_search_executor = parameter_search_executor

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
        if parsed.parameter_search_id is not None:
            return await self._run_parameter_search(
                parsed.parameter_search_id,
                context=context,
                report_progress=report_progress,
                is_cancelled=is_cancelled,
            )
        assert parsed.run_id is not None
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

    async def _run_parameter_search(
        self,
        search_id: str,
        *,
        context: DomainTaskContext,
        report_progress: ProgressCallback,
        is_cancelled: CancellationChecker,
    ) -> DomainTaskResultRef:
        if self.parameter_search_executor is None:
            raise TerminalTaskError(
                "Parameter-search executor is not configured",
                code="PARAMETER_SEARCH_HANDLER_UNAVAILABLE",
            )
        try:
            search = await self.parameter_search_executor(
                search_id=search_id,
                user_id=context.user_id,
                task_id=context.task_id,
                report_progress=report_progress,
                is_cancelled=is_cancelled,
            )
        except TaskCancellationRequested:
            raise
        except PyMongoError as exc:
            raise RetryableTaskError(
                "Parameter-search persistence is temporarily unavailable",
                code="BACKTEST_STORE_RETRYABLE",
            ) from exc
        except (
            ParameterSearchValidationError,
            ParameterSearchNotFound,
            ParameterSearchConflict,
            ValueError,
            KeyError,
        ) as exc:
            raise TerminalTaskError(
                "Parameter search is not executable",
                code=getattr(exc, "code", "PARAMETER_SEARCH_NOT_EXECUTABLE"),
                details={"exception_type": type(exc).__name__},
            ) from exc
        except Exception as exc:
            raise RetryableTaskError(
                "Parameter search was interrupted after its last durable result",
                code="PARAMETER_SEARCH_RETRYABLE",
                details={"exception_type": type(exc).__name__},
            ) from exc
        return parameter_search_result_ref(search)


def register_backtest_handler(
    engine: BacktestEngine,
    *,
    parameter_search_executor: ParameterSearchExecutor | None = None,
    registry: DomainTaskHandlerRegistry = domain_task_handler_registry,
) -> BacktestTaskHandler:
    handler = BacktestTaskHandler(
        engine, parameter_search_executor=parameter_search_executor
    )
    registry.register(DomainTaskType.BACKTEST, handler)
    return handler
