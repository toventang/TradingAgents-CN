"""The single legal state machine for every persistent domain task."""

from types import MappingProxyType

from app.models.domain_task import DomainTaskStatus
from app.services.domain_tasks.errors import InvalidTaskTransitionError


LEGAL_TRANSITIONS = MappingProxyType(
    {
        DomainTaskStatus.QUEUED: frozenset(
            {DomainTaskStatus.RUNNING, DomainTaskStatus.CANCELLED}
        ),
        DomainTaskStatus.RUNNING: frozenset(
            {
                DomainTaskStatus.SUCCEEDED,
                DomainTaskStatus.CANCELLING,
                DomainTaskStatus.RETRY_WAIT,
                DomainTaskStatus.FAILED,
            }
        ),
        DomainTaskStatus.CANCELLING: frozenset(
            {DomainTaskStatus.CANCELLED}
        ),
        DomainTaskStatus.RETRY_WAIT: frozenset(
            {DomainTaskStatus.QUEUED, DomainTaskStatus.FAILED}
        ),
        DomainTaskStatus.SUCCEEDED: frozenset(),
        DomainTaskStatus.CANCELLED: frozenset(),
        DomainTaskStatus.FAILED: frozenset(),
    }
)


def can_transition(
    current: DomainTaskStatus | str,
    target: DomainTaskStatus | str,
) -> bool:
    current_status = DomainTaskStatus(current)
    target_status = DomainTaskStatus(target)
    return target_status in LEGAL_TRANSITIONS[current_status]


def require_transition(
    current: DomainTaskStatus | str,
    target: DomainTaskStatus | str,
) -> None:
    current_status = DomainTaskStatus(current)
    target_status = DomainTaskStatus(target)
    if not can_transition(current_status, target_status):
        raise InvalidTaskTransitionError(
            "illegal domain-task transition: "
            f"{current_status.value} -> {target_status.value}"
        )
