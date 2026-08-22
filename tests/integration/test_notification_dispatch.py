import pytest
from app.models.notification import NotificationPayload, NotificationEvent, NotificationSeverity, NotificationChannel
from app.repositories.notification_repository import NotificationRepository
from app.services.notifications.notification_service import NotificationService


@pytest.mark.asyncio
async def test_integration_notification_dispatch():
    fake_docs = []

    class MockCollection:
        async def insert_one(self, doc):
            fake_docs.append(dict(doc))
            return True

        async def find_one(self, query):
            for d in fake_docs:
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
                    fake_docs.append(new_doc)
                    return True
                return False
            if "$set" in update:
                for k, v in update["$set"].items():
                    doc[k] = v
            return True

    class MockDB(dict):
        def __getitem__(self, item):
            if item not in self:
                self[item] = MockCollection()
            return super().__getitem__(item)

    db = MockDB()
    repo = NotificationRepository(db=db)
    service = NotificationService(repo=repo, is_test_env=True)

    payload = NotificationPayload(
        event_id="evt_integ_1",
        user_id="u_integ",
        event_type=NotificationEvent.BACKTEST_COMPLETED,
        severity=NotificationSeverity.INFO,
        title="Backtest Done",
        message="Backtest completed with CAGR 25%"
    )

    logs = await service.dispatch(payload)
    assert len(logs) > 0
    assert any(l.status == "success" for l in logs)
