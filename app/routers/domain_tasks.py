"""Authenticated, owner-scoped APIs for durable domain tasks."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from pymongo.errors import PyMongoError

from app.core.database import get_mongo_db
from app.models.domain_task import (
    DomainTask,
    DomainTaskEvent,
    DomainTaskStatus,
    DomainTaskType,
)
from app.repositories.domain_task_repository import DomainTaskRepository
from app.routers.auth_db import get_current_user
from app.services.domain_tasks import TaskNotCancellableError

router = APIRouter(prefix="/tasks", tags=["domain-tasks"])


class DomainTaskListResponse(BaseModel):
    items: list[DomainTask]
    page: int
    page_size: int


class DomainTaskEventListResponse(BaseModel):
    items: list[DomainTaskEvent]
    page: int
    page_size: int


def get_domain_task_repository() -> DomainTaskRepository:
    return DomainTaskRepository(get_mongo_db())


def _error(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


@router.get("", response_model=DomainTaskListResponse)
async def list_domain_tasks(
    task_type: Optional[DomainTaskType] = Query(default=None, alias="type"),
    task_status: Optional[DomainTaskStatus] = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
    repository: DomainTaskRepository = Depends(get_domain_task_repository),
) -> DomainTaskListResponse:
    try:
        items = await repository.list_tasks(
            user_id=current_user["id"],
            task_type=task_type,
            status=task_status,
            page=page,
            page_size=page_size,
        )
    except PyMongoError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_error("TASK_QUEUE_UNAVAILABLE", "Task queue is unavailable"),
        ) from exc
    return DomainTaskListResponse(items=items, page=page, page_size=page_size)


@router.get("/{task_id}/events", response_model=DomainTaskEventListResponse)
async def list_domain_task_events(
    task_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
    repository: DomainTaskRepository = Depends(get_domain_task_repository),
) -> DomainTaskEventListResponse:
    try:
        task = await repository.get_task(task_id, current_user["id"])
        if task is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=_error("TASK_NOT_FOUND", "Task was not found"),
            )
        items = await repository.list_events(
            task_id=task_id,
            user_id=current_user["id"],
            page=page,
            page_size=page_size,
        )
    except HTTPException:
        raise
    except PyMongoError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_error("TASK_QUEUE_UNAVAILABLE", "Task queue is unavailable"),
        ) from exc
    return DomainTaskEventListResponse(
        items=items,
        page=page,
        page_size=page_size,
    )


@router.get("/{task_id}", response_model=DomainTask)
async def get_domain_task(
    task_id: str,
    current_user: dict = Depends(get_current_user),
    repository: DomainTaskRepository = Depends(get_domain_task_repository),
) -> DomainTask:
    try:
        task = await repository.get_task(task_id, current_user["id"])
    except PyMongoError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_error("TASK_QUEUE_UNAVAILABLE", "Task queue is unavailable"),
        ) from exc
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_error("TASK_NOT_FOUND", "Task was not found"),
        )
    return task


@router.post(
    "/{task_id}/cancel",
    response_model=DomainTask,
    status_code=status.HTTP_202_ACCEPTED,
)
async def cancel_domain_task(
    task_id: str,
    current_user: dict = Depends(get_current_user),
    repository: DomainTaskRepository = Depends(get_domain_task_repository),
) -> DomainTask:
    try:
        task = await repository.request_cancel(
            task_id=task_id,
            user_id=current_user["id"],
        )
    except TaskNotCancellableError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_error(exc.code, str(exc)),
        ) from exc
    except PyMongoError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_error("TASK_QUEUE_UNAVAILABLE", "Task queue is unavailable"),
        ) from exc
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_error("TASK_NOT_FOUND", "Task was not found"),
        )
    return task
