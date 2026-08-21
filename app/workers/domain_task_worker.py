"""Durable worker lifecycle for explicitly registered domain-task handlers."""

import asyncio
import logging
import math
import os
import signal
import socket
from contextlib import suppress
from typing import Optional
from uuid import uuid4

from app.models.domain_task import (
    DomainTask,
    DomainTaskResultRef,
    DomainTaskStatus,
)
from app.repositories.domain_task_repository import DomainTaskRepository
from app.services.domain_tasks import (
    DomainTaskContext,
    DomainTaskHandlerRegistry,
    LeaseOwnershipError,
    TaskCancellationRequested,
    TaskExecutionError,
    TerminalTaskError,
    domain_task_handler_registry,
)

logger = logging.getLogger("domain_task_worker")


def default_worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:12]}"


class DomainTaskWorker:
    """Claims one durable task at a time and owns it only while its lease is live."""

    def __init__(
        self,
        repository: DomainTaskRepository,
        registry: DomainTaskHandlerRegistry,
        *,
        worker_id: Optional[str] = None,
        lease_seconds: int = 60,
        heartbeat_seconds: float = 15.0,
        poll_seconds: float = 1.0,
    ) -> None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        if not 0 < heartbeat_seconds < lease_seconds:
            raise ValueError("heartbeat_seconds must be between zero and the lease")
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        self.repository = repository
        self.registry = registry
        self.worker_id = worker_id or default_worker_id()
        self.lease_seconds = lease_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.poll_seconds = poll_seconds
        self._stop_requested = asyncio.Event()

    def stop(self) -> None:
        """Stop accepting new work; an active handler is allowed to finish."""

        self._stop_requested.set()

    def install_signal_handlers(
        self,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ) -> None:
        """Translate SIGTERM/SIGINT into a graceful stop request."""

        event_loop = loop or asyncio.get_running_loop()
        for signum in (signal.SIGTERM, signal.SIGINT):
            try:
                event_loop.add_signal_handler(signum, self.stop)
            except (NotImplementedError, RuntimeError):
                # Windows event loops do not implement add_signal_handler.
                signal.signal(signum, lambda *_: self.stop())

    async def run_forever(self) -> None:
        """Poll until stopped, waiting for the current task before returning."""

        await self.recover_interrupted_tasks()
        while not self._stop_requested.is_set():
            processed = await self.run_once()
            if processed:
                continue
            try:
                await asyncio.wait_for(
                    self._stop_requested.wait(),
                    timeout=self.poll_seconds,
                )
            except asyncio.TimeoutError:
                pass

    async def recover_interrupted_tasks(self) -> dict[str, int]:
        """Recover expired leases and make persisted retry waits claimable."""

        counts = await self.repository.recover_expired_leases()
        cursor = self.repository.tasks.find(
            {"status": DomainTaskStatus.RETRY_WAIT.value}
        )
        waiting = await cursor.to_list(length=None)
        requeued = 0
        for document in waiting:
            task = await self.repository.requeue_retry(
                task_id=document["task_id"],
            )
            if task is not None:
                requeued += 1
        return {**counts, "requeued": requeued}

    async def run_once(self) -> bool:
        """Claim and execute at most one task, returning whether one was claimed."""

        if self._stop_requested.is_set():
            return False
        task = await self.repository.claim_next(
            worker_id=self.worker_id,
            lease_seconds=self.lease_seconds,
        )
        if task is None:
            return False

        cancellation_requested = asyncio.Event()
        lease_lost = asyncio.Event()
        handler_complete = asyncio.Event()
        heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(
                task,
                handler_complete,
                cancellation_requested,
                lease_lost,
            )
        )
        try:
            await self._execute_claimed(
                task,
                cancellation_requested,
                lease_lost,
            )
        finally:
            handler_complete.set()
            with suppress(asyncio.CancelledError):
                await heartbeat_task
        return True

    async def _execute_claimed(
        self,
        task: DomainTask,
        cancellation_requested: asyncio.Event,
        lease_lost: asyncio.Event,
    ) -> None:
        last_progress = task.progress
        progress_lock = asyncio.Lock()

        async def refresh_status() -> bool:
            if lease_lost.is_set():
                raise LeaseOwnershipError("worker lease was lost")
            refreshed = await self.repository.heartbeat(
                task_id=task.task_id,
                worker_id=self.worker_id,
                lease_seconds=self.lease_seconds,
            )
            if refreshed is None:
                lease_lost.set()
                raise LeaseOwnershipError("worker lease was lost")
            if refreshed.status == DomainTaskStatus.CANCELLING:
                cancellation_requested.set()
            return cancellation_requested.is_set()

        async def is_cancelled() -> bool:
            if cancellation_requested.is_set():
                return True
            return await refresh_status()

        async def report_progress(
            progress: float,
            stage: str,
            message: Optional[str] = None,
        ) -> None:
            nonlocal last_progress
            if await is_cancelled():
                raise TaskCancellationRequested("task cancellation was requested")
            if (
                isinstance(progress, bool)
                or not isinstance(progress, (int, float))
                or not math.isfinite(progress)
                or not 0.0 <= progress <= 1.0
            ):
                raise ValueError("progress must be a finite number between 0 and 1")
            if not isinstance(stage, str) or not stage.strip():
                raise ValueError("stage must be a non-empty string")
            async with progress_lock:
                if progress < last_progress:
                    raise ValueError("progress must be monotonic")
                await self.repository.update_progress(
                    task_id=task.task_id,
                    worker_id=self.worker_id,
                    progress=float(progress),
                    stage=stage,
                    message=message,
                )
                last_progress = float(progress)

        async def persist_failure(error: TaskExecutionError) -> None:
            try:
                if await refresh_status():
                    await self.repository.acknowledge_cancel(
                        task_id=task.task_id,
                        worker_id=self.worker_id,
                    )
                    return
                await self._record_failure(task, error)
            except LeaseOwnershipError:
                if not await self._acknowledge_cancel_race(task):
                    logger.warning("Lease lost for task %s", task.task_id)

        try:
            handler = self.registry.resolve(task.task_type)
            result_ref = await handler(
                task.payload,
                DomainTaskContext.from_task(task),
                report_progress,
                is_cancelled,
            )
            if await is_cancelled():
                await self.repository.acknowledge_cancel(
                    task_id=task.task_id,
                    worker_id=self.worker_id,
                )
                return
            normalized_ref = (
                DomainTaskResultRef.model_validate(result_ref)
                if result_ref is not None
                else None
            )
            await self.repository.mark_succeeded(
                task_id=task.task_id,
                worker_id=self.worker_id,
                result_ref=normalized_ref,
            )
        except TaskCancellationRequested:
            if cancellation_requested.is_set():
                await self.repository.acknowledge_cancel(
                    task_id=task.task_id,
                    worker_id=self.worker_id,
                )
                return
            await persist_failure(
                TerminalTaskError(
                    "handler raised cancellation without a persisted request",
                    code="TASK_INVALID_CANCELLATION_SIGNAL",
                ),
            )
        except LeaseOwnershipError:
            if not await self._acknowledge_cancel_race(task):
                logger.warning("Lease lost for task %s", task.task_id)
        except TaskExecutionError as exc:
            await persist_failure(exc)
        except Exception as exc:
            logger.error(
                "Unhandled handler failure for task %s (type=%s)",
                task.task_id,
                type(exc).__name__,
            )
            await persist_failure(
                TerminalTaskError(
                    "Task handler failed",
                    code="TASK_UNHANDLED_HANDLER_ERROR",
                    details={"exception_type": type(exc).__name__},
                ),
            )

    async def _record_failure(
        self,
        task: DomainTask,
        error: TaskExecutionError,
    ) -> None:
        failed = await self.repository.fail_attempt(
            task_id=task.task_id,
            worker_id=self.worker_id,
            code=error.error_code,
            message=str(error),
            retryable=error.retryable,
            details=error.details,
        )
        if failed.status == DomainTaskStatus.RETRY_WAIT:
            await self.repository.requeue_retry(task_id=task.task_id)

    async def _acknowledge_cancel_race(self, task: DomainTask) -> bool:
        """Finish cancellation that won a race with success/failure persistence."""

        refreshed = await self.repository.heartbeat(
            task_id=task.task_id,
            worker_id=self.worker_id,
            lease_seconds=self.lease_seconds,
        )
        if (
            refreshed is None
            or refreshed.status != DomainTaskStatus.CANCELLING
        ):
            return False
        await self.repository.acknowledge_cancel(
            task_id=task.task_id,
            worker_id=self.worker_id,
        )
        return True

    async def _heartbeat_loop(
        self,
        task: DomainTask,
        handler_complete: asyncio.Event,
        cancellation_requested: asyncio.Event,
        lease_lost: asyncio.Event,
    ) -> None:
        while not handler_complete.is_set():
            try:
                await asyncio.wait_for(
                    handler_complete.wait(),
                    timeout=self.heartbeat_seconds,
                )
                return
            except asyncio.TimeoutError:
                refreshed = await self.repository.heartbeat(
                    task_id=task.task_id,
                    worker_id=self.worker_id,
                    lease_seconds=self.lease_seconds,
                )
                if refreshed is None:
                    lease_lost.set()
                    return
                if refreshed.status == DomainTaskStatus.CANCELLING:
                    cancellation_requested.set()


async def run_worker() -> None:
    """Standalone process entry point. J04 intentionally registers no handlers."""

    from app.core.database import close_db, get_mongo_db, init_db

    await init_db()
    worker = DomainTaskWorker(
        DomainTaskRepository(get_mongo_db()),
        domain_task_handler_registry,
    )
    worker.install_signal_handlers()
    try:
        await worker.run_forever()
    finally:
        await close_db()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker())
