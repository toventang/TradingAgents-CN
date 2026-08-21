import asyncio
from datetime import datetime, timezone
import signal

import pytest

from app.models.domain_task import (
    DomainTaskResultRef,
    DomainTaskStatus,
)
from app.repositories.domain_task_repository import DomainTaskRepository
from app.services.domain_tasks import (
    DomainTaskHandlerRegistry,
    RetryableTaskError,
    TerminalTaskError,
)
from app.workers.domain_task_worker import DomainTaskWorker
from tests.unit.domain_tasks.fakes import FakeDatabase

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def make_repository():
    repository = DomainTaskRepository(FakeDatabase())
    await repository.ensure_indexes()
    return repository


def make_worker(repository, registry):
    return DomainTaskWorker(
        repository,
        registry,
        worker_id="test-worker",
        lease_seconds=10,
        heartbeat_seconds=0.01,
        poll_seconds=0.01,
    )


async def test_worker_success_persists_progress_and_result_reference():
    repository = await make_repository()
    task = await repository.create_task(
        user_id="owner",
        task_type="backtest",
        payload={"validated": True},
    )
    registry = DomainTaskHandlerRegistry()

    async def success(payload, context, report_progress, is_cancelled):
        assert payload == {"validated": True}
        assert context.task_id == task.task_id
        assert context.user_id == "owner"
        assert context.attempt == 1
        assert await is_cancelled() is False
        await report_progress(0.4, "computing", "deterministic step")
        return DomainTaskResultRef(collection="backtest_runs", id="run-1")

    registry.register("backtest", success)
    assert await make_worker(repository, registry).run_once() is True

    persisted = await repository.get_task(task.task_id, "owner")
    assert persisted.status == DomainTaskStatus.SUCCEEDED
    assert persisted.progress == 1.0
    assert persisted.result_ref == DomainTaskResultRef(
        collection="backtest_runs",
        id="run-1",
    )
    events = await repository.list_events(
        task_id=task.task_id,
        user_id="owner",
    )
    assert {event.event_type for event in events} == {
        "created",
        "claimed",
        "progress",
        "succeeded",
    }
    progress_event = next(
        event for event in events if event.event_type == "progress"
    )
    assert progress_event.data == {"progress": 0.4, "stage": "computing"}


async def test_retryable_failure_requeues_and_succeeds_on_next_attempt():
    repository = await make_repository()
    task = await repository.create_task(
        user_id="owner",
        task_type="factor_compute",
        payload={},
        max_attempts=2,
    )
    registry = DomainTaskHandlerRegistry()

    async def flaky(payload, context, report_progress, is_cancelled):
        if context.attempt == 1:
            raise RetryableTaskError(
                "temporary data outage",
                code="DATA_TEMPORARILY_UNAVAILABLE",
            )
        return DomainTaskResultRef(collection="factor_snapshots", id="snap-1")

    registry.register("factor_compute", flaky)
    worker = make_worker(repository, registry)
    await worker.run_once()
    waiting = await repository.get_task(task.task_id, "owner")
    assert waiting.status == DomainTaskStatus.QUEUED
    assert waiting.attempt == 1
    assert waiting.error.code == "DATA_TEMPORARILY_UNAVAILABLE"
    assert waiting.error.retryable is True

    await worker.run_once()
    succeeded = await repository.get_task(task.task_id, "owner")
    assert succeeded.status == DomainTaskStatus.SUCCEEDED
    assert succeeded.attempt == 2


async def test_terminal_failure_is_not_retried():
    repository = await make_repository()
    task = await repository.create_task(
        user_id="owner",
        task_type="strategy_run",
        payload={},
    )
    registry = DomainTaskHandlerRegistry()

    async def terminal(payload, context, report_progress, is_cancelled):
        raise TerminalTaskError("invalid definition", code="INVALID_STRATEGY")

    registry.register("strategy_run", terminal)
    await make_worker(repository, registry).run_once()

    failed = await repository.get_task(task.task_id, "owner")
    assert failed.status == DomainTaskStatus.FAILED
    assert failed.attempt == 1
    assert failed.error.code == "INVALID_STRATEGY"
    assert failed.error.retryable is False


async def test_worker_cooperatively_acknowledges_persisted_cancellation():
    repository = await make_repository()
    task = await repository.create_task(
        user_id="owner",
        task_type="campaign_eval",
        payload={},
    )
    registry = DomainTaskHandlerRegistry()
    started = asyncio.Event()

    async def cancellable(payload, context, report_progress, is_cancelled):
        started.set()
        while not await is_cancelled():
            await asyncio.sleep(0)
        return None

    registry.register("campaign_eval", cancellable)
    running = asyncio.create_task(make_worker(repository, registry).run_once())
    await asyncio.wait_for(started.wait(), timeout=1)
    requested = await repository.request_cancel(
        task_id=task.task_id,
        user_id="owner",
    )
    assert requested.status == DomainTaskStatus.CANCELLING
    await asyncio.wait_for(running, timeout=1)

    cancelled = await repository.get_task(task.task_id, "owner")
    assert cancelled.status == DomainTaskStatus.CANCELLED
    assert cancelled.worker_id is None


