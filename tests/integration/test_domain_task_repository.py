import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.models.domain_task import DomainTaskStatus
from app.repositories.domain_task_repository import DomainTaskRepository
from app.services.domain_tasks import (
    IdempotencyConflictError,
    LeaseOwnershipError,
    TaskNotCancellableError,
)
from tests.unit.domain_tasks.fakes import FakeDatabase

pytestmark = pytest.mark.asyncio

BASE_TIME = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


async def make_repository():
    repository = DomainTaskRepository(FakeDatabase())
    await repository.ensure_indexes()
    return repository


async def test_creates_every_required_index():
    repository = await make_repository()
    task_names = {options["name"] for _, options in repository.tasks.indexes}
    event_names = {options["name"] for _, options in repository.events.indexes}

    assert task_names == {
        "uq_domain_tasks_task_id",
        "uq_domain_tasks_idempotency",
        "ix_domain_tasks_claim",
        "ix_domain_tasks_owner_created",
        "ix_domain_tasks_expired_lease",
    }
    assert event_names == {
        "uq_domain_task_events_event_id",
        "ix_domain_task_events_page",
    }
    idempotency_index = next(
        (keys, options)
        for keys, options in repository.tasks.indexes
        if options["name"] == "uq_domain_tasks_idempotency"
    )
    assert idempotency_index[0] == [
        ("user_id", 1),
        ("task_type", 1),
        ("idempotency_key", 1),
    ]
    assert idempotency_index[1]["unique"] is True
    assert idempotency_index[1]["partialFilterExpression"] == {
        "idempotency_key": {"$exists": True, "$type": "string"}
    }


async def test_idempotency_same_request_and_conflicting_request():
    repository = await make_repository()
    first = await repository.create_task(
        user_id="user-a",
        task_type="backtest",
        payload={"symbol": "600519", "days": 20},
        idempotency_key="same-key",
        now=BASE_TIME,
    )
    same = await repository.create_task(
        user_id="user-a",
        task_type="backtest",
        payload={"days": 20, "symbol": "600519"},
        idempotency_key="same-key",
        now=BASE_TIME + timedelta(seconds=1),
    )
    assert same.task_id == first.task_id

    with pytest.raises(IdempotencyConflictError):
        await repository.create_task(
            user_id="user-a",
            task_type="backtest",
            payload={"symbol": "600519", "days": 21},
            idempotency_key="same-key",
        )

    other_user = await repository.create_task(
        user_id="user-b",
        task_type="backtest",
        payload={"symbol": "600519", "days": 21},
        idempotency_key="same-key",
    )
    assert other_user.task_id != first.task_id


async def test_concurrent_idempotent_creation_returns_one_task():
    repository = await make_repository()

    results = await asyncio.gather(
        *[
            repository.create_task(
                user_id="user-a",
                task_type="backtest",
                payload={"symbol": "600519"},
                idempotency_key="race-key",
                now=BASE_TIME,
            )
            for _ in range(2)
        ]
    )

    assert results[0].task_id == results[1].task_id
    assert len(repository.tasks.documents) == 1
    assert len(repository.events.documents) == 1


async def test_two_workers_cannot_claim_the_same_task():
    repository = await make_repository()
    task = await repository.create_task(
        user_id="user-a",
        task_type="factor_compute",
        payload={},
        now=BASE_TIME,
    )

    claims = await asyncio.gather(
        repository.claim_next(
            worker_id="worker-1",
            lease_seconds=30,
            now=BASE_TIME + timedelta(seconds=1),
        ),
        repository.claim_next(
            worker_id="worker-2",
            lease_seconds=30,
            now=BASE_TIME + timedelta(seconds=1),
        ),
    )

    claimed = [item for item in claims if item is not None]
    assert len(claimed) == 1
    assert claimed[0].task_id == task.task_id
    assert claimed[0].attempt == 1


async def test_claim_orders_by_priority_then_creation_time():
    repository = await make_repository()
    normal = await repository.create_task(
        user_id="user-a",
        task_type="backtest",
        payload={"order": 1},
        priority=0,
        now=BASE_TIME,
    )
    urgent = await repository.create_task(
        user_id="user-a",
        task_type="backtest",
        payload={"order": 2},
        priority=20,
        now=BASE_TIME + timedelta(seconds=1),
    )
    claimed_urgent = await repository.claim_next(
        worker_id="worker",
        lease_seconds=30,
        now=BASE_TIME + timedelta(seconds=2),
    )
    claimed_normal = await repository.claim_next(
        worker_id="worker",
        lease_seconds=30,
        now=BASE_TIME + timedelta(seconds=3),
    )
    assert claimed_urgent.task_id == urgent.task_id
    assert claimed_normal.task_id == normal.task_id


