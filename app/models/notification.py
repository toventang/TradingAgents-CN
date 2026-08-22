import enum
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from app.utils.timezone import now_tz


class NotificationChannel(str, enum.Enum):
    WEBHOOK = "webhook"
    WEBSOCKET = "websocket"
    EMAIL = "email"


class NotificationSeverity(str, enum.Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class NotificationEvent(str, enum.Enum):
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    BACKTEST_COMPLETED = "backtest_completed"
    RISK_ALERT = "risk_alert"
    STRATEGY_SIGNAL = "strategy_signal"


class ChannelConfig(BaseModel):
    enabled: bool = True
    min_severity: NotificationSeverity = NotificationSeverity.INFO
    target_address: Optional[str] = None      # Webhook URL or Email address


class NotificationPreference(BaseModel):
    """用户通知渠道与订阅偏好"""
    user_id: str
    channels: Dict[NotificationChannel, ChannelConfig] = Field(default_factory=lambda: {
        NotificationChannel.WEBHOOK: ChannelConfig(enabled=True, min_severity=NotificationSeverity.INFO),
        NotificationChannel.WEBSOCKET: ChannelConfig(enabled=True, min_severity=NotificationSeverity.INFO),
        NotificationChannel.EMAIL: ChannelConfig(enabled=False, min_severity=NotificationSeverity.WARNING)
    })
    events: List[NotificationEvent] = Field(default_factory=lambda: list(NotificationEvent))
    created_at: datetime = Field(default_factory=now_tz)
    updated_at: datetime = Field(default_factory=now_tz)


class NotificationPayload(BaseModel):
    """通知消息体"""
    event_id: str
    user_id: str
    event_type: NotificationEvent
    severity: NotificationSeverity = NotificationSeverity.INFO
    title: str
    message: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=now_tz)


class NotificationLog(BaseModel):
    """通知发送与失败日志"""
    log_id: str
    user_id: str
    event_id: str
    channel: NotificationChannel
    status: str                               # success / failed / retrying
    attempts: int = 1
    target_address: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=now_tz)
