"""MongoDB repository for durable, owner-scoped domain tasks."""

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.core.logging_context import redact_sensitive_mapping
from app.models.domain_task import (
    DomainTask,
    DomainTaskError,
    DomainTaskEvent,
    DomainTaskResultRef,
    DomainTaskStatus,
    DomainTaskType,
    utc_now,
)
from app.services.domain_tasks.errors import (
    IdempotencyConflictError,
    LeaseOwnershipError,
    TaskNotCancellableError,
)
from app.services.domain_tasks.hashing import canonical_request_hash
from app.services.domain_tasks.state_machine import require_transition


def _utc_timestamp(value: Optional[datetime]) -> datetime:
    timestamp = value or utc_now()
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


class DomainTaskRepository:
    TASKS_COLLECTION = "domain_tasks"
    EVENTS_COLLECTION = "domain_task_events"

    def __init__(self, database: Any):
        self.tasks = database[self.TASKS_COLLECTION]
        self.events = database[self.EVENTS_COLLECTION]

    async def ensure_indexes(self) -> None:
        await self.tasks.create_index(
            [("task_id", ASCENDING)],
            unique=True,
            name="uq_domain_tasks_task_id",
        )
        await self.tasks.create_index(
            [
                ("user_id", ASCENDING),
                ("task_type", ASCENDING),
                ("idempotency_key", ASCENDING),
            ],
            unique=True,
            partialFilterExpression={
                "idempotency_key": {"$exists": True, "$type": "string"}
            },
            name="uq_domain_tasks_idempotency",
        )
        await self.tasks.create_index(
            [
                ("status", ASCENDING),
                ("priority", DESCENDING),
                ("created_at", ASCENDING),
            ],
            name="ix_domain_tasks_claim",
        )
        await self.tasks.create_index(
            [("user_id", ASCENDING), ("created_at", DESCENDING)],
            name="ix_domain_tasks_owner_created",
        )
        await self.tasks.create_index(
            [("lease_expires_at", ASCENDING)],
            name="ix_domain_tasks_expired_lease",
        )
        await self.events.create_index(
            [("event_id", ASCENDING)],
            unique=True,
            name="uq_domain_task_events_event_id",
        )
        await self.events.create_index(
            [
                ("task_id", ASCENDING),
                ("user_id", ASCENDING),
                ("created_at", ASCENDING),
                ("event_id", ASCENDING),
            ],
            name="ix_domain_task_events_page",
        )

    @staticmethod
    def _task_document(task: DomainTask) -> dict[str, Any]:
        document = task.model_dump(mode="python", exclude_none=True)
        document["task_type"] = task.task_type.value
        document["status"] = task.status.value
        return document

    @staticmethod
    def _event_document(event: DomainTaskEvent) -> dict[str, Any]:
        document = event.model_dump(mode="python", exclude_none=True)
        document["status"] = event.status.value
        return document

    @staticmethod
    def _parse_task(document: Optional[dict[str, Any]]) -> Optional[DomainTask]:
        if document is None:
            return None
        clean = dict(document)
        clean.pop("_id", None)
        return DomainTask.model_validate(clean)

    @staticmethod
    def _parse_event(document: dict[str, Any]) -> DomainTaskEvent:
        clean = dict(document)
        clean.pop("_id", None)
        return DomainTaskEvent.model_validate(clean)

    async def _append_event(
        self,
        task: DomainTask,
        event_type: str,
        *,
        message: Optional[str] = None,
        data: Optional[dict[str, Any]] = None,
        now: Optional[datetime] = None,
    ) -> DomainTaskEvent:
        event = DomainTaskEvent(
            task_id=task.task_id,
            user_id=task.user_id,
            event_type=event_type,
            status=task.status,
            message=message,
            data=redact_sensitive_mapping(data or {}),
            created_at=_utc_timestamp(now),
        )
        await self.events.insert_one(self._event_document(event))
        return event

    async def create_task(
        self,
        *,
        user_id: str,
        task_type: DomainTaskType | str,
        payload: dict[str, Any],
        priority: int = 0,
        max_attempts: int = 3,
        idempotency_key: Optional[str] = None,
        task_id: Optional[str] = None,
        stage: str = "queued",
        message: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> DomainTask:
        task_type_value = DomainTaskType(task_type)
        created_at = _utc_timestamp(now)
        request_hash = None
        idempotency_query = None
        if idempotency_key is not None:
            if not isinstance(idempotency_key, str) or not idempotency_key.strip():
                raise ValueError("idempotency_key must be a non-empty string")
            idempotency_key = idempotency_key.strip()
            request_hash = canonical_request_hash(
                {
                    "task_type": task_type_value.value,
                    "payload": payload,
                    "priority": priority,
                    "max_attempts": max_attempts,
                }
            )
            idempotency_query = {
                "user_id": user_id,
                "task_type": task_type_value.value,
                "idempotency_key": idempotency_key,
            }
            existing = await self.tasks.find_one(idempotency_query)
            if existing is not None:
                return self._verify_idempotent_existing(existing, request_hash)

        values: dict[str, Any] = {
            "user_id": user_id,
            "task_type": task_type_value,
            "priority": priority,
            "payload": payload,
            "max_attempts": max_attempts,
            "stage": stage,
            "message": message,
            "created_at": created_at,
            "updated_at": created_at,
            "idempotency_key": idempotency_key,
            "request_hash": request_hash,
        }
        if task_id is not None:
            values["task_id"] = task_id
        task = DomainTask(**values)
        try:
            await self.tasks.insert_one(self._task_document(task))
        except DuplicateKeyError:
            if idempotency_query is None:
                raise
            existing = await self.tasks.find_one(idempotency_query)
            if existing is None:
                raise
            return self._verify_idempotent_existing(existing, request_hash)
        await self._append_event(
            task,
            "created",
            message=message,
            data={"stage": stage},
            now=created_at,
        )
        return task

    def _verify_idempotent_existing(
        self,
        document: dict[str, Any],
        request_hash: str,
    ) -> DomainTask:
        if document.get("request_hash") != request_hash:
            raise IdempotencyConflictError(
                "idempotency key was already used with a different request"
            )
        task = self._parse_task(document)
        assert task is not None
        return task

    async def get_task(self, task_id: str, user_id: str) -> Optional[DomainTask]:
        return self._parse_task(
            await self.tasks.find_one({"task_id": task_id, "user_id": user_id})
        )

    async def list_tasks(
        self,
        *,
        user_id: str,
        task_type: Optional[DomainTaskType | str] = None,
        status: Optional[DomainTaskStatus | str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> list[DomainTask]:
        if page < 1 or not 1 <= page_size <= 200:
            raise ValueError("invalid pagination")
        query: dict[str, Any] = {"user_id": user_id}
        if task_type is not None:
            query["task_type"] = DomainTaskType(task_type).value
        if status is not None:
            query["status"] = DomainTaskStatus(status).value
        cursor = (
            self.tasks.find(query)
            .sort([("created_at", DESCENDING), ("task_id", DESCENDING)])
            .skip((page - 1) * page_size)
            .limit(page_size)
        )
        documents = await cursor.to_list(length=page_size)
        return [
            task
            for document in documents
            if (task := self._parse_task(document)) is not None
        ]

    async def list_events(
        self,
        *,
        task_id: str,
        user_id: str,
        page: int = 1,
        page_size: int = 100,
    ) -> list[DomainTaskEvent]:
        if page < 1 or not 1 <= page_size <= 200:
            raise ValueError("invalid pagination")
        cursor = (
            self.events.find({"task_id": task_id, "user_id": user_id})
            .sort([("created_at", ASCENDING), ("event_id", ASCENDING)])
            .skip((page - 1) * page_size)
            .limit(page_size)
        )
        documents = await cursor.to_list(length=page_size)
        return [self._parse_event(document) for document in documents]

    async def claim_next(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        task_types: Optional[Iterable[DomainTaskType | str]] = None,
        now: Optional[datetime] = None,
    ) -> Optional[DomainTask]:
        if not worker_id or lease_seconds <= 0:
            raise ValueError("worker_id and a positive lease are required")
        claimed_at = _utc_timestamp(now)
        query: dict[str, Any] = {
            "status": DomainTaskStatus.QUEUED.value,
            "$expr": {"$lt": ["$attempt", "$max_attempts"]},
        }
        if task_types is not None:
            allowed = [DomainTaskType(value).value for value in task_types]
            if not allowed:
                return None
            query["task_type"] = {"$in": allowed}
        document = await self.tasks.find_one_and_update(
            query,
            {
                "$set": {
                    "status": DomainTaskStatus.RUNNING.value,
                    "worker_id": worker_id,
                    "heartbeat_at": claimed_at,
                    "lease_expires_at": claimed_at
                    + timedelta(seconds=lease_seconds),
                    "updated_at": claimed_at,
                    "stage": "running",
                    "error": None,
                },
                "$inc": {"attempt": 1},
                "$min": {"started_at": claimed_at},
            },
            sort=[("priority", DESCENDING), ("created_at", ASCENDING)],
            return_document=ReturnDocument.AFTER,
        )
        task = self._parse_task(document)
        if task is not None:
            require_transition(DomainTaskStatus.QUEUED, task.status)
            await self._append_event(
                task,
                "claimed",
                data={"worker_id": worker_id, "attempt": task.attempt},
                now=claimed_at,
            )
        return task

    async def heartbeat(
        self,
        *,
        task_id: str,
        worker_id: str,
        lease_seconds: int,
        now: Optional[datetime] = None,
    ) -> Optional[DomainTask]:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        heartbeat_at = _utc_timestamp(now)
        document = await self.tasks.find_one_and_update(
            {
                "task_id": task_id,
                "worker_id": worker_id,
                "status": {
                    "$in": [
                        DomainTaskStatus.RUNNING.value,
                        DomainTaskStatus.CANCELLING.value,
                    ]
                },
                "lease_expires_at": {"$gt": heartbeat_at},
            },
            {
                "$set": {
                    "heartbeat_at": heartbeat_at,
                    "lease_expires_at": heartbeat_at
                    + timedelta(seconds=lease_seconds),
                    "updated_at": heartbeat_at,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        return self._parse_task(document)

    async def update_progress(
        self,
        *,
        task_id: str,
        worker_id: str,
        progress: float,
        stage: str,
        message: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> DomainTask:
        updated_at = _utc_timestamp(now)
        if (
            isinstance(progress, bool)
            or not isinstance(progress, (int, float))
            or not 0.0 <= progress <= 1.0
        ):
            raise ValueError("progress must be a finite number between 0 and 1")
        if not isinstance(stage, str) or not 1 <= len(stage) <= 120:
            raise ValueError("stage must contain 1 to 120 characters")
        if message is not None and (
            not isinstance(message, str) or len(message) > 2000
        ):
            raise ValueError("message must be a string of at most 2000 characters")
        document = await self.tasks.find_one_and_update(
            {
                "task_id": task_id,
                "worker_id": worker_id,
                "status": DomainTaskStatus.RUNNING.value,
                "lease_expires_at": {"$gt": updated_at},
            },
            {
                "$set": {
                    "progress": progress,
                    "stage": stage,
                    "message": message,
                    "updated_at": updated_at,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        task = self._parse_task(document)
        if task is None:
            raise LeaseOwnershipError("active lease is not owned by worker")
        await self._append_event(
            task,
            "progress",
            message=message,
            data={"progress": progress, "stage": stage},
            now=updated_at,
        )
        return task

    async def mark_succeeded(
        self,
        *,
        task_id: str,
        worker_id: str,
        result_ref: Optional[DomainTaskResultRef | dict[str, Any]] = None,
        now: Optional[datetime] = None,
    ) -> DomainTask:
        finished_at = _utc_timestamp(now)
        normalized_ref = (
            DomainTaskResultRef.model_validate(result_ref).model_dump()
            if result_ref is not None
            else None
        )
        document = await self.tasks.find_one_and_update(
            {
                "task_id": task_id,
                "worker_id": worker_id,
                "status": DomainTaskStatus.RUNNING.value,
                "lease_expires_at": {"$gt": finished_at},
            },
            {
                "$set": {
                    "status": DomainTaskStatus.SUCCEEDED.value,
                    "progress": 1.0,
                    "stage": "succeeded",
                    "result_ref": normalized_ref,
                    "finished_at": finished_at,
                    "updated_at": finished_at,
                },
                "$unset": {
                    "worker_id": "",
                    "heartbeat_at": "",
                    "lease_expires_at": "",
                },
            },
            return_document=ReturnDocument.AFTER,
        )
        task = self._parse_task(document)
        if task is None:
            raise LeaseOwnershipError("active lease is not owned by worker")
        require_transition(DomainTaskStatus.RUNNING, task.status)
        await self._append_event(task, "succeeded", now=finished_at)
        return task

    async def fail_attempt(
        self,
        *,
        task_id: str,
        worker_id: str,
        code: str,
        message: str,
        retryable: bool,
        details: Optional[dict[str, Any]] = None,
        now: Optional[datetime] = None,
    ) -> DomainTask:
        failed_at = _utc_timestamp(now)
        current = await self.tasks.find_one(
            {
                "task_id": task_id,
                "worker_id": worker_id,
                "status": DomainTaskStatus.RUNNING.value,
                "lease_expires_at": {"$gt": failed_at},
            }
        )
        if current is None:
            raise LeaseOwnershipError("active lease is not owned by worker")
        target = (
            DomainTaskStatus.RETRY_WAIT
            if retryable and current["attempt"] < current["max_attempts"]
            else DomainTaskStatus.FAILED
        )
        require_transition(DomainTaskStatus.RUNNING, target)
        effective_retryable = (
            retryable and target == DomainTaskStatus.RETRY_WAIT
        )
        error = DomainTaskError(
            code=code,
            message=message,
            retryable=effective_retryable,
            details=redact_sensitive_mapping(details or {}),
        ).model_dump()
        set_values: dict[str, Any] = {
            "status": target.value,
            "stage": target.value,
            "error": error,
            "updated_at": failed_at,
        }
        if target == DomainTaskStatus.FAILED:
            set_values["finished_at"] = failed_at
        document = await self.tasks.find_one_and_update(
            {
                "task_id": task_id,
                "worker_id": worker_id,
                "status": DomainTaskStatus.RUNNING.value,
                "attempt": current["attempt"],
            },
            {
                "$set": set_values,
                "$unset": {
                    "worker_id": "",
                    "heartbeat_at": "",
                    "lease_expires_at": "",
                },
            },
            return_document=ReturnDocument.AFTER,
        )
        task = self._parse_task(document)
        if task is None:
            raise LeaseOwnershipError("task changed while failing attempt")
        await self._append_event(
            task,
            target.value,
            message=message,
            data={"error_code": code, "retryable": effective_retryable},
            now=failed_at,
        )
        return task

    async def requeue_retry(
        self,
        *,
        task_id: str,
        now: Optional[datetime] = None,
    ) -> Optional[DomainTask]:
        queued_at = _utc_timestamp(now)
        require_transition(DomainTaskStatus.RETRY_WAIT, DomainTaskStatus.QUEUED)
        document = await self.tasks.find_one_and_update(
            {
                "task_id": task_id,
                "status": DomainTaskStatus.RETRY_WAIT.value,
                "$expr": {"$lt": ["$attempt", "$max_attempts"]},
            },
            {
                "$set": {
                    "status": DomainTaskStatus.QUEUED.value,
                    "stage": "queued",
                    "updated_at": queued_at,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        task = self._parse_task(document)
        if task is not None:
            await self._append_event(task, "requeued", now=queued_at)
        return task

    async def fail_retry_wait(
        self,
        *,
        task_id: str,
        code: str = "TASK_RETRY_EXHAUSTED",
        message: str = "Task retry was exhausted",
        details: Optional[dict[str, Any]] = None,
        now: Optional[datetime] = None,
    ) -> Optional[DomainTask]:
        failed_at = _utc_timestamp(now)
        require_transition(
            DomainTaskStatus.RETRY_WAIT,
            DomainTaskStatus.FAILED,
        )
        error = DomainTaskError(
            code=code,
            message=message,
            retryable=False,
            details=redact_sensitive_mapping(details or {}),
        ).model_dump()
        document = await self.tasks.find_one_and_update(
            {
                "task_id": task_id,
                "status": DomainTaskStatus.RETRY_WAIT.value,
            },
            {
                "$set": {
                    "status": DomainTaskStatus.FAILED.value,
                    "stage": "failed",
                    "error": error,
                    "finished_at": failed_at,
                    "updated_at": failed_at,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        task = self._parse_task(document)
        if task is not None:
            await self._append_event(
                task,
                "failed",
                message=message,
                data={"error_code": code, "retryable": False},
                now=failed_at,
            )
        return task

    async def recover_expired_leases(
        self,
        *,
        now: Optional[datetime] = None,
    ) -> dict[str, int]:
        recovered_at = _utc_timestamp(now)
        cursor = self.tasks.find(
            {
                "status": DomainTaskStatus.RUNNING.value,
                "lease_expires_at": {"$lte": recovered_at},
            }
        )
        candidates = await cursor.to_list(length=None)
        counts = {"retry_wait": 0, "failed": 0}
        for candidate in candidates:
            target = (
                DomainTaskStatus.RETRY_WAIT
                if candidate["attempt"] < candidate["max_attempts"]
                else DomainTaskStatus.FAILED
            )
            require_transition(DomainTaskStatus.RUNNING, target)
            error = DomainTaskError(
                code=(
                    "TASK_LEASE_EXPIRED"
                    if target == DomainTaskStatus.RETRY_WAIT
                    else "TASK_RETRY_EXHAUSTED"
                ),
                message="Worker lease expired",
                retryable=target == DomainTaskStatus.RETRY_WAIT,
            ).model_dump()
            set_values: dict[str, Any] = {
                "status": target.value,
                "stage": target.value,
                "error": error,
                "updated_at": recovered_at,
            }
            if target == DomainTaskStatus.FAILED:
                set_values["finished_at"] = recovered_at
            document = await self.tasks.find_one_and_update(
                {
                    "task_id": candidate["task_id"],
                    "status": DomainTaskStatus.RUNNING.value,
                    "worker_id": candidate.get("worker_id"),
                    "lease_expires_at": {"$lte": recovered_at},
                },
                {
                    "$set": set_values,
                    "$unset": {
                        "worker_id": "",
                        "heartbeat_at": "",
                        "lease_expires_at": "",
                    },
                },
                return_document=ReturnDocument.AFTER,
            )
            task = self._parse_task(document)
            if task is None:
                continue
            counts[target.value] += 1
            await self._append_event(
                task,
                "lease_expired",
                data={"outcome": target.value},
                now=recovered_at,
            )
        return counts

    async def request_cancel(
        self,
        *,
        task_id: str,
        user_id: str,
        now: Optional[datetime] = None,
    ) -> Optional[DomainTask]:
        requested_at = _utc_timestamp(now)
        require_transition(DomainTaskStatus.QUEUED, DomainTaskStatus.CANCELLED)
        document = await self.tasks.find_one_and_update(
            {
                "task_id": task_id,
                "user_id": user_id,
                "status": DomainTaskStatus.QUEUED.value,
            },
            {
                "$set": {
                    "status": DomainTaskStatus.CANCELLED.value,
                    "stage": "cancelled",
                    "cancel_requested_at": requested_at,
                    "finished_at": requested_at,
                    "updated_at": requested_at,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        event_type = "cancelled"
        if document is None:
            require_transition(
                DomainTaskStatus.RUNNING,
                DomainTaskStatus.CANCELLING,
            )
            document = await self.tasks.find_one_and_update(
                {
                    "task_id": task_id,
                    "user_id": user_id,
                    "status": DomainTaskStatus.RUNNING.value,
                },
                {
                    "$set": {
                        "status": DomainTaskStatus.CANCELLING.value,
                        "stage": "cancelling",
                        "cancel_requested_at": requested_at,
                        "updated_at": requested_at,
                    }
                },
                return_document=ReturnDocument.AFTER,
            )
            event_type = "cancel_requested"
        task = self._parse_task(document)
        if task is not None:
            await self._append_event(task, event_type, now=requested_at)
            return task
        existing = await self.tasks.find_one(
            {"task_id": task_id, "user_id": user_id}
        )
        if existing is None:
            return None
        parsed = self._parse_task(existing)
        assert parsed is not None
        if parsed.status == DomainTaskStatus.CANCELLING:
            return parsed
        raise TaskNotCancellableError(
            f"task in {parsed.status.value} cannot be cancelled"
        )

    async def acknowledge_cancel(
        self,
        *,
        task_id: str,
        worker_id: str,
        now: Optional[datetime] = None,
    ) -> DomainTask:
        cancelled_at = _utc_timestamp(now)
        require_transition(
            DomainTaskStatus.CANCELLING,
            DomainTaskStatus.CANCELLED,
        )
        document = await self.tasks.find_one_and_update(
            {
                "task_id": task_id,
                "worker_id": worker_id,
                "status": DomainTaskStatus.CANCELLING.value,
            },
            {
                "$set": {
                    "status": DomainTaskStatus.CANCELLED.value,
                    "stage": "cancelled",
                    "finished_at": cancelled_at,
                    "updated_at": cancelled_at,
                },
                "$unset": {
                    "worker_id": "",
                    "heartbeat_at": "",
                    "lease_expires_at": "",
                },
            },
            return_document=ReturnDocument.AFTER,
        )
        task = self._parse_task(document)
        if task is None:
            raise LeaseOwnershipError("cancellation is not owned by worker")
        await self._append_event(task, "cancelled", now=cancelled_at)
        return task


async def ensure_domain_task_indexes(database: Any) -> None:
    await DomainTaskRepository(database).ensure_indexes()
