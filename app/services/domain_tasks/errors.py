"""Typed domain-task failures for repositories, workers, and APIs."""

from typing import Any, Optional


class DomainTaskErrorBase(RuntimeError):
    code = "DOMAIN_TASK_ERROR"


class InvalidTaskTransitionError(DomainTaskErrorBase):
    code = "TASK_INVALID_TRANSITION"


class IdempotencyConflictError(DomainTaskErrorBase):
    code = "TASK_IDEMPOTENCY_CONFLICT"


class LeaseOwnershipError(DomainTaskErrorBase):
    code = "TASK_LEASE_NOT_OWNED"


class TaskNotCancellableError(DomainTaskErrorBase):
    code = "TASK_NOT_CANCELLABLE"


class TaskExecutionError(DomainTaskErrorBase):
    """A safe, explicitly classified failure raised by a task handler."""

    retryable = False

    def __init__(
        self,
        message: str,
        *,
        code: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.error_code = code or self.code
        self.details = details or {}


class RetryableTaskError(TaskExecutionError):
    code = "TASK_RETRYABLE_FAILURE"
    retryable = True


class TerminalTaskError(TaskExecutionError):
    code = "TASK_TERMINAL_FAILURE"


class UnknownTaskHandlerError(TerminalTaskError):
    code = "TASK_HANDLER_NOT_REGISTERED"


class TaskCancellationRequested(DomainTaskErrorBase):
    """Cooperative control-flow signal raised after a cancellation check."""

    code = "TASK_CANCELLATION_REQUESTED"
