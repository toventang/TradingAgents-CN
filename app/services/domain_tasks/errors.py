"""Typed domain-task failures for repositories, workers, and future APIs."""


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
