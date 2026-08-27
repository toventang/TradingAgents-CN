import pytest
from app.models.notification import (
    NotificationPayload,
    NotificationEvent,
    NotificationSeverity,
    NotificationChannel,
    ChannelConfig,
    NotificationPreference
)
from app.repositories.notification_repository import NotificationRepository
from app.services.notifications.notification_service import NotificationService


class FakeCollection:
    def __init__(self):
        self.docs = []

    async def insert_one(self, doc):
        self.docs.append(dict(doc))
        return True

    async def find_one(self, query):
        for d in self.docs:
            if all(d.get(k) == v for k, v in query.items()):
                return dict(d)
        return None

    async def update_one(self, query, update, upsert=False):
        doc = await self.find_one(query)
        if not doc:
            if upsert:
                new_doc = {}
                if "$set" in update:
                    new_doc.update(update["$set"])
                self.docs.append(new_doc)
                return True
            return False
        if "$set" in update:
            for k, v in update["$set"].items():
                doc[k] = v
        return True


class FakeDB(dict):
    def __getitem__(self, item):
        if item not in self:
            self[item] = FakeCollection()
        return super().__getitem__(item)


@pytest.mark.asyncio
async def test_notification_severity_and_retry_flow():
    fake_db = FakeDB()
    repo = NotificationRepository(db=fake_db)
    service = NotificationService(repo=repo, is_test_env=True)

    # Set user preferences
    pref = NotificationPreference(
        user_id="user_notif",
        channels={
            NotificationChannel.WEBHOOK: ChannelConfig(enabled=True, min_severity=NotificationSeverity.WARNING, target_address="https://example.com/webhook"),
            NotificationChannel.EMAIL: ChannelConfig(enabled=True, min_severity=NotificationSeverity.INFO, target_address="fail_user@example.com")
        }
    )
    await repo.update_preference(pref)

    # 1. Info event -> Webhook skipped due to min_severity=WARNING, Email fails 3 times
    payload_info = NotificationPayload(
        event_id="evt_01",
        user_id="user_notif",
        event_type=NotificationEvent.TASK_COMPLETED,
        severity=NotificationSeverity.INFO,
        title="Task Finished",
        message="Task Completed Successfully"
    )

    logs_info = await service.dispatch(payload_info)
    assert len(logs_info) == 1
    assert logs_info[0].channel == NotificationChannel.EMAIL
    assert logs_info[0].status == "failed"
    assert logs_info[0].attempts == 3

    # 2. Warning event -> Webhook dispatched successfully
    payload_warn = NotificationPayload(
        event_id="evt_02",
        user_id="user_notif",
        event_type=NotificationEvent.RISK_ALERT,
        severity=NotificationSeverity.WARNING,
        title="Risk Alert",
        message="Drawdown threshold reached"
    )

    logs_warn = await service.dispatch(payload_warn)
    webhook_log = next(l for l in logs_warn if l.channel == NotificationChannel.WEBHOOK)
    assert webhook_log.status == "success"
    assert webhook_log.attempts == 1
