from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, status, Response
from pydantic import BaseModel
from app.routers.auth_db import get_current_user
from app.core.database import get_mongo_db
from app.models.domain_task import DomainTask, DomainTaskEvent, TaskStatus
from app.repositories.domain_task_repository import (
    DomainTaskRepository,
    TaskNotFoundError,
    TaskForbiddenError,
    InvalidTaskTransitionError
)

router = APIRouter(prefix="/api/tasks", tags=["Domain Tasks"])


def get_task_repository() -> DomainTaskRepository:
    db = get_mongo_db()
    return DomainTaskRepository(db)


@router.get("/{task_id}")
async def get_task_detail(
    task_id: str,
    user: dict = Depends(get_current_user),
    repo: DomainTaskRepository = Depends(get_task_repository)
):
    """获取属于当前用户的任务详情"""
    try:
        task = await repo.get_task(task_id, user_id=user["id"])
        if not task:
            raise HTTPException(status_code=404, detail="TASK_NOT_FOUND")
        return {
            "success": True,
            "data": task.model_dump()
        }
    except TaskForbiddenError:
        raise HTTPException(status_code=403, detail="TASK_FORBIDDEN")
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="TASK_NOT_FOUND")


@router.post("/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    response: Response,
    user: dict = Depends(get_current_user),
    repo: DomainTaskRepository = Depends(get_task_repository)
):
    """请求取消任务"""
    try:
        task = await repo.request_cancel(task_id, user_id=user["id"])
        if task.status in (TaskStatus.CANCELLING, TaskStatus.CANCELLING.value, "cancelling"):
            response.status_code = status.HTTP_202_ACCEPTED
        else:
            response.status_code = status.HTTP_200_OK
        return {
            "success": True,
            "data": task.model_dump(),
            "message": f"Task cancellation status: {task.status.value}"
        }
    except TaskForbiddenError:
        raise HTTPException(status_code=403, detail="TASK_FORBIDDEN")
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="TASK_NOT_FOUND")
    except InvalidTaskTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("")
async def list_user_tasks(
    task_type: Optional[str] = Query(None, alias="type"),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_current_user),
    repo: DomainTaskRepository = Depends(get_task_repository)
):
    """分页列出当前用户的任务"""
    tasks, total = await repo.list_tasks(
        user_id=user["id"],
        task_type=task_type,
        status=status,
        page=page,
        page_size=page_size
    )
    return {
        "success": True,
        "data": {
            "items": [t.model_dump() for t in tasks],
            "total": total,
            "page": page,
            "page_size": page_size
        }
    }


@router.get("/{task_id}/events")
async def list_task_events(
    task_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user: dict = Depends(get_current_user),
    repo: DomainTaskRepository = Depends(get_task_repository)
):
    """分页获取任务进度事件"""
    try:
        events, total = await repo.list_task_events(
            task_id=task_id,
            user_id=user["id"],
            page=page,
            page_size=page_size
        )
        return {
            "success": True,
            "data": {
                "items": [e.model_dump() for e in events],
                "total": total,
                "page": page,
                "page_size": page_size
            }
        }
    except TaskForbiddenError:
        raise HTTPException(status_code=403, detail="TASK_FORBIDDEN")
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="TASK_NOT_FOUND")
