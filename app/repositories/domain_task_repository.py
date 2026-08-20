import uuid
from datetime import timedelta
from typing import Optional, List, Dict, Any, Tuple
from app.utils.timezone import now_tz
from app.models.domain_task import (
    DomainTask,
    DomainTaskEvent,
    TaskStatus,
    TaskType,
    validate_task_transition,
    InvalidTaskTransitionError
)


class IdempotencyConflictError(Exception):
    """幂等键请求冲突"""
    pass


class TaskNotFoundError(Exception):
    """任务未找到"""
    pass


class TaskForbiddenError(Exception):
    """无权访问任务"""
    pass


class DomainTaskRepository:
    """持久化任务 Repository (适配 Motor / Fake In-memory DB)"""

    def __init__(self, db):
        self.db = db
        self.tasks_col = db["domain_tasks"]
        self.events_col = db["domain_task_events"]

    async def init_indexes(self):
        """初始化数据库索引"""
        try:
            await self.tasks_col.create_index([("task_id", 1)], unique=True)
            await self.tasks_col.create_index(
                [("user_id", 1), ("task_type", 1), ("idempotency_key", 1)],
                unique=True,
                sparse=True
            )
            await self.tasks_col.create_index([("status", 1), ("priority", -1), ("created_at", 1)])
            await self.tasks_col.create_index([("user_id", 1), ("created_at", -1)])
            await self.tasks_col.create_index([("lease_expires_at", 1)])
            await self.events_col.create_index([("task_id", 1), ("created_at", 1)])
        except Exception:
            pass

    async def create_task(
        self,
        user_id: str,
        task_type: TaskType,
        payload: Dict[str, Any],
        priority: int = 0,
        idempotency_key: Optional[str] = None,
        request_hash: Optional[str] = None,
        max_attempts: int = 3
    ) -> DomainTask:
        """创建任务（支持幂等）"""
        now = now_tz()

        if idempotency_key:
            existing = await self.tasks_col.find_one({
                "user_id": user_id,
                "task_type": task_type.value if isinstance(task_type, TaskType) else task_type,
                "idempotency_key": idempotency_key
            })
            if existing:
                if request_hash and existing.get("request_hash") and existing.get("request_hash") != request_hash:
                    raise IdempotencyConflictError("Idempotency key reused with different request_hash")
                return DomainTask(**existing)

        task_id = f"task_{uuid.uuid4().hex[:16]}"
        task = DomainTask(
            task_id=task_id,
            user_id=user_id,
            task_type=task_type,
            status=TaskStatus.QUEUED,
            priority=priority,
            payload=payload,
            progress=0.0,
            stage="queued",
            attempt=0,
            max_attempts=max_attempts,
            created_at=now,
            updated_at=now,
            idempotency_key=idempotency_key,
            request_hash=request_hash
        )

        task_dict = task.model_dump()
        await self.tasks_col.insert_one(task_dict)

        event = DomainTaskEvent(
            event_id=f"evt_{uuid.uuid4().hex[:16]}",
            task_id=task_id,
            user_id=user_id,
            stage="queued",
            progress=0.0,
            message="Task created and queued",
            created_at=now
        )
        await self.events_col.insert_one(event.model_dump())

        return task

    async def get_task(self, task_id: str, user_id: str) -> Optional[DomainTask]:
        """获取属于特定用户的任务"""
        doc = await self.tasks_col.find_one({"task_id": task_id})
        if not doc:
            return None
        if doc.get("user_id") != user_id:
            raise TaskForbiddenError("Access to task denied")
        return DomainTask(**doc)

    async def list_tasks(
        self,
        user_id: str,
        task_type: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20
    ) -> Tuple[List[DomainTask], int]:
        """分页列出用户的任务"""
        query: Dict[str, Any] = {"user_id": user_id}
        if task_type:
            query["task_type"] = task_type
        if status:
            query["status"] = status

        total = await self.tasks_col.count_documents(query) if hasattr(self.tasks_col, "count_documents") else len(await self.tasks_col.find(query).to_list(1000))
        skip = (page - 1) * page_size

        cursor = self.tasks_col.find(query).sort("created_at", -1).skip(skip).limit(page_size)
        docs = await cursor.to_list(length=page_size) if hasattr(cursor, "to_list") else await cursor

        return [DomainTask(**d) for d in docs], total

    async def claim_task(
        self,
        worker_id: str,
        lease_seconds: int = 60,
        task_types: Optional[List[str]] = None
    ) -> Optional[DomainTask]:
        """原子性领取任务"""
        now = now_tz()
        lease_expires = now + timedelta(seconds=lease_seconds)

        query: Dict[str, Any] = {
            "status": {"$in": [TaskStatus.QUEUED.value, TaskStatus.RETRY_WAIT.value]}
        }
        if task_types:
            query["task_type"] = {"$in": task_types}

        doc = await self.tasks_col.find_one_and_update(
            filter=query,
            update={
                "$set": {
                    "status": TaskStatus.RUNNING.value,
                    "worker_id": worker_id,
                    "heartbeat_at": now,
                    "lease_expires_at": lease_expires,
                    "stage": "running",
                    "updated_at": now
                },
                "$inc": {"attempt": 1}
            },
            sort=[("priority", -1), ("created_at", 1)],
            return_document=True
        )

        if not doc:
            return None

        # 如果首次运行，设置 started_at
        if not doc.get("started_at"):
            await self.tasks_col.update_one(
                {"task_id": doc["task_id"]},
                {"$set": {"started_at": now}}
            )
            doc["started_at"] = now

        task = DomainTask(**doc)

        event = DomainTaskEvent(
            event_id=f"evt_{uuid.uuid4().hex[:16]}",
            task_id=task.task_id,
            user_id=task.user_id,
            stage="running",
            progress=task.progress,
            message=f"Claimed by worker {worker_id}",
            created_at=now
        )
        await self.events_col.insert_one(event.model_dump())

        return task

    async def heartbeat(self, task_id: str, worker_id: str, lease_seconds: int = 60) -> Dict[str, bool]:
        """续约租约与心跳"""
        now = now_tz()
        lease_expires = now + timedelta(seconds=lease_seconds)

        doc = await self.tasks_col.find_one_and_update(
            filter={"task_id": task_id, "worker_id": worker_id, "status": TaskStatus.RUNNING.value},
            update={
                "$set": {
                    "heartbeat_at": now,
                    "lease_expires_at": lease_expires,
                    "updated_at": now
                }
            },
            return_document=True
        )

        if not doc:
            return {"success": False, "cancel_requested": False}

        return {
            "success": True,
            "cancel_requested": doc.get("cancel_requested_at") is not None
        }

    async def update_progress(
        self,
        task_id: str,
        worker_id: str,
        progress: float,
        stage: str,
        message: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ) -> bool:
        """更新任务进度与阶段"""
        now = now_tz()
        doc = await self.tasks_col.find_one_and_update(
            filter={"task_id": task_id, "worker_id": worker_id, "status": TaskStatus.RUNNING.value},
            update={
                "$set": {
                    "progress": max(0.0, min(1.0, progress)),
                    "stage": stage,
                    "message": message,
                    "updated_at": now
                }
            },
            return_document=True
        )
        if not doc:
            return False

        event = DomainTaskEvent(
            event_id=f"evt_{uuid.uuid4().hex[:16]}",
            task_id=task_id,
            user_id=doc["user_id"],
            stage=stage,
            progress=progress,
            message=message,
            details=details,
            created_at=now
        )
        await self.events_col.insert_one(event.model_dump())
        return True

    async def complete_task(
        self,
        task_id: str,
        worker_id: str,
        result_ref: Optional[Dict[str, Any]] = None,
        message: str = "Task completed successfully"
    ) -> bool:
        """完成任务"""
        now = now_tz()
        doc = await self.tasks_col.find_one_and_update(
            filter={"task_id": task_id, "worker_id": worker_id, "status": TaskStatus.RUNNING.value},
            update={
                "$set": {
                    "status": TaskStatus.SUCCEEDED.value,
                    "progress": 1.0,
                    "stage": "succeeded",
                    "message": message,
                    "result_ref": result_ref,
                    "finished_at": now,
                    "updated_at": now
                }
            },
            return_document=True
        )
        if not doc:
            return False

        event = DomainTaskEvent(
            event_id=f"evt_{uuid.uuid4().hex[:16]}",
            task_id=task_id,
            user_id=doc["user_id"],
            stage="succeeded",
            progress=1.0,
            message=message,
            created_at=now
        )
        await self.events_col.insert_one(event.model_dump())
        return True

    async def fail_task(
        self,
        task_id: str,
        worker_id: str,
        error_data: Dict[str, Any],
        retryable: bool = True
    ) -> bool:
        """失败/重试任务"""
        now = now_tz()
        doc = await self.tasks_col.find_one({"task_id": task_id, "worker_id": worker_id})
        if not doc:
            return False

        attempt = doc.get("attempt", 1)
        max_attempts = doc.get("max_attempts", 3)

        if retryable and attempt < max_attempts:
            new_status = TaskStatus.RETRY_WAIT.value
            update_fields = {
                "status": new_status,
                "stage": "retry_wait",
                "message": f"Task failed (attempt {attempt}/{max_attempts}), waiting for retry",
                "error": error_data,
                "worker_id": None,
                "lease_expires_at": None,
                "updated_at": now
            }
        else:
            new_status = TaskStatus.FAILED.value
            update_fields = {
                "status": new_status,
                "stage": "failed",
                "message": error_data.get("message", "Task execution failed"),
                "error": error_data,
                "finished_at": now,
                "updated_at": now
            }

        res = await self.tasks_col.update_one(
            {"task_id": task_id, "worker_id": worker_id},
            {"$set": update_fields}
        )

        event = DomainTaskEvent(
            event_id=f"evt_{uuid.uuid4().hex[:16]}",
            task_id=task_id,
            user_id=doc["user_id"],
            stage=new_status,
            progress=doc.get("progress", 0.0),
            message=update_fields["message"],
            details=error_data,
            created_at=now
        )
        await self.events_col.insert_one(event.model_dump())
        return res.modified_count > 0

    async def request_cancel(self, task_id: str, user_id: str) -> DomainTask:
        """取消任务"""
        now = now_tz()
        task_doc = await self.tasks_col.find_one({"task_id": task_id})
        if not task_doc:
            raise TaskNotFoundError("Task not found")
        if task_doc.get("user_id") != user_id:
            raise TaskForbiddenError("Access to task denied")

        status = task_doc.get("status")

        if status in [TaskStatus.QUEUED.value, TaskStatus.RETRY_WAIT.value]:
            new_status = TaskStatus.CANCELLED.value
            update_dict = {
                "status": new_status,
                "stage": "cancelled",
                "message": "Cancelled by user",
                "finished_at": now,
                "updated_at": now
            }
        elif status == TaskStatus.RUNNING.value:
            new_status = TaskStatus.CANCELLING.value
            update_dict = {
                "status": new_status,
                "stage": "cancelling",
                "cancel_requested_at": now,
                "message": "Cancellation requested by user",
                "updated_at": now
            }
        elif status == TaskStatus.CANCELLING.value or status == TaskStatus.CANCELLED.value:
            return DomainTask(**task_doc)
        else:
            raise InvalidTaskTransitionError(f"Cannot cancel task in status {status}")

        updated_doc = await self.tasks_col.find_one_and_update(
            filter={"task_id": task_id},
            update={"$set": update_dict},
            return_document=True
        )

        event = DomainTaskEvent(
            event_id=f"evt_{uuid.uuid4().hex[:16]}",
            task_id=task_id,
            user_id=user_id,
            stage=new_status,
            progress=task_doc.get("progress", 0.0),
            message=update_dict["message"],
            created_at=now
        )
        await self.events_col.insert_one(event.model_dump())

        return DomainTask(**updated_doc)

    async def recover_expired_leases(self) -> int:
        """恢复过期僵尸任务"""
        now = now_tz()
        cursor = self.tasks_col.find({
            "status": TaskStatus.RUNNING.value,
            "lease_expires_at": {"$lt": now}
        })
        expired_docs = await cursor.to_list(length=100) if hasattr(cursor, "to_list") else await cursor

        recovered_count = 0
        for doc in expired_docs:
            task_id = doc["task_id"]
            attempt = doc.get("attempt", 1)
            max_attempts = doc.get("max_attempts", 3)

            if attempt < max_attempts:
                new_status = TaskStatus.RETRY_WAIT.value
                update_fields = {
                    "status": new_status,
                    "stage": "retry_wait",
                    "message": "Worker lease expired, recovered into retry_wait",
                    "worker_id": None,
                    "lease_expires_at": None,
                    "updated_at": now
                }
            else:
                new_status = TaskStatus.FAILED.value
                update_fields = {
                    "status": new_status,
                    "stage": "failed",
                    "message": "Worker lease expired and max attempts reached",
                    "error": {"code": "LEASE_EXPIRED", "message": "Worker lease expired without heartbeat"},
                    "finished_at": now,
                    "updated_at": now
                }

            res = await self.tasks_col.update_one(
                {"task_id": task_id, "status": TaskStatus.RUNNING.value},
                {"$set": update_fields}
            )
            if res.modified_count > 0:
                recovered_count += 1
                event = DomainTaskEvent(
                    event_id=f"evt_{uuid.uuid4().hex[:16]}",
                    task_id=task_id,
                    user_id=doc["user_id"],
                    stage=new_status,
                    progress=doc.get("progress", 0.0),
                    message=update_fields["message"],
                    created_at=now
                )
                await self.events_col.insert_one(event.model_dump())

        return recovered_count

    async def list_task_events(
        self,
        task_id: str,
        user_id: str,
        page: int = 1,
        page_size: int = 50
    ) -> Tuple[List[DomainTaskEvent], int]:
        """分页查询关联的任务事件"""
        # 验证所有权
        task = await self.get_task(task_id, user_id)
        if not task:
            raise TaskNotFoundError("Task not found")

        query = {"task_id": task_id}
        total = await self.events_col.count_documents(query) if hasattr(self.events_col, "count_documents") else len(await self.events_col.find(query).to_list(1000))
        skip = (page - 1) * page_size

        cursor = self.events_col.find(query).sort("created_at", 1).skip(skip).limit(page_size)
        docs = await cursor.to_list(length=page_size) if hasattr(cursor, "to_list") else await cursor

        return [DomainTaskEvent(**d) for d in docs], total
