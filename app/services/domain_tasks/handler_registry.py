from typing import Protocol, Dict, Any, Callable, Awaitable, Optional
from dataclasses import dataclass
from app.models.domain_task import TaskType


@dataclass
class TaskContext:
    """任务执行上下文"""
    task_id: str
    user_id: str
    task_type: str
    worker_id: str
    attempt: int
    max_attempts: int


ProgressCallback = Callable[[float, str, Optional[str]], Awaitable[None]]
CancellationChecker = Callable[[], bool]


class BaseTaskHandler(Protocol):
    """任务处理器协议"""
    async def execute(
        self,
        payload: Dict[str, Any],
        context: TaskContext,
        progress: ProgressCallback,
        is_cancelled: CancellationChecker
    ) -> Dict[str, Any]:
        """执行任务逻辑并返回 result_ref 字典"""
        ...


class UnknownTaskHandlerError(KeyError):
    """未注册的任务处理器异常"""
    pass


class TaskHandlerRegistry:
    """显式任务处理器注册表"""

    def __init__(self):
        self._handlers: Dict[str, BaseTaskHandler] = {}

    def register(self, task_type: str | TaskType, handler: BaseTaskHandler):
        """注册 Handler"""
        key = task_type.value if isinstance(task_type, TaskType) else str(task_type)
        self._handlers[key] = handler

    def get(self, task_type: str | TaskType) -> BaseTaskHandler:
        """获取 Handler"""
        key = task_type.value if isinstance(task_type, TaskType) else str(task_type)
        if key not in self._handlers:
            raise UnknownTaskHandlerError(f"No task handler registered for task_type: {key}")
        return self._handlers[key]

    def has_handler(self, task_type: str | TaskType) -> bool:
        """检查是否已注册 Handler"""
        key = task_type.value if isinstance(task_type, TaskType) else str(task_type)
        return key in self._handlers


# 全局 Handler 注册表单例
global_handler_registry = TaskHandlerRegistry()
