import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from bson import ObjectId

from app.models.alert import (
    AlertCompareOperator,
    AlertEvent,
    AlertEventKind,
    AlertEvaluationMode,
    AlertMarket,
    AlertQualityStatus,
    AlertRule,
    AlertRuleOrigin,
    AlertRuleRevision,
    AlertSeverity,
    AlertTrigger,
    AlertType,
    CompareAlertCondition,
    ConditionState,
    ConstantOperand,
    CurrentValueOperand,
    MarketHoursSchedule,
    SymbolScope,
)
from app.models.notification import NotificationCreate
from app.routers.websocket_notifications import ConnectionManager, RedisNotificationRelay
from app.services.alerts.event_service import (
    AlertEventDeliveryService,
    AlertNotificationMetadata,
)
from app.services.notifications_service import NotificationsService

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]
NOW = datetime(2026, 8, 17, 2, 0, tzinfo=timezone.utc)


def dotted(document, key):
    value = document
    for part in key.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def matches(document, query):
    for key, expected in query.items():
        actual = dotted(document, key)
        if isinstance(expected, dict):
            if "$lt" in expected and not actual < expected["$lt"]:
                return False
            if "$in" in expected and actual not in expected["$in"]:
                return False
        elif actual != expected:
            return False
    return True


class Cursor:
    def __init__(self, documents):
        self.documents = [deepcopy(item) for item in documents]
        self.offset = 0
        self.maximum = None

    def sort(self, field, direction=None):
        spec = field if isinstance(field, list) else [(field, direction)]
        for name, order in reversed(spec):
            self.documents.sort(key=lambda item: dotted(item, name), reverse=order < 0)
        return self

    def skip(self, count):
        self.offset = count
        return self

    def limit(self, count):
        self.maximum = count
        return self

    def __aiter__(self):
        selected = self.documents[self.offset :]
        if self.maximum is not None:
            selected = selected[: self.maximum]
        self._iterator = iter(selected)
        return self

    async def __anext__(self):
        try:
            return next(self._iterator)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class Collection:
    def __init__(self):
        self.documents = []
        self.indexes = []

    async def create_index(self, keys, **options):
        self.indexes.append((keys, options))
        return options.get("name")

    async def update_one(self, query, update, upsert=False):
        for document in self.documents:
            if matches(document, query):
                for key, value in update.get("$set", {}).items():
                    document[key] = deepcopy(value)
                return SimpleNamespace(upserted_id=None, modified_count=1)
        if not upsert:
            return SimpleNamespace(upserted_id=None, modified_count=0)
        document = deepcopy(update.get("$setOnInsert", {}))
        document["_id"] = ObjectId()
        self.documents.append(document)
        return SimpleNamespace(upserted_id=document["_id"], modified_count=0)

    async def update_many(self, query, update):
        count = 0
        for document in self.documents:
            if matches(document, query):
                document.update(deepcopy(update.get("$set", {})))
                count += 1
        return SimpleNamespace(modified_count=count)

    async def insert_one(self, document):
        stored = deepcopy(document)
        stored["_id"] = ObjectId()
        self.documents.append(stored)
        return SimpleNamespace(inserted_id=stored["_id"])

    async def find_one(self, query, projection=None):
        return next(
            (deepcopy(item) for item in self.documents if matches(item, query)),
            None,
        )

    def find(self, query, projection=None):
        return Cursor(item for item in self.documents if matches(item, query))

    async def count_documents(self, query):
        return sum(matches(item, query) for item in self.documents)

    async def delete_many(self, query):
        before = len(self.documents)
        self.documents[:] = [item for item in self.documents if not matches(item, query)]
        return SimpleNamespace(deleted_count=before - len(self.documents))

class Database:
    def __init__(self):
        self.collections = {}

    def __getitem__(self, name):
        return self.collections.setdefault(name, Collection())


class Redis:
    def __init__(self, *, fails=False):
        self.fails = fails
        self.published = []

    async def publish(self, channel, payload):
        if self.fails:
            raise ConnectionError("redis unavailable")
        self.published.append((channel, payload))
        return 1


class Socket:
    def __init__(self):
        self.messages = []

    async def accept(self):
        return None

    async def send_text(self, message):
        self.messages.append(json.loads(message))


def alert_payload(user_id="user-a", event_id="event-1"):
    return NotificationCreate(
        user_id=user_id,
        type="alert",
        title="price threshold",
        content="fallback text",
        link="/stocks/CN/600000",
        source="alert_event",
        severity="warning",
        metadata={
            "alert_event_id": event_id,
            "rule_id": "rule-1",
            "rule_version": 1,
            "market": "CN",
            "symbol": "600000",
            "stock_name": "浦发银行",
            "trigger_type": "price_above",
            "severity": "warning",
            "observed_value": "11",
            "threshold": "10",
            "unit": "CNY",
            "quote_time": NOW.isoformat(),
            "evaluated_at": NOW.isoformat(),
            "latency_seconds": "0",
            "source": "market_quotes",
            "quality_status": "valid",
            "campaign_id": None,
            "position_id": None,
            "deep_link": "/stocks/CN/600000",
        },
    )


