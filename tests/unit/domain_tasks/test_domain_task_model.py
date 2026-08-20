import pytest
from app.models.domain_task import (
    DomainTask,
    TaskStatus,
    TaskType,
    validate_task_transition,
    InvalidTaskTransitionError
)

def test_legal_task_transitions():
    assert validate_task_transition(TaskStatus.QUEUED, TaskStatus.RUNNING)
    assert validate_task_transition(TaskStatus.RUNNING, TaskStatus.SUCCEEDED)
    assert validate_task_transition(TaskStatus.RUNNING, TaskStatus.CANCELLING)
    assert validate_task_transition(TaskStatus.CANCELLING, TaskStatus.CANCELLED)
    assert validate_task_transition(TaskStatus.RUNNING, TaskStatus.RETRY_WAIT)
    assert validate_task_transition(TaskStatus.RETRY_WAIT, TaskStatus.QUEUED)

def test_illegal_task_transitions():
    with pytest.raises(InvalidTaskTransitionError):
        validate_task_transition(TaskStatus.QUEUED, TaskStatus.SUCCEEDED)
    with pytest.raises(InvalidTaskTransitionError):
        validate_task_transition(TaskStatus.SUCCEEDED, TaskStatus.RUNNING)
    with pytest.raises(InvalidTaskTransitionError):
        validate_task_transition(TaskStatus.CANCELLED, TaskStatus.RUNNING)

def test_domain_task_model_defaults():
    task = DomainTask(
        task_id="task_1",
        user_id="user_a",
        task_type=TaskType.FACTOR_COMPUTE,
        payload={"symbols": ["000001"]}
    )
    assert task.status == TaskStatus.QUEUED
    assert task.progress == 0.0
    assert task.attempt == 0
    assert task.max_attempts == 3
