"""Domain-task state machine and deterministic request hashing."""

from app.services.domain_tasks.errors import (
    DomainTaskErrorBase,
    IdempotencyConflictError,
    InvalidTaskTransitionError,
    LeaseOwnershipError,
    TaskNotCancellableError,
)
from app.services.domain_tasks.hashing import canonical_request_hash
from app.services.domain_tasks.state_machine import (
    LEGAL_TRANSITIONS,
    can_transition,
    require_transition,
)

__all__ = [
    "DomainTaskErrorBase",
    "IdempotencyConflictError",
    "InvalidTaskTransitionError",
    "LEGAL_TRANSITIONS",
    "LeaseOwnershipError",
    "TaskNotCancellableError",
    "can_transition",
    "canonical_request_hash",
    "require_transition",
]