async def test_lease_requires_matching_worker_and_must_not_be_expired():
    repository = await make_repository()
    task = await repository.create_task(
        user_id="user-a",
        task_type="strategy_run",
        payload={},
        now=BASE_TIME,
    )
    claimed = await repository.claim_next(
        worker_id="owner",
        lease_seconds=10,
        now=BASE_TIME,
    )
    assert claimed.task_id == task.task_id
    assert (
        await repository.heartbeat(
            task_id=task.task_id,
            worker_id="other",
            lease_seconds=10,
            now=BASE_TIME + timedelta(seconds=1),
        )
        is None
    )
    renewed = await repository.heartbeat(
        task_id=task.task_id,
        worker_id="owner",
        lease_seconds=10,
        now=BASE_TIME + timedelta(seconds=1),
    )
    assert renewed.lease_expires_at == BASE_TIME + timedelta(seconds=11)
    assert (
        await repository.heartbeat(
            task_id=task.task_id,
            worker_id="owner",
            lease_seconds=10,
            now=BASE_TIME + timedelta(seconds=12),
        )
        is None
    )
    with pytest.raises(LeaseOwnershipError):
        await repository.update_progress(
            task_id=task.task_id,
            worker_id="other",
            progress=0.5,
            stage="compute",
            now=BASE_TIME + timedelta(seconds=2),
        )
    with pytest.raises(ValueError, match="progress"):
        await repository.update_progress(
            task_id=task.task_id,
            worker_id="owner",
            progress=1.5,
            stage="compute",
            now=BASE_TIME + timedelta(seconds=2),
        )
    persisted = await repository.get_task(task.task_id, "user-a")
    assert persisted.progress == 0.0


async def test_retry_exhaustion_and_sensitive_error_redaction():
    repository = await make_repository()
    task = await repository.create_task(
        user_id="user-a",
        task_type="backtest",
        payload={},
        max_attempts=2,
        now=BASE_TIME,
    )
    first_claim = await repository.claim_next(
        worker_id="worker",
        lease_seconds=30,
        now=BASE_TIME,
    )
    assert first_claim.started_at == BASE_TIME
    waiting = await repository.fail_attempt(
        task_id=task.task_id,
        worker_id="worker",
        code="TEMPORARY",
        message="retry",
        retryable=True,
        details={"token": "secret"},
        now=BASE_TIME + timedelta(seconds=1),
    )
    assert waiting.status == DomainTaskStatus.RETRY_WAIT
    assert waiting.error.details["token"] == "[REDACTED]"

    await repository.requeue_retry(
        task_id=task.task_id,
        now=BASE_TIME + timedelta(seconds=2),
    )
    second_claim = await repository.claim_next(
        worker_id="worker",
        lease_seconds=30,
        now=BASE_TIME + timedelta(seconds=3),
    )
    assert second_claim.started_at == BASE_TIME
    failed = await repository.fail_attempt(
        task_id=task.task_id,
        worker_id="worker",
        code="TEMPORARY",
        message="exhausted",
        retryable=True,
        now=BASE_TIME + timedelta(seconds=4),
    )
    assert failed.status == DomainTaskStatus.FAILED
    assert failed.finished_at == BASE_TIME + timedelta(seconds=4)
    assert failed.error.retryable is False


async def test_success_requires_active_worker_lease_and_stores_reference_only():
    repository = await make_repository()
    task = await repository.create_task(
        user_id="user-a",
        task_type="factor_compute",
        payload={},
        now=BASE_TIME,
    )
    await repository.claim_next(
        worker_id="worker",
        lease_seconds=30,
        now=BASE_TIME,
    )
    with pytest.raises(LeaseOwnershipError):
        await repository.mark_succeeded(
            task_id=task.task_id,
            worker_id="other",
            now=BASE_TIME + timedelta(seconds=1),
        )
    succeeded = await repository.mark_succeeded(
        task_id=task.task_id,
        worker_id="worker",
        result_ref={"collection": "factor_snapshots", "id": "result-1"},
        now=BASE_TIME + timedelta(seconds=1),
    )
    assert succeeded.status == DomainTaskStatus.SUCCEEDED
    assert succeeded.result_ref.collection == "factor_snapshots"
    assert succeeded.result_ref.id == "result-1"
    assert succeeded.worker_id is None


