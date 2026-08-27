"""
通知数据模型

包含两类模型：
1. 新架构：用户通知偏好/事件/分发日志（NotificationPreference / NotificationPayload / NotificationLog ...）
2. 遗留 API：简单通知模型（NotificationCreate / NotificationDB / NotificationOut / NotificationList）
   保留以兼容 services/notifications_service.py 与 services/simple_analysis_service.py
"""

import enum
from datetime import datetime
from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field, field_serializer
from app.utils.timezone import now_tz


# ============================================================
# 新架构：通知偏好与分发
# ============================================================


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


# ============================================================
# 遗留 API：简单通知模型
# ============================================================

NotificationType = Literal['analysis', 'alert', 'system']
NotificationStatus = Literal['unread', 'read']


class NotificationCreate(BaseModel):
    """创建通知请求"""
    user_id: str
    type: NotificationType
    title: str
    content: Optional[str] = None
    link: Optional[str] = None
    source: Optional[str] = None
    severity: Optional[Literal['info', 'success', 'warning', 'error']] = None
    metadata: Optional[Dict[str, Any]] = None


class NotificationDB(BaseModel):
    """通知数据库模型"""
    id: Optional[str] = Field(default=None)
    user_id: str
    type: NotificationType
    title: str
    content: Optional[str] = None
    link: Optional[str] = None
    source: Optional[str] = None
    severity: Optional[Literal['info', 'success', 'warning', 'error']] = 'info'
    status: NotificationStatus = 'unread'
    created_at: datetime = Field(default_factory=now_tz)
    metadata: Optional[Dict[str, Any]] = None


class NotificationOut(BaseModel):
    """通知输出模型"""
    id: str
    type: NotificationType
    title: str
    content: Optional[str] = None
    link: Optional[str] = None
    source: Optional[str] = None
    status: NotificationStatus
    created_at: datetime

    @field_serializer('created_at')
    def serialize_datetime(self, dt: Optional[datetime], _info) -> Optional[str]:
        """序列化 datetime 为 ISO 8601 格式，保留时区信息"""
        if dt:
            return dt.isoformat()
        return None


class NotificationList(BaseModel):
    """通知列表响应"""
    items: List[NotificationOut]
    total: int = 0
    page: int = 1
    page_size: int = 20
