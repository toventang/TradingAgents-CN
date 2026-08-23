import uuid
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
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
from app.services.auth_service import AuthService
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
