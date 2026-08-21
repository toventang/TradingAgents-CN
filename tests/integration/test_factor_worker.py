import pytest
from app.models.domain_task import TaskType, TaskStatus
from app.repositories.domain_task_repository import DomainTaskRepository
from app.repositories.factor_repository import FactorRepository
from app.workers.domain_worker import DomainWorker
from app.workers.handlers.factor_compute import FactorComputeHandler
from app.services.domain_tasks.handler_registry import global_handler_registry
from tests.integration.test_domain_task_repository import FakeDatabase

@pytest.mark.asyncio
async def test_factor_compute_worker_execution():
    db = FakeDatabase()
    task_repo = DomainTaskRepository(db=db)
    factor_repo = FactorRepository(db=db)

    handler = FactorComputeHandler(repo=factor_repo)
    global_handler_registry.register(TaskType.FACTOR_COMPUTE, handler)

    task = await task_repo.create_task(
        user_id="user_a",
        task_type=TaskType.FACTOR_COMPUTE,
        payload={
            "symbols": ["000001", "000002"],
            "market": "CN",
            "factor_ids": ["ret_1d", "sma_5"]
        }
    )

    worker = DomainWorker(
        repository=task_repo,
        registry=global_handler_registry,
        worker_id="factor_worker_1"
    )

    processed = await worker.process_one_task()
    assert processed is True

    fetched = await task_repo.get_task(task.task_id, user_id="user_a")
    assert fetched.status == TaskStatus.SUCCEEDED
    assert "snapshot_id" in fetched.result_ref
    assert fetched.result_ref["symbol_count"] == 2
