import asyncio
import logging
import uuid
import signal
from typing import Optional, List
from app.utils.timezone import now_tz
from app.models.domain_task import DomainTask, TaskStatus
from app.repositories.domain_task_repository import DomainTaskRepository
from app.services.domain_tasks.handler_registry import (
    TaskHandlerRegistry,
    TaskContext,
    UnknownTaskHandlerError,
    global_handler_registry
)

logger = logging.getLogger("app.workers.domain_worker")


class NonRetryableTaskError(Exception):
    """不可重试的任务异常"""
    pass


class DomainWorker:
    """持久化领域任务 Worker 进程/循环"""

    def __init__(
        self,
        repository: DomainTaskRepository,
        registry: TaskHandlerRegistry = global_handler_registry,
        worker_id: Optional[str] = None,
        poll_interval: float = 1.0,
        lease_seconds: int = 60,
        task_types: Optional[List[str]] = None
    ):
        self.repo = repository
        self.registry = registry
        self.worker_id = worker_id or f"worker_{uuid.uuid4().hex[:8]}"
        self.poll_interval = poll_interval
        self.lease_seconds = lease_seconds
        self.task_types = task_types
        self.running = False
        self._stop_event = asyncio.Event()

    async def start(self):
        """启动 Worker 循环"""
        self.running = True
        self._stop_event.clear()
        logger.info(f"🚀 DomainWorker {self.worker_id} started")

        while self.running and not self._stop_event.is_set():
            try:
                processed = await self.process_one_task()
                if not processed:
                    await asyncio.sleep(self.poll_interval)
            except asyncio.CancelledError:
                logger.info(f"🛑 DomainWorker {self.worker_id} received cancellation signal")
                break
            except Exception as e:
                logger.error(f"❌ Worker loop unhandled error: {e}", exc_info=True)
                await asyncio.sleep(self.poll_interval)

        logger.info(f"🏁 DomainWorker {self.worker_id} stopped")

    def stop(self):
        """触发优雅停止"""
        self.running = False
        self._stop_event.set()

    async def process_one_task(self) -> bool:
        """处理单个领取的任务，返回是否处理了任务"""
        # 僵尸任务定期恢复
        try:
            await self.repo.recover_expired_leases()
        except Exception as e:
            logger.debug(f"Recover expired leases error: {e}")

        task = await self.repo.claim_task(
            worker_id=self.worker_id,
            lease_seconds=self.lease_seconds,
            task_types=self.task_types
        )
        if not task:
            return False

        logger.info(f"⚙️ Worker {self.worker_id} executing task {task.task_id} (type: {task.task_type})")

        cancel_requested_flag = False

        try:
            handler = self.registry.get(task.task_type)
        except UnknownTaskHandlerError as e:
            logger.error(f"❌ Unknown task handler for {task.task_type}: {e}")
            await self.repo.fail_task(
                task.task_id,
                self.worker_id,
                error_data={"code": "UNKNOWN_TASK_HANDLER", "message": str(e)},
                retryable=False
            )
            return True

        # 心跳及取消检查循环
        heartbeat_interval = max(5, self.lease_seconds // 3)

        async def heartbeat_loop():
            nonlocal cancel_requested_flag
            while True:
                await asyncio.sleep(heartbeat_interval)
                res = await self.repo.heartbeat(task.task_id, self.worker_id, lease_seconds=self.lease_seconds)
                if not res.get("success"):
                    break
                if res.get("cancel_requested"):
                    cancel_requested_flag = True

        heartbeat_task = asyncio.create_task(heartbeat_loop())

        context = TaskContext(
            task_id=task.task_id,
            user_id=task.user_id,
            task_type=task.task_type,
            worker_id=self.worker_id,
            attempt=task.attempt,
            max_attempts=task.max_attempts
        )

        async def progress_callback(progress: float, stage: str, message: Optional[str] = None):
            await self.repo.update_progress(
                task_id=task.task_id,
                worker_id=self.worker_id,
                progress=progress,
                stage=stage,
                message=message
            )

        def is_cancelled() -> bool:
            return cancel_requested_flag

        try:
            result_ref = await handler.execute(
                payload=task.payload,
                context=context,
                progress=progress_callback,
                is_cancelled=is_cancelled
            )

            if is_cancelled():
                await self.repo.request_cancel(task.task_id, task.user_id)
            else:
                await self.repo.complete_task(
                    task_id=task.task_id,
                    worker_id=self.worker_id,
                    result_ref=result_ref
                )
            logger.info(f"✅ Worker {self.worker_id} completed task {task.task_id}")

        except NonRetryableTaskError as e:
            logger.warning(f"⚠️ Task {task.task_id} failed with non-retryable error: {e}")
            await self.repo.fail_task(
                task_id=task.task_id,
                worker_id=self.worker_id,
                error_data={"code": e.__class__.__name__, "message": str(e)},
                retryable=False
            )

        except Exception as e:
            retryable = getattr(e, "retryable", True)
            logger.warning(f"⚠️ Task {task.task_id} failed with exception: {e}")
            await self.repo.fail_task(
                task_id=task.task_id,
                worker_id=self.worker_id,
                error_data={"code": e.__class__.__name__, "message": str(e)},
                retryable=retryable
            )

        finally:
            if "heartbeat_task" in locals() and not heartbeat_task.done():
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except (asyncio.CancelledError, Exception):
                    pass

        return True
