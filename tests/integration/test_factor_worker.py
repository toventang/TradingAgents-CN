from __future__ import annotations

import pytest

from app.models.domain_task import DomainTaskType
from app.repositories.factor_repository import FactorRepository
from app.services.domain_tasks import (
    DomainTaskContext,
    DomainTaskHandlerRegistry,
    RetryableTaskError,
    TaskCancellationRequested,
    TerminalTaskError,
)
from app.services.factors.engine import FactorEngine, InlineChunkExecutor
from app.workers.handlers.factor_compute import register_factor_compute_handler
from tests.factor_fakes import FakeDatabase
from tests.unit.factors.test_engine import (
    _false,
    _report,
    calculate_rows,
    load_members,
    make_request,
)


def context(task_id="task-worker"):
    return DomainTaskContext(
        task_id=task_id,
        user_id="user-a",
        task_type=DomainTaskType.FACTOR_COMPUTE,
        attempt=1,
        max_attempts=3,
    )


def engine(repository, calculator=calculate_rows):
    return FactorEngine(
        repository=repository,
        loader=load_members,
        calculator=calculator,
        executor=InlineChunkExecutor(),
    )


@pytest.mark.asyncio
async def test_registered_worker_handler_publishes_result_and_deduplicates_request():
    repository = FactorRepository(db=FakeDatabase())
    registry = DomainTaskHandlerRegistry()
    handler = register_factor_compute_handler(engine(repository), registry=registry)
    assert registry.resolve(DomainTaskType.FACTOR_COMPUTE) is handler
    payload = make_request(2).model_dump(mode="json")
    result = await handler(payload, context("task-1"), _report, _false)
    duplicate = await handler(payload, context("task-2"), _report, _false)
    assert result.collection == "factor_snapshots"
    assert duplicate.id == result.id


@pytest.mark.asyncio
async def test_worker_classifies_invalid_payload_cancellation_and_chunk_failure():
    repository = FactorRepository(db=FakeDatabase())
    handler = register_factor_compute_handler(
        engine(repository), registry=DomainTaskHandlerRegistry()
    )
    with pytest.raises(TerminalTaskError) as invalid:
        await handler({}, context(), _report, _false)
    assert invalid.value.error_code == "FACTOR_REQUEST_INVALID"

    async def cancelled():
        return True

    with pytest.raises(TaskCancellationRequested):
        await handler(
            make_request(1).model_dump(mode="json"), context("task-cancel"), _report, cancelled
        )

    def broken(data, plan, request, members, snapshot_id):
        del data, plan, request, members, snapshot_id
        raise RuntimeError("fixture compute failure")

    failing = register_factor_compute_handler(
        engine(FactorRepository(db=FakeDatabase()), calculator=broken),
        registry=DomainTaskHandlerRegistry(),
    )
    with pytest.raises(RetryableTaskError) as failure:
        await failing(
            make_request(1).model_dump(mode="json"), context("task-fail"), _report, _false
        )
    assert failure.value.error_code == "FACTOR_COMPUTE_RETRYABLE"
