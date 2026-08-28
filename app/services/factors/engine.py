"""Bounded parallel orchestration for durable factor snapshot computation."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from typing import Any, Protocol

from app.models.factor import (
    FactorComputeRequest,
    FactorJobStatus,
    FactorSnapshot,
    FactorSnapshotStatus,
    FactorUniverseMember,
    FactorValueRow,
)
from app.repositories.factor_repository import FactorRepository
from app.services.domain_tasks import TaskCancellationRequested
from app.services.factors.dag import FactorDAGPlanner, FactorPlan
from app.services.factors.snapshot_service import FactorSnapshotService


class FactorComputationInProgress(RuntimeError):
    pass


class FactorChunkLoader(Protocol):
    async def __call__(
        self,
        request: FactorComputeRequest,
        members: tuple[FactorUniverseMember, ...],
        plan: FactorPlan,
    ) -> Any: ...


class FactorChunkCalculator(Protocol):
    def __call__(
        self,
        data: Any,
        plan: FactorPlan,
        request: FactorComputeRequest,
        members: tuple[FactorUniverseMember, ...],
        snapshot_id: str,
    ) -> Iterable[FactorValueRow | dict[str, Any]]: ...


class ChunkExecutor(Protocol):
    async def execute(
        self,
        calculator: FactorChunkCalculator,
        data: Any,
        plan: FactorPlan,
        request: FactorComputeRequest,
        members: tuple[FactorUniverseMember, ...],
        snapshot_id: str,
    ) -> tuple[FactorValueRow | dict[str, Any], ...]: ...


class InlineChunkExecutor:
    """Deterministic executor for tests and already-isolated worker processes."""

    async def execute(
        self,
        calculator: FactorChunkCalculator,
        data: Any,
        plan: FactorPlan,
        request: FactorComputeRequest,
        members: tuple[FactorUniverseMember, ...],
        snapshot_id: str,
    ) -> tuple[FactorValueRow | dict[str, Any], ...]:
        return tuple(calculator(data, plan, request, members, snapshot_id))


class ProcessPoolChunkExecutor:
    """Bounded process executor; caller controls its lifecycle per computation."""

    def __init__(self, max_workers: int):
        if not 1 <= max_workers <= 16:
            raise ValueError("process workers must be between 1 and 16")
        self._pool = ProcessPoolExecutor(max_workers=max_workers)

    async def execute(
        self,
        calculator: FactorChunkCalculator,
        data: Any,
        plan: FactorPlan,
        request: FactorComputeRequest,
        members: tuple[FactorUniverseMember, ...],
        snapshot_id: str,
    ) -> tuple[FactorValueRow | dict[str, Any], ...]:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            self._pool,
            _run_calculator,
            calculator,
            data,
            plan,
            request,
            members,
            snapshot_id,
        )
        return tuple(result)

    def close(self) -> None:
        self._pool.shutdown(wait=True, cancel_futures=True)


ProgressReporter = Callable[[float, str, str | None], Awaitable[None]]
CancellationChecker = Callable[[], Awaitable[bool]]


@dataclass(frozen=True, slots=True)
class FactorEngineResult:
    job_id: str
    snapshot: FactorSnapshot
    deduplicated: bool
    plan_checksum: str


class FactorEngine:
    def __init__(
        self,
        *,
        repository: FactorRepository,
        loader: FactorChunkLoader,
        calculator: FactorChunkCalculator,
        planner: FactorDAGPlanner | None = None,
        snapshot_service: FactorSnapshotService | None = None,
        executor: ChunkExecutor | None = None,
    ) -> None:
        self.repository = repository
        self.loader = loader
        self.calculator = calculator
        self.planner = planner or FactorDAGPlanner()
        self.snapshot_service = snapshot_service or FactorSnapshotService(repository)
        self.executor = executor

    async def compute(
        self,
        *,
        user_id: str,
        task_id: str,
        request: FactorComputeRequest,
        report_progress: ProgressReporter,
        is_cancelled: CancellationChecker,
    ) -> FactorEngineResult:
        plan = self.planner.plan(request)
        await self.repository.ensure_compute_indexes()
        job, created = await self.repository.create_or_get_job(
            user_id=user_id, task_id=task_id, request=request
        )
        if not created and job.status == FactorJobStatus.SUCCEEDED and job.snapshot_id:
            ready = await self.repository.get_snapshot(job.snapshot_id, user_id=user_id)
            if ready is not None and ready.status == FactorSnapshotStatus.READY:
                return FactorEngineResult(job.job_id, ready, True, plan.checksum)
        if (
            not created
            and job.status in {FactorJobStatus.QUEUED, FactorJobStatus.RUNNING}
            and job.task_id != task_id
        ):
            raise FactorComputationInProgress(
                f"identical factor request is already owned by task {job.task_id}"
            )

        job = await self.repository.mark_job_running(
            job.job_id, task_id, user_id=user_id
        )
        snapshot: FactorSnapshot | None = None
        tasks: list[asyncio.Task[Any]] = []
        executor: ChunkExecutor | None = None
        owned_executor = False
        try:
            snapshot = await self.snapshot_service.begin(
                user_id=user_id,
                task_id=task_id,
                job=job,
                request=request,
            )
            if snapshot.status == FactorSnapshotStatus.READY:
                await self.repository.mark_job_succeeded(
                    job.job_id,
                    snapshot.snapshot_id,
                    user_id=user_id,
                    completed_symbols=len(request.members),
                )
                return FactorEngineResult(job.job_id, snapshot, True, plan.checksum)
            if snapshot.status != FactorSnapshotStatus.BUILDING:
                raise ValueError(
                    f"factor snapshot cannot resume from {snapshot.status.value}; "
                    "create a request with a new semantic identity"
                )

            await report_progress(0.0, "factor_plan", "Factor DAG planned once")
            ordered_members = tuple(
                sorted(request.members, key=lambda item: (item.market.value, item.symbol))
            )
            chunks = tuple(_chunks(ordered_members, request.chunk_size))
            completed_symbols = 0
            progress_lock = asyncio.Lock()
            semaphore = asyncio.Semaphore(request.workers)
            owned_executor = self.executor is None
            executor = self.executor or ProcessPoolChunkExecutor(request.workers)

            async def process_chunk(
                chunk_index: int, members: tuple[FactorUniverseMember, ...]
            ) -> None:
                nonlocal completed_symbols
                assert snapshot is not None and executor is not None
                async with semaphore:
                    if await is_cancelled():
                        raise TaskCancellationRequested("factor computation was cancelled")
                    data = await self.loader(request, members, plan)
                    if await is_cancelled():
                        raise TaskCancellationRequested("factor computation was cancelled")
                    rows = await executor.execute(
                        self.calculator,
                        data,
                        plan,
                        request,
                        members,
                        snapshot.snapshot_id,
                    )
                    await self.snapshot_service.write_chunk(
                        user_id=user_id,
                        snapshot=snapshot,
                        request=request,
                        members=members,
                        chunk_id=f"{chunk_index:08d}",
                        rows=rows,
                    )
                    async with progress_lock:
                        completed_symbols += len(members)
                        await self.repository.update_job_progress(
                            job.job_id,
                            user_id=user_id,
                            completed_symbols=completed_symbols,
                        )
                        await report_progress(
                            completed_symbols / len(ordered_members),
                            "factor_compute",
                            f"Completed {completed_symbols}/{len(ordered_members)} symbols",
                        )

            tasks = [
                asyncio.create_task(process_chunk(index, members))
                for index, members in enumerate(chunks)
            ]
            await asyncio.gather(*tasks)
            if await is_cancelled():
                raise TaskCancellationRequested("factor computation was cancelled")
            published = await self.snapshot_service.publish(
                user_id=user_id, snapshot=snapshot, request=request
            )
            await self.repository.mark_job_succeeded(
                job.job_id,
                published.snapshot_id,
                user_id=user_id,
                completed_symbols=len(request.members),
            )
            await report_progress(1.0, "factor_publish", "Immutable snapshot published")
            return FactorEngineResult(job.job_id, published, not created, plan.checksum)
        except TaskCancellationRequested:
            await _cancel_tasks(tasks)
            if snapshot is not None:
                await self.snapshot_service.fail(
                    user_id=user_id,
                    snapshot_id=snapshot.snapshot_id,
                    code="FACTOR_COMPUTE_CANCELLED",
                    message="Factor computation was cancelled",
                )
            await self.repository.mark_job_failed(
                job.job_id,
                user_id=user_id,
                error={"code": "FACTOR_COMPUTE_CANCELLED"},
                cancelled=True,
            )
            raise
        except Exception as exc:
            await _cancel_tasks(tasks)
            if snapshot is not None:
                await self.snapshot_service.fail(
                    user_id=user_id,
                    snapshot_id=snapshot.snapshot_id,
                    code="FACTOR_CHUNK_FAILED",
                    message=str(exc),
                )
            await self.repository.mark_job_failed(
                job.job_id,
                user_id=user_id,
                error={"code": "FACTOR_CHUNK_FAILED", "type": type(exc).__name__},
            )
            raise
        finally:
            if owned_executor and isinstance(executor, ProcessPoolChunkExecutor):
                executor.close()


def _chunks(
    values: Sequence[FactorUniverseMember], size: int
) -> Iterable[tuple[FactorUniverseMember, ...]]:
    for start in range(0, len(values), size):
        yield tuple(values[start:start + size])


def _run_calculator(
    calculator: FactorChunkCalculator,
    data: Any,
    plan: FactorPlan,
    request: FactorComputeRequest,
    members: tuple[FactorUniverseMember, ...],
    snapshot_id: str,
) -> tuple[FactorValueRow | dict[str, Any], ...]:
    return tuple(calculator(data, plan, request, members, snapshot_id))


async def _cancel_tasks(tasks: Iterable[asyncio.Task[Any]]) -> None:
    pending = [task for task in tasks if not task.done()]
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
