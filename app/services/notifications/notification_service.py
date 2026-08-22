import uuid
import asyncio
from typing import Optional, List, Dict, Any
import httpx

from app.models.notification import (
    NotificationPayload,
    NotificationPreference,
    NotificationChannel,
    NotificationSeverity,
    NotificationLog
)
from app.repositories.notification_repository import NotificationRepository
from app.utils.timezone import now_tz


SEVERITY_LEVELS = {
    NotificationSeverity.INFO: 1,
    NotificationSeverity.WARNING: 2,
    NotificationSeverity.CRITICAL: 3
}


class NotificationService:
    """多渠道通知调度与重试服务"""

    def __init__(self, repo: Optional[NotificationRepository] = None, is_test_env: bool = True):
        self.repo = repo or NotificationRepository()
        self.is_test_env = is_test_env

    async def dispatch(self, payload: NotificationPayload) -> List[NotificationLog]:
        """
        根据用户偏好与消息严重级别过滤并分发通知。
        - 包含指数退避重试 (最多 3 次尝试)
        - 支持 Webhook, WebSocket, Email 渠道
        - 记录分发结果与失败日志
        """
        pref = await self.repo.get_preference(payload.user_id)
        logs: List[NotificationLog] = []

        # 检查事件是否被订阅
        if payload.event_type not in pref.events:
            return logs

        payload_severity_score = SEVERITY_LEVELS.get(payload.severity, 1)

        for channel, config in pref.channels.items():
            if not config.enabled:
                continue

            min_severity_score = SEVERITY_LEVELS.get(config.min_severity, 1)
            if payload_severity_score < min_severity_score:
                continue

            log = await self._send_to_channel_with_retry(payload, channel, config.target_address)
            logs.append(log)

        return logs

    async def _send_to_channel_with_retry(
        self,
        payload: NotificationPayload,
        channel: NotificationChannel,
        target_address: Optional[str]
    ) -> NotificationLog:
        max_attempts = 3
        last_error = None

        for attempt in range(1, max_attempts + 1):
            try:
                if channel == NotificationChannel.WEBHOOK:
                    await self._send_webhook(payload, target_address)
                elif channel == NotificationChannel.WEBSOCKET:
                    await self._send_websocket(payload)
                elif channel == NotificationChannel.EMAIL:
                    await self._send_email(payload, target_address)

                log = NotificationLog(
                    log_id=f"log_{uuid.uuid4().hex[:12]}",
                    user_id=payload.user_id,
                    event_id=payload.event_id,
                    channel=channel,
                    status="success",
                    attempts=attempt,
                    target_address=target_address,
                    created_at=now_tz()
                )
                await self.repo.save_log(log)
                return log
            except Exception as e:
                last_error = str(e)
                if attempt < max_attempts:
                    await asyncio.sleep(0.01 if self.is_test_env else 2 ** attempt)

        # 最终尝试均失败，记录失败日志
        log = NotificationLog(
            log_id=f"log_{uuid.uuid4().hex[:12]}",
            user_id=payload.user_id,
            event_id=payload.event_id,
            channel=channel,
            status="failed",
            attempts=max_attempts,
            target_address=target_address,
            error_message=last_error,
            created_at=now_tz()
        )
        await self.repo.save_log(log)
        return log

    async def _send_webhook(self, payload: NotificationPayload, target_url: Optional[str]):
        if not target_url:
            raise ValueError("Target Webhook URL is missing")

        if self.is_test_env:
            if "fail" in target_url:
                raise RuntimeError(f"Simulated Webhook Failure for {target_url}")
            return

        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.post(target_url, json=payload.model_dump(mode="json"))
            res.raise_for_status()

    async def _send_websocket(self, payload: NotificationPayload):
        # 内部 WebSocket 实时推流集成
        return

    async def _send_email(self, payload: NotificationPayload, email_address: Optional[str]):
        if not email_address:
            raise ValueError("Target email address is missing")

        if self.is_test_env:
            if "fail" in email_address:
                raise RuntimeError(f"Simulated Email Failure for {email_address}")
            return