async def test_unknown_handler_fails_terminally():
    repository = await make_repository()
    task = await repository.create_task(
        user_id="owner",
        task_type="attribution",
        payload={},
    )

    await make_worker(repository, DomainTaskHandlerRegistry()).run_once()

    failed = await repository.get_task(task.task_id, "owner")
    assert failed.status == DomainTaskStatus.FAILED
    assert failed.error.code == "TASK_HANDLER_NOT_REGISTERED"
    assert failed.error.details == {"task_type": "attribution"}


async def test_persisted_cancellation_wins_race_with_handler_failure():
    repository = await make_repository()
    task = await repository.create_task(
        user_id="owner",
        task_type="strategy_run",
        payload={},
    )
    registry = DomainTaskHandlerRegistry()
    started = asyncio.Event()
    release = asyncio.Event()

    async def failing(payload, context, report_progress, is_cancelled):
        started.set()
        await release.wait()
        raise TerminalTaskError("late failure", code="LATE_FAILURE")

    registry.register("strategy_run", failing)
    running = asyncio.create_task(make_worker(repository, registry).run_once())
    await asyncio.wait_for(started.wait(), timeout=1)
    await repository.request_cancel(task_id=task.task_id, user_id="owner")
    release.set()
    await asyncio.wait_for(running, timeout=1)

    cancelled = await repository.get_task(task.task_id, "owner")
    assert cancelled.status == DomainTaskStatus.CANCELLED
    assert cancelled.error is None


async def test_progress_must_be_finite_and_monotonic():
    repository = await make_repository()
    task = await repository.create_task(
        user_id="owner",
        task_type="alert_eval",
        payload={},
    )
    registry = DomainTaskHandlerRegistry()

    async def regresses(payload, context, report_progress, is_cancelled):
        await report_progress(0.6, "first")
        await report_progress(0.5, "regressed")
        return None

    registry.register("alert_eval", regresses)
    await make_worker(repository, registry).run_once()

    failed = await repository.get_task(task.task_id, "owner")
    assert failed.status == DomainTaskStatus.FAILED
    assert failed.progress == 0.6
    assert failed.error.code == "TASK_UNHANDLED_HANDLER_ERROR"
    assert failed.error.details == {"exception_type": "ValueError"}


async def test_graceful_stop_finishes_active_task_without_claiming_another():
    repository = await make_repository()
    first = await repository.create_task(
        user_id="owner",
        task_type="backtest",
        payload={"sequence": 1},
    )
    second = await repository.create_task(
        user_id="owner",
        task_type="backtest",
        payload={"sequence": 2},
    )
    registry = DomainTaskHandlerRegistry()
    started = asyncio.Event()
    release = asyncio.Event()
    handled = []

    async def blocking(payload, context, report_progress, is_cancelled):
        handled.append(payload["sequence"])
        started.set()
        await release.wait()
        return DomainTaskResultRef(collection="runs", id=str(payload["sequence"]))

    registry.register("backtest", blocking)
    worker = make_worker(repository, registry)
    running = asyncio.create_task(worker.run_forever())
    await asyncio.wait_for(started.wait(), timeout=1)
    worker.stop()
    release.set()
    await asyncio.wait_for(running, timeout=1)

    assert handled == [1]
    assert (await repository.get_task(first.task_id, "owner")).status == (
        DomainTaskStatus.SUCCEEDED
    )
    assert (await repository.get_task(second.task_id, "owner")).status == (
        DomainTaskStatus.QUEUED
    )


async def test_restart_recovers_expired_lease_and_requeues_persisted_retry():
    repository = await make_repository()
    task = await repository.create_task(
        user_id="owner",
        task_type="backtest",
        payload={},
        max_attempts=2,
        now=datetime(2000, 1, 1, tzinfo=timezone.utc),
    )
    await repository.claim_next(
        worker_id="crashed-worker",
        lease_seconds=1,
        now=datetime(2000, 1, 1, tzinfo=timezone.utc),
    )
    registry = DomainTaskHandlerRegistry()

    async def recovered(payload, context, report_progress, is_cancelled):
        assert context.attempt == 2
        return DomainTaskResultRef(collection="runs", id="recovered")

    registry.register("backtest", recovered)
    worker = make_worker(repository, registry)
    counts = await worker.recover_interrupted_tasks()
    assert counts == {"retry_wait": 1, "failed": 0, "requeued": 1}

    await worker.run_once()
    persisted = await repository.get_task(task.task_id, "owner")
    assert persisted.status == DomainTaskStatus.SUCCEEDED
    assert persisted.attempt == 2


async def test_sigterm_handler_requests_graceful_stop():
    repository = await make_repository()
    worker = make_worker(repository, DomainTaskHandlerRegistry())

    class RecordingLoop:
        def __init__(self):
            self.handlers = {}

        def add_signal_handler(self, signum, callback):
            self.handlers[signum] = callback

    loop = RecordingLoop()
    worker.install_signal_handlers(loop)
    assert set(loop.handlers) == {signal.SIGTERM, signal.SIGINT}

    loop.handlers[signal.SIGTERM]()
    assert await worker.run_once() is False
