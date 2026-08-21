from itertools import product

import pytest
from pydantic import ValidationError

from app.models.domain_task import (
    DomainTask,
    DomainTaskStatus,
    DomainTaskType,
)
from app.services.domain_tasks import (
    LEGAL_TRANSITIONS,
    InvalidTaskTransitionError,
    can_transition,
    canonical_request_hash,
    require_transition,
)


def test_every_legal_and_illegal_transition():
    for current, target in product(DomainTaskStatus, repeat=2):
        expected = target in LEGAL_TRANSITIONS[current]
        assert can_transition(current, target) is expected
        if expected:
            require_transition(current, target)
        else:
            with pytest.raises(InvalidTaskTransitionError):
                require_transition(current, target)


def test_terminal_states_have_no_outgoing_transitions():
    for status in (
        DomainTaskStatus.SUCCEEDED,
        DomainTaskStatus.CANCELLED,
        DomainTaskStatus.FAILED,
    ):
        assert LEGAL_TRANSITIONS[status] == frozenset()


def test_task_model_contains_complete_persistent_contract():
    task = DomainTask(
        user_id="user-a",
        task_type=DomainTaskType.BACKTEST,
        payload={"symbol": "600519"},
    )
    assert set(task.model_dump()) == {
        "task_id",
        "user_id",
        "task_type",
        "status",
        "priority",
        "payload",
        "progress",
        "stage",
        "message",
        "result_ref",
        "attempt",
        "max_attempts",
        "worker_id",
        "heartbeat_at",
        "lease_expires_at",
        "cancel_requested_at",
        "error",
        "created_at",
        "started_at",
        "finished_at",
        "updated_at",
        "idempotency_key",
        "request_hash",
    }
    assert task.created_at.utcoffset().total_seconds() == 0
    assert task.updated_at.utcoffset().total_seconds() == 0


def test_task_model_rejects_inconsistent_idempotency_and_terminal_time():
    with pytest.raises(ValidationError, match="request_hash"):
        DomainTask(
            user_id="user-a",
            task_type="backtest",
            payload={},
            idempotency_key="key",
        )
    with pytest.raises(ValidationError, match="finished_at"):
        DomainTask(
            user_id="user-a",
            task_type="backtest",
            payload={},
            status="failed",
        )
    with pytest.raises(ValidationError, match="UUID"):
        DomainTask(
            task_id="not-a-uuid",
            user_id="user-a",
            task_type="backtest",
            payload={},
        )


def test_request_hash_is_order_independent_and_request_sensitive():
    first = canonical_request_hash({"payload": {"b": 2, "a": 1}})
    reordered = canonical_request_hash({"payload": {"a": 1, "b": 2}})
    changed = canonical_request_hash({"payload": {"a": 1, "b": 3}})

    assert first == reordered
    assert first != changed
    assert len(first) == 64