async def test_multi_instance_delivery_is_owner_scoped_and_idempotent():
    database = Database()
    redis = Redis()
    manager_a = ConnectionManager()
    manager_b = ConnectionManager()
    socket_a = Socket()
    socket_b = Socket()
    socket_other = Socket()
    await manager_a.connect(socket_a, "user-a")
    await manager_b.connect(socket_b, "user-a")
    await manager_b.connect(socket_other, "user-b")

    async def local_sender(user_id, message):
        await manager_a.send_personal_message(
            {"type": "notification", "data": message},
            user_id,
        )

    service = NotificationsService(
        database,
        redis,
        websocket_sender=local_sender,
        instance_id="instance-a",
        clock=lambda: NOW,
    )
    notification_id = await service.create_and_publish(alert_payload())
    replay_id = await service.create_and_publish(alert_payload())

    assert replay_id == notification_id
    assert len(database["notifications"].documents) == 1
    assert len(redis.published) == 1
    assert len(socket_a.messages) == 1
    assert socket_b.messages == []
    assert socket_other.messages == []

    relay_b = RedisNotificationRelay(manager_b, instance_id="instance-b")
    assert await relay_b.handle_message(redis.published[0][1]) is True
    relay_a = RedisNotificationRelay(manager_a, instance_id="instance-a")
    assert await relay_a.handle_message(redis.published[0][1]) is False

    assert len(socket_b.messages) == 1
    assert socket_other.messages == []
    message = socket_b.messages[0]
    assert message["type"] == "notification"
    assert message["data"]["metadata"]["alert_event_id"] == "event-1"
    assert "user_id" not in message["data"]

    fallback = await service.list("user-a", ntype="alert")
    assert fallback.total == 1
    assert fallback.items[0].metadata["rule_version"] == 1
    assert (await service.list("user-b")).total == 0

    conflicting = alert_payload().model_copy(update={"title": "different"})
    with pytest.raises(ValueError, match="different notification"):
        await service.create_and_publish(conflicting)


async def test_redis_failure_keeps_mongo_and_local_delivery():
    database = Database()
    delivered = []

    async def sender(user_id, message):
        delivered.append((user_id, message))

    service = NotificationsService(
        database,
        Redis(fails=True),
        websocket_sender=sender,
        clock=lambda: NOW,
    )
    await service.create_and_publish(alert_payload(event_id="event-fallback"))

    assert delivered[0][0] == "user-a"
    page = await service.list("user-a")
    assert page.items[0].metadata["alert_event_id"] == "event-fallback"

    with pytest.raises(ValueError, match="structured metadata"):
        await service.create_and_publish(
            NotificationCreate(
                user_id="user-a",
                type="alert",
                title="invalid",
            )
        )


def make_rule():
    return AlertRule(
        user_id="user-a",
        name="价格突破",
        alert_type=AlertType.PRICE_ABOVE,
        scope=SymbolScope(symbol="600000"),
        market=AlertMarket.CN,
        trigger=AlertTrigger(
            condition=CompareAlertCondition(
                left=CurrentValueOperand(),
                operator=AlertCompareOperator.GT,
                right=ConstantOperand(value=Decimal("10")),
            )
        ),
        evaluation_mode=AlertEvaluationMode.EDGE,
        frequency_seconds=60,
        active_schedule=MarketHoursSchedule(),
        origin=AlertRuleOrigin.USER,
        created_at=NOW,
        updated_at=NOW,
    )


class FakeAlerts:
    RULE_VERSIONS_COLLECTION = "alert_rule_versions"
    EVENTS_COLLECTION = "alert_events"

    def __init__(self, database):
        self.database = database

    def get_db(self):
        return self.database

    @staticmethod
    def _parse(model, document):
        payload = dict(document)
        payload.pop("_id", None)
        return model.model_validate(payload)


class CapturingNotifications:
    def __init__(self):
        self.calls = []

    async def create_and_publish(self, payload, *, publish_realtime=True):
        self.calls.append((payload, publish_realtime))
        return "notification-1"


async def test_alert_event_service_emits_complete_structured_contract():
    database = Database()
    rule = make_rule()
    revision = AlertRuleRevision(
        rule_id=rule.rule_id,
        user_id=rule.user_id,
        version=rule.version,
        condition_version=rule.condition_version,
        rule=rule,
        created_at=NOW,
    )
    database["alert_rule_versions"].documents.append(
        {**revision.model_dump(mode="json"), "_id": ObjectId()}
    )
    event = AlertEvent(
        rule_id=rule.rule_id,
        rule_version=1,
        condition_version=1,
        user_id="user-a",
        scope_key="CN:600000",
        symbol="600000",
        kind=AlertEventKind.TRIGGERED,
        severity=AlertSeverity.WARNING,
        direction="enter",
        condition_state=ConditionState.TRUE,
        current_value=Decimal("11"),
        previous_value=Decimal("9"),
        quote_time=NOW,
        ingested_at=NOW + timedelta(seconds=1),
        evaluated_at=NOW + timedelta(seconds=2),
        source="market_quotes",
        latency_seconds=Decimal("2"),
        quality_status=AlertQualityStatus.VALID,
        fingerprint="a" * 64,
        created_at=NOW + timedelta(seconds=2),
    )
    notifications = CapturingNotifications()
    service = AlertEventDeliveryService(
        alerts=FakeAlerts(database),
        notifications=notifications,
    )

    assert await service.deliver_event(event) == "notification-1"
    payload, realtime = notifications.calls[0]
    metadata = payload.metadata
    assert payload.type == "alert"
    assert realtime is True
    assert metadata is not None
    assert set(metadata) == set(AlertNotificationMetadata.model_fields)
    assert metadata["alert_event_id"] == event.event_id
    assert metadata["rule_id"] == rule.rule_id
    assert metadata["threshold"] == "10"
    assert metadata["observed_value"] == "11"
    assert metadata["latency_seconds"] == "2"

    with pytest.raises(LookupError, match="owner-scoped"):
        await service.deliver_event(event.model_copy(update={"user_id": "user-b"}))
