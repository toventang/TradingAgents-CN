import uuid
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.models.notification import (
    NotificationPreference,
    NotificationChannel,
    NotificationSeverity,
    NotificationEvent,
    ChannelConfig,
    NotificationPayload
)
from app.repositories.notification_repository import NotificationRepository
from app.services.notifications.notification_service import NotificationService
from app.services.notifications_service import get_notifications_service
from app.services.auth_service import AuthService
from app.core.response import ok
from app.utils.timezone import now_tz

router = APIRouter(prefix="/api/notifications", tags=["Notifications"])


class TestWebhookRequest(BaseModel):
    target_url: str


@router.get("/preferences", response_model=Dict[str, Any])
async def get_preferences(
    user_id: str = Depends(AuthService.get_canonical_user_id)
):
    repo = NotificationRepository()
    pref = await repo.get_preference(user_id)
    return pref.model_dump()


@router.put("/preferences", response_model=Dict[str, Any])
async def update_preferences(
    preference: NotificationPreference,
    user_id: str = Depends(AuthService.get_canonical_user_id)
):
    repo = NotificationRepository()
    preference.user_id = user_id
    updated = await repo.update_preference(preference)
    return updated.model_dump()


@router.get("/logs", response_model=List[Dict[str, Any]])
async def list_logs(
    limit: int = 50,
    user_id: str = Depends(AuthService.get_canonical_user_id)
):
    repo = NotificationRepository()
    logs = await repo.list_logs(user_id, limit=limit)
    return [l.model_dump() for l in logs]


@router.post("/webhooks/test", response_model=Dict[str, Any])
async def test_webhook(
    req: TestWebhookRequest,
    user_id: str = Depends(AuthService.get_canonical_user_id)
):
    service = NotificationService(is_test_env=True)
    test_payload = NotificationPayload(
        event_id=f"evt_test_{uuid.uuid4().hex[:8]}",
        user_id=user_id,
        event_type=NotificationEvent.TASK_COMPLETED,
        severity=NotificationSeverity.INFO,
        title="Test Webhook Notification",
        message="This is a test webhook ping from TradingAgents."
    )

    try:
        await service._send_webhook(test_payload, req.target_url)
        return {"status": "success", "message": f"Webhook test ping sent successfully to {req.target_url}"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Webhook delivery failed: {str(e)}")


# ============ 用户通知列表 / 已读（前端 store 使用，返回 ApiResponse 形态） ============

@router.get("/unread_count", response_model=Dict[str, Any])
async def get_unread_count(
    user_id: str = Depends(AuthService.get_canonical_user_id)
):
    """获取当前用户的未读通知数量"""
    svc = get_notifications_service()
    count = await svc.unread_count(user_id)
    return ok({"count": count})


@router.get("", response_model=Dict[str, Any])
async def list_notifications(
    status: Optional[str] = None,
    type: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    user_id: str = Depends(AuthService.get_canonical_user_id)
):
    """获取当前用户的通知列表

    查询参数（与前端 NotificationListQuery 对齐）：
    - status: unread / read / all（其它值视为 all，不过滤）
    - type: analysis / alert / system
    - page / page_size: 分页
    """
    # 规范化分页参数，防止越界
    page = max(1, int(page))
    page_size = max(1, min(int(page_size), 100))

    svc = get_notifications_service()
    result = await svc.list(
        user_id,
        status=status,
        ntype=type,
        page=page,
        page_size=page_size,
    )
    return ok(result.model_dump())


@router.post("/read-all", response_model=Dict[str, Any])
async def mark_all_notifications_read(
    user_id: str = Depends(AuthService.get_canonical_user_id)
):
    """标记全部未读通知为已读"""
    svc = get_notifications_service()
    modified = await svc.mark_all_read(user_id)
    return ok({"success": True, "modified": modified})


@router.post("/{notif_id}/read", response_model=Dict[str, Any])
async def mark_notification_read(
    notif_id: str,
    user_id: str = Depends(AuthService.get_canonical_user_id)
):
    """标记单条通知为已读"""
    svc = get_notifications_service()
    success = await svc.mark_read(user_id, notif_id)
    return ok({"success": success})
