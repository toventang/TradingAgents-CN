"""Domain-task state machine and deterministic request hashing."""

from app.services.domain_tasks.errors import (
    DomainTaskErrorBase,
    IdempotencyConflictError,
    InvalidTaskTransitionError,
    LeaseOwnershipError,
    RetryableTaskError,
    TaskCancellationRequested,
    TaskExecutionError,
    TaskNotCancellableError,
    TerminalTaskError,
    UnknownTaskHandlerError,
)
from app.services.domain_tasks.handlers import (
    CancellationChecker,
    DomainTaskContext,
    DomainTaskHandler,
    DomainTaskHandlerRegistry,
    ProgressCallback,
    domain_task_handler_registry,
)
from app.services.domain_tasks.hashing import canonical_request_hash
from app.services.domain_tasks.state_machine import (
    LEGAL_TRANSITIONS,
    can_transition,
    require_transition,
)

__all__ = [
    "DomainTaskErrorBase",
    "DomainTaskContext",
    "DomainTaskHandler",
    "DomainTaskHandlerRegistry",
    "IdempotencyConflictError",
    "InvalidTaskTransitionError",
    "LEGAL_TRANSITIONS",
    "LeaseOwnershipError",
    "ProgressCallback",
    "CancellationChecker",
    "RetryableTaskError",
    "TaskCancellationRequested",
    "TaskExecutionError",
    "TaskNotCancellableError",
    "TerminalTaskError",
    "UnknownTaskHandlerError",
    "can_transition",
    "canonical_request_hash",
    "domain_task_handler_registry",
    "require_transition",
]