async def test_expired_leases_recover_to_retry_wait_then_failed():
    repository = await make_repository()
    task = await repository.create_task(
        user_id="user-a",
        task_type="alert_eval",
        payload={},
        max_attempts=2,
        now=BASE_TIME,
    )
    await repository.claim_next(
        worker_id="worker-1",
        lease_seconds=5,
        now=BASE_TIME,
    )
    first = await repository.recover_expired_leases(
        now=BASE_TIME + timedelta(seconds=6)
    )
    assert first == {"retry_wait": 1, "failed": 0}
    await repository.requeue_retry(
        task_id=task.task_id,
        now=BASE_TIME + timedelta(seconds=7),
    )
    await repository.claim_next(
        worker_id="worker-2",
        lease_seconds=5,
        now=BASE_TIME + timedelta(seconds=8),
    )
    second = await repository.recover_expired_leases(
        now=BASE_TIME + timedelta(seconds=14)
    )
    assert second == {"retry_wait": 0, "failed": 1}
    final = await repository.get_task(task.task_id, "user-a")
    assert final.status == DomainTaskStatus.FAILED
    assert final.error.code == "TASK_RETRY_EXHAUSTED"


async def test_retry_wait_can_transition_directly_to_failed():
    repository = await make_repository()
    task = await repository.create_task(
        user_id="user-a",
        task_type="backtest",
        payload={},
        max_attempts=2,
        now=BASE_TIME,
    )
    await repository.claim_next(
        worker_id="worker",
        lease_seconds=30,
        now=BASE_TIME,
    )
    waiting = await repository.fail_attempt(
        task_id=task.task_id,
        worker_id="worker",
        code="TEMPORARY",
        message="retry later",
        retryable=True,
        now=BASE_TIME + timedelta(seconds=1),
    )
    assert waiting.status == DomainTaskStatus.RETRY_WAIT

    failed = await repository.fail_retry_wait(
        task_id=task.task_id,
        details={"authorization": "secret"},
        now=BASE_TIME + timedelta(seconds=2),
    )
    assert failed.status == DomainTaskStatus.FAILED
    assert failed.error.retryable is False
    assert failed.error.details["authorization"] == "[REDACTED]"


async def test_queued_and_running_cancellation_paths():
    repository = await make_repository()
    queued = await repository.create_task(
        user_id="user-a",
        task_type="campaign_eval",
        payload={},
        now=BASE_TIME,
    )
    assert (
        await repository.request_cancel(
            task_id=queued.task_id,
            user_id="user-b",
            now=BASE_TIME + timedelta(milliseconds=500),
        )
        is None
    )
    cancelled = await repository.request_cancel(
        task_id=queued.task_id,
        user_id="user-a",
        now=BASE_TIME + timedelta(seconds=1),
    )
    assert cancelled.status == DomainTaskStatus.CANCELLED

    running = await repository.create_task(
        user_id="user-a",
        task_type="attribution",
        payload={},
        now=BASE_TIME + timedelta(seconds=2),
    )
    await repository.claim_next(
        worker_id="worker",
        lease_seconds=30,
        now=BASE_TIME + timedelta(seconds=3),
    )
    cancelling = await repository.request_cancel(
        task_id=running.task_id,
        user_id="user-a",
        now=BASE_TIME + timedelta(seconds=4),
    )
    assert cancelling.status == DomainTaskStatus.CANCELLING
    with pytest.raises(LeaseOwnershipError):
        await repository.acknowledge_cancel(
            task_id=running.task_id,
            worker_id="other",
            now=BASE_TIME + timedelta(seconds=5),
        )
    completed = await repository.acknowledge_cancel(
        task_id=running.task_id,
        worker_id="worker",
        now=BASE_TIME + timedelta(seconds=5),
    )
    assert completed.status == DomainTaskStatus.CANCELLED

    with pytest.raises(TaskNotCancellableError):
        await repository.request_cancel(
            task_id=running.task_id,
            user_id="user-a",
            now=BASE_TIME + timedelta(seconds=6),
        )


async def test_cross_user_reads_and_event_pagination_are_isolated():
    repository = await make_repository()
    task = await repository.create_task(
        user_id="user-a",
        task_type="factor_compute",
        payload={},
        now=BASE_TIME,
    )
    await repository.claim_next(
        worker_id="worker",
        lease_seconds=30,
        now=BASE_TIME + timedelta(seconds=1),
    )
    await repository.update_progress(
        task_id=task.task_id,
        worker_id="worker",
        progress=0.5,
        stage="compute",
        now=BASE_TIME + timedelta(seconds=2),
    )

    assert await repository.get_task(task.task_id, "user-b") is None
    assert await repository.list_tasks(user_id="user-b") == []
    assert (
        await repository.list_events(
            task_id=task.task_id,
            user_id="user-b",
        )
        == []
    )
    page_one = await repository.list_events(
        task_id=task.task_id,
        user_id="user-a",
        page=1,
        page_size=2,
    )
    page_two = await repository.list_events(
        task_id=task.task_id,
        user_id="user-a",
        page=2,
        page_size=2,
    )
    assert [event.event_type for event in page_one] == ["created", "claimed"]
    assert [event.event_type for event in page_two] == ["progress"]
