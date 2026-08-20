import pytest
import asyncio
from app.models.domain_task import TaskType, TaskStatus
from app.repositories.domain_task_repository import DomainTaskRepository
from app.services.domain_tasks.handler_registry import (
    TaskHandlerRegistry,
    TaskContext,
    UnknownTaskHandlerError
)
from app.workers.domain_worker import DomainWorker, NonRetryableTaskError
from tests.integration.test_domain_task_repository import FakeDatabase


class SampleFactorHandler:
    async def execute(self, payload, context, progress, is_cancelled):
        await progress(0.5, "computing", "Halfway calculated")
        if is_cancelled():
            return {}
        return {"factor_values": [1.2, 3.4]}


class RetryableFailureHandler:
    async def execute(self, payload, context, progress, is_cancelled):
        raise ValueError("Network timeout")


class NonRetryableFailureHandler:
    async def execute(self, payload, context, progress, is_cancelled):
        raise NonRetryableTaskError("Invalid input parameters")


def create_worker():
    db = FakeDatabase()
    repo = DomainTaskRepository(db)
    registry = TaskHandlerRegistry()
    registry.register(TaskType.FACTOR_COMPUTE, SampleFactorHandler())
    registry.register("retryable_type", RetryableFailureHandler())
    registry.register("non_retryable_type", NonRetryableFailureHandler())

    worker = DomainWorker(
        repository=repo,
        registry=registry,
        worker_id="test_worker_1",
        lease_seconds=30
    )
    return repo, registry, worker


@pytest.mark.asyncio
async def test_worker_successful_task_execution():
    repo, registry, worker = create_worker()

    task = await repo.create_task(
        user_id="user_a",
        task_type=TaskType.FACTOR_COMPUTE,
        payload={"symbols": ["000001"]}
    )

    processed = await worker.process_one_task()
    assert processed is True

    fetched = await repo.get_task(task.task_id, user_id="user_a")
    assert fetched.status == TaskStatus.SUCCEEDED
    assert fetched.progress == 1.0
    assert fetched.result_ref == {"factor_values": [1.2, 3.4]}


@pytest.mark.asyncio
async def test_worker_unknown_handler_terminal_failure():
    repo, registry, worker = create_worker()

    task = await repo.create_task(
        user_id="user_a",
        task_type=TaskType.STRATEGY_RUN,
        payload={}
    )

    processed = await worker.process_one_task()
    assert processed is True

    fetched = await repo.get_task(task.task_id, user_id="user_a")
    assert fetched.status == TaskStatus.FAILED
    assert fetched.error["code"] == "UNKNOWN_TASK_HANDLER"


@pytest.mark.asyncio
async def test_worker_retryable_vs_non_retryable_failures():
    # Retryable test
    repo1, registry1, worker1 = create_worker()
    task_retry = await repo1.create_task(
        user_id="user_a",
        task_type="retryable_type",
        payload={},
        max_attempts=3
    )
    await worker1.process_one_task()
    fetched_retry = await repo1.get_task(task_retry.task_id, user_id="user_a")
    assert fetched_retry.status == TaskStatus.RETRY_WAIT

    # Non-retryable test
    repo2, registry2, worker2 = create_worker()
    task_fatal = await repo2.create_task(
        user_id="user_a",
        task_type="non_retryable_type",
        payload={},
        max_attempts=3
    )
    await worker2.process_one_task()
    fetched_fatal = await repo2.get_task(task_fatal.task_id, user_id="user_a")
    assert fetched_fatal.status == TaskStatus.FAILED
