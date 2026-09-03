"""Convert durable alert events into structured, owner-scoped notifications."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.alert import (
    AlertChannel,
    AlertEvent,
    AlertMarket,
    AlertRule,
    AlertRuleRevision,
    AlertSeverity,
    AllAlertCondition,
    AnyAlertCondition,
    CompareAlertCondition,
    ConstantOperand,
    CrossAlertCondition,
    NotAlertCondition,
    PaperPositionScope,
)
from app.models.notification import NotificationCreate
from app.repositories.alert_repository import AlertRepository
from app.services.notifications_service import NotificationsService


class AlertNotificationMetadata(BaseModel):
    """Stable metadata rendered by clients; text content is only a fallback."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    alert_event_id: str
    rule_id: str
    rule_version: int = Field(ge=1)
    market: str
    symbol: str | None
    stock_name: str | None
    trigger_type: str
    severity: str
    observed_value: str | bool | None
    threshold: str | list[str] | None
    unit: str
    quote_time: str
    evaluated_at: str
    latency_seconds: str
    source: str
    quality_status: str
    campaign_id: str | None
    position_id: str | None
    deep_link: str


class AlertEventDeliveryService:
    def __init__(
        self,
        db=None,
        *,
        notifications: NotificationsService | None = None,
        alerts: AlertRepository | None = None,
    ):
        self.alerts = alerts or AlertRepository(db)
        self.notifications = notifications or NotificationsService(db)

    def get_db(self):
        return self.alerts.get_db()

    async def deliver_event(self, event: AlertEvent) -> str:
        """Persist/publish one event once using its immutable rule revision."""

        revision_document = await self.get_db()[
            self.alerts.RULE_VERSIONS_COLLECTION
        ].find_one(
            {
                "rule_id": event.rule_id,
                "user_id": event.user_id,
                "version": event.rule_version,
            }
        )
        if revision_document is None:
            raise LookupError("owner-scoped alert rule revision does not exist")
        revision = self.alerts._parse(AlertRuleRevision, revision_document)
        if revision.condition_version != event.condition_version:
            raise ValueError("event condition version does not match rule revision")
        rule = revision.rule
        metadata = await self._metadata(event, rule)
        severity = {
            AlertSeverity.INFO: "info",
            AlertSeverity.WARNING: "warning",
            AlertSeverity.CRITICAL: "error",
        }[event.severity]
        title = self._title(event, rule, metadata.stock_name)
        content = self._fallback_content(event, rule, metadata)
        return await self.notifications.create_and_publish(
            NotificationCreate(
                user_id=event.user_id,
                type="alert",
                title=title,
                content=content,
                link=metadata.deep_link,
                source="alert_event",
                severity=severity,
                metadata=metadata.model_dump(mode="json"),
            ),
            publish_realtime=AlertChannel.WEBSOCKET in rule.channels,
        )

    async def deliver_pending(self, *, limit: int = 100) -> tuple[str, ...]:
        """Replay recent events safely; notification event IDs make this idempotent."""

        if limit < 1 or limit > 1000:
            raise ValueError("limit must be in 1..1000")
        cursor = self.get_db()[self.alerts.EVENTS_COLLECTION].find({}).sort(
            [("created_at", 1), ("event_id", 1)]
        ).limit(limit)
        identifiers: list[str] = []
        async for document in cursor:
            event = self.alerts._parse(AlertEvent, document)
            identifiers.append(await self.deliver_event(event))
        return tuple(identifiers)

    async def _metadata(
        self,
        event: AlertEvent,
        rule: AlertRule,
    ) -> AlertNotificationMetadata:
        stock_name = await self._stock_name(rule.market, event.symbol)
        deep_link = (
            f"/stocks/{rule.market.value}/{event.symbol}"
            f"?alert_event_id={event.event_id}"
            if event.symbol
            else f"/alerts/events/{event.event_id}"
        )
        position_id = (
            getattr(rule.scope, "position_id", None)
            if isinstance(rule.scope, PaperPositionScope)
            else None
        )
        return AlertNotificationMetadata(
            alert_event_id=event.event_id,
            rule_id=event.rule_id,
            rule_version=event.rule_version,
            market=rule.market.value,
            symbol=event.symbol,
            stock_name=stock_name,
            trigger_type=rule.alert_type.value,
            severity=event.severity.value,
            observed_value=_scalar(event.current_value),
            threshold=_threshold(rule),
            unit=_unit(rule),
            quote_time=event.quote_time.isoformat(),
            evaluated_at=event.evaluated_at.isoformat(),
            latency_seconds=str(event.latency_seconds),
            source=event.source,
            quality_status=event.quality_status.value,
            campaign_id=getattr(rule, "campaign_id", None),
            position_id=position_id,
            deep_link=deep_link,
        )

    async def _stock_name(
        self,
        market: AlertMarket,
        symbol: str | None,
    ) -> str | None:
        if symbol is None:
            return None
        document = await self.get_db()["stock_basic_info"].find_one(
            {
                "$and": [
                    {
                        "$or": [
                            {"symbol": symbol},
                            {"code": symbol},
                            {"stock_code": symbol},
                        ]
                    },
                    {
                        "$or": [
                            {"normalized_market": market.value},
                            {"market_code": market.value},
                            {"market": market.value},
                        ]
                    },
                ]
            },
            {"name": 1, "stock_name": 1},
        )
        if document is None:
            return symbol
        return str(document.get("name") or document.get("stock_name") or symbol)

    @staticmethod
    def _title(event: AlertEvent, rule: AlertRule, stock_name: str | None) -> str:
        target = stock_name or event.symbol or rule.name
        return f"{target}：{rule.name}"

    @staticmethod
    def _fallback_content(
        event: AlertEvent,
        rule: AlertRule,
        metadata: AlertNotificationMetadata,
    ) -> str:
        return (
            f"{rule.name} {event.kind.value}; value={metadata.observed_value}; "
            f"threshold={metadata.threshold}; evaluated_at={metadata.evaluated_at}"
        )


def _scalar(value: Any) -> str | bool | None:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def _threshold(rule: AlertRule) -> str | list[str] | None:
    values = []
    for condition in _walk_conditions(rule.trigger.condition):
        if isinstance(condition, CompareAlertCondition):
            operands = (condition.right, condition.upper)
        elif isinstance(condition, CrossAlertCondition):
            operands = (condition.right,)
        else:
            operands = ()
        for operand in operands:
            if isinstance(operand, ConstantOperand):
                value = str(operand.value)
                if value not in values:
                    values.append(value)
    if not values:
        return None
    return values[0] if len(values) == 1 else values


def _walk_conditions(condition):
    yield condition
    if isinstance(condition, (AllAlertCondition, AnyAlertCondition)):
        for child in condition.children:
            yield from _walk_conditions(child)
    elif isinstance(condition, NotAlertCondition):
        yield from _walk_conditions(condition.child)


def _unit(rule: AlertRule) -> str:
    value = rule.alert_type.value
    if value.startswith("price_") or value in {"gap_up", "gap_down"}:
        return {"CN": "CNY", "HK": "HKD", "US": "USD"}.get(
            rule.market.value,
            "value",
        )
    if "pct" in value or "drawdown" in value or "weight" in value:
        return "percent"
    if "volume" in value:
        return "shares"
    if "amount" in value or value == "cash_below":
        return {"CN": "CNY", "HK": "HKD", "US": "USD"}.get(
            rule.market.value,
            "currency",
        )
    return "value"
