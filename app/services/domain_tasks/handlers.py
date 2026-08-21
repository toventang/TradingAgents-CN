"""Explicit handler contracts and registry for durable domain tasks."""

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping, Optional, Protocol

from app.models.domain_task import DomainTask, DomainTaskResultRef, DomainTaskType
from app.services.domain_tasks.errors import UnknownTaskHandlerError

ProgressCallback = Callable[[float, str, Optional[str]], Awaitable[None]]
CancellationChecker = Callable[[], Awaitable[bool]]


@dataclass(frozen=True, slots=True)
class DomainTaskContext:
    """Immutable task identity exposed to handlers without persistence access."""

    task_id: str
    user_id: str
    task_type: DomainTaskType
    attempt: int
    max_attempts: int

    @classmethod
    def from_task(cls, task: DomainTask) -> "DomainTaskContext":
        return cls(
            task_id=task.task_id,
            user_id=task.user_id,
            task_type=task.task_type,
            attempt=task.attempt,
            max_attempts=task.max_attempts,
        )


class DomainTaskHandler(Protocol):
    """A handler receives only validated payload and controlled callbacks."""

    async def __call__(
        self,
        payload: Mapping[str, Any],
        context: DomainTaskContext,
        report_progress: ProgressCallback,
        is_cancelled: CancellationChecker,
    ) -> Optional[DomainTaskResultRef]: ...


class DomainTaskHandlerRegistry:
    """Closed, in-memory registry; task data can never select an import path."""

    def __init__(self) -> None:
        self._handlers: dict[DomainTaskType, DomainTaskHandler] = {}

    def register(
        self,
        task_type: DomainTaskType | str,
        handler: DomainTaskHandler,
    ) -> None:
        normalized = DomainTaskType(task_type)
        if normalized in self._handlers:
            raise ValueError(f"handler already registered for {normalized.value}")
        if not callable(handler):
            raise TypeError("handler must be callable")
        self._handlers[normalized] = handler

    def resolve(self, task_type: DomainTaskType | str) -> DomainTaskHandler:
        normalized = DomainTaskType(task_type)
        try:
            return self._handlers[normalized]
        except KeyError as exc:
            raise UnknownTaskHandlerError(
                f"No handler is registered for task type {normalized.value}",
                details={"task_type": normalized.value},
            ) from exc

    @property
    def task_types(self) -> tuple[DomainTaskType, ...]:
        return tuple(self._handlers)


# Deliberately empty in J04. Feature tasks explicitly register handlers later.
domain_task_handler_registry = DomainTaskHandlerRegistry()
