from __future__ import annotations

import pytest

from app.models.domain_task import DomainTaskType
from app.repositories.backtest_repository import BacktestRepository
from app.services.backtest.ledger import BacktestRunStatus
from app.services.domain_tasks import (
    DomainTaskContext,
    DomainTaskHandlerRegistry,
    RetryableTaskError,
    TaskCancellationRequested,
    TerminalTaskError,
)
from app.workers.handlers.backtest import register_backtest_handler
from tests.strategy_fakes import FakeDatabase
from tests.unit.backtest.test_engine import (
    InterruptOnceRepository,
    make_engine,
    make_run,
    no_cancel,
    no_progress,
)


def context(task_id: str, *, user_id: str = "owner") -> DomainTaskContext:
    return DomainTaskContext(
        task_id=task_id,
        user_id=user_id,
        task_type=DomainTaskType.BACKTEST,
        attempt=1,
        max_attempts=3,
    )


@pytest.mark.asyncio
async def test_registered_backtest_worker_commits_result_and_is_idempotent():
    database = FakeDatabase()
    repository = BacktestRepository(database)
    await repository.create_run(make_run(run_id="worker-run", task_id="worker-task"))
    registry = DomainTaskHandlerRegistry()
    handler = register_backtest_handler(make_engine(repository), registry=registry)
    progress: list[tuple[float, str, str | None]] = []

    async def report(value, stage, message=None):
        progress.append((value, stage, message))

    result = await handler(
        {"run_id": "worker-run"}, context("worker-task"), report, no_cancel
    )
    duplicate = await handler(
        {"run_id": "worker-run"}, context("worker-task"), no_progress, no_cancel
    )

    assert registry.resolve(DomainTaskType.BACKTEST) is handler
    assert result.collection == "backtest_runs"
    assert result.id == duplicate.id == "worker-run"
    assert progress[-1][0] == 1
    run = await repository.get_run("worker-run", user_id="owner")
    assert run is not None and run.status == BacktestRunStatus.SUCCEEDED
    assert len(database[repository.CHECKPOINTS_COLLECTION].documents) == 3
    assert len(database[repository.TRADES_COLLECTION].documents) == 2


@pytest.mark.asyncio
async def test_worker_retries_from_durable_checkpoint_without_duplicate_ledgers():
    database = FakeDatabase()
    repository = InterruptOnceRepository(database)
    await repository.create_run(make_run(run_id="retry-run", task_id="retry-task"))
    handler = register_backtest_handler(
        make_engine(repository), registry=DomainTaskHandlerRegistry()
    )

    with pytest.raises(RetryableTaskError) as interrupted:
        await handler(
            {"run_id": "retry-run"},
            context("retry-task"),
            no_progress,
            no_cancel,
        )
    assert interrupted.value.error_code == "BACKTEST_EXECUTION_RETRYABLE"

    result = await handler(
        {"run_id": "retry-run"}, context("retry-task"), no_progress, no_cancel
    )
    assert result.id == "retry-run"
    assert len(database[repository.CHECKPOINTS_COLLECTION].documents) == 3
    trade_ids = [
        item["trade_id"] for item in database[repository.TRADES_COLLECTION].documents
    ]
    event_ids = [
        item["event_id"] for item in database[repository.EVENTS_COLLECTION].documents
    ]
    assert len(trade_ids) == len(set(trade_ids)) == 2
    assert len(event_ids) == len(set(event_ids))


@pytest.mark.asyncio
async def test_worker_validates_owner_and_cancels_a_queued_run_durably():
    database = FakeDatabase()
    repository = BacktestRepository(database)
    await repository.create_run(make_run(run_id="cancel-run", task_id="cancel-task"))
    handler = register_backtest_handler(
        make_engine(repository), registry=DomainTaskHandlerRegistry()
    )

    with pytest.raises(TerminalTaskError) as invalid:
        await handler({}, context("cancel-task"), no_progress, no_cancel)
    assert invalid.value.error_code == "BACKTEST_REQUEST_INVALID"

    with pytest.raises(TerminalTaskError) as isolated:
        await handler(
            {"run_id": "cancel-run"},
            context("cancel-task", user_id="another-owner"),
            no_progress,
            no_cancel,
        )
    assert isolated.value.error_code == "BACKTEST_RUN_NOT_FOUND"

    async def cancelled():
        return True

    with pytest.raises(TaskCancellationRequested):
        await handler(
            {"run_id": "cancel-run"},
            context("cancel-task"),
            no_progress,
            cancelled,
        )
    run = await repository.get_run("cancel-run", user_id="owner")
    assert run is not None and run.status == BacktestRunStatus.CANCELLED
    assert database[repository.CHECKPOINTS_COLLECTION].documents == []
    assert database[repository.TRADES_COLLECTION].documents == []
