"""Application service for the authenticated alert-management HTTP API."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import uuid4

from pymongo import ASCENDING, DESCENDING, ReturnDocument

from app.models.alert import (
    AlertAction,
    AlertChannel,
    AlertEvent,
    AlertMarket,
    AlertQualityStatus,
    AlertRule,
    AlertRuleOrigin,
    AlertSeverity,
    AllAlertCondition,
    AnyAlertCondition,
    CompareAlertCondition,
    CrossAlertCondition,
    FactorOperand,
    NotAlertCondition,
    PaperAccountScope,
    PaperPositionScope,
    StrategyUniverseScope,
    WatchlistScope,
)
from app.models.notification import NotificationCreate
from app.repositories.alert_repository import (
    AlertRepository,
    AlertRepositoryConflict,
)
from app.services.alerts.evaluator import (
    AlertSnapshotRequest,
    MongoAlertScopeResolver,
    MongoAlertSnapshotLoader,
    PureAlertEvaluator,
    _market_date,
)
from app.services.alerts.event_service import _threshold, _unit
from app.services.alerts.planner import rule_dependencies
from app.services.alerts.rule_validator import AlertRuleValidator
from app.services.calendars.market_calendar import MarketCalendarService
from app.services.notifications_service import NotificationsService


class AlertApiError(RuntimeError):
    """Stable API failure independent from FastAPI."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int,
        details: Any | None = None,
    ):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details
        super().__init__(message)


class AlertApiService:
    TOMBSTONES_COLLECTION = "alert_rule_tombstones"
    MAX_RULES_PER_USER = 200

    def __init__(
        self,
        database,
        *,
        repository: AlertRepository | None = None,
        validator: AlertRuleValidator | None = None,
        scope_resolver=None,
        snapshot_loader=None,
        evaluator: PureAlertEvaluator | None = None,
        notifications: NotificationsService | None = None,
        clock=None,
        max_rules_per_user: int = MAX_RULES_PER_USER,
    ):
        self.database = database
        self.validator = validator or AlertRuleValidator()
        self.repository = repository or AlertRepository(
            database, validator=self.validator
        )
        self.scope_resolver = scope_resolver or MongoAlertScopeResolver(database)
        self.snapshot_loader = snapshot_loader or MongoAlertSnapshotLoader(database)
        self.evaluator = evaluator or PureAlertEvaluator()
        self.notifications = notifications or NotificationsService(database)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.max_rules_per_user = max_rules_per_user
        self._indexes_ready = False

    async def ensure_indexes(self) -> None:
        if self._indexes_ready:
            return
        await self.repository.ensure_indexes()
        tombstones = self.database[self.TOMBSTONES_COLLECTION]
        await tombstones.create_index(
            [("rule_id", ASCENDING)], unique=True, name="alert_tombstone_rule"
        )
        await tombstones.create_index(
            [("user_id", ASCENDING), ("deleted_at", DESCENDING)],
            name="alert_tombstone_owner_deleted",
        )
        self._indexes_ready = True

    async def create_rule(self, *, user_id: str, payload: dict[str, Any]) -> AlertRule:
        await self.ensure_indexes()
        if await self._active_rule_count(user_id) >= self.max_rules_per_user:
            raise AlertApiError(
                "ALERT_QUOTA_EXCEEDED",
                "Alert rule quota has been reached",
                status_code=409,
            )
        candidate = dict(payload)
        self._enforce_public_rule(candidate)
        supplied_owner = candidate.get("user_id")
        if supplied_owner not in (None, user_id):
            raise AlertApiError(
                "ALERT_RULE_FORBIDDEN", "Cannot create a rule for another user", status_code=403
            )
        created_at = self._now()
        candidate.update(
            user_id=user_id,
            version=1,
            condition_version=1,
            origin=AlertRuleOrigin.USER.value,
            action=AlertAction.NOTIFY_ONLY.value,
            automation_id=None,
            paper_account_id=None,
            created_at=created_at,
            updated_at=created_at,
        )
        rule = self._validate_rule(candidate)
        if rule.enabled:
            await self._validate_dependencies(rule)
        if await self.database[self.TOMBSTONES_COLLECTION].find_one(
            {"rule_id": rule.rule_id}
        ):
            raise AlertApiError(
                "ALERT_RULE_VERSION_CONFLICT",
                "A deleted rule already uses this identifier",
                status_code=409,
            )
        try:
            return await self.repository.create_rule(rule)
        except AlertRepositoryConflict as exc:
            raise self._version_conflict() from exc

    async def list_rules(
        self,
        *,
        user_id: str,
        page: int,
        page_size: int,
        enabled: bool | None = None,
    ) -> dict[str, Any]:
        await self.ensure_indexes()
        deleted = await self._deleted_ids(user_id)
        query: dict[str, Any] = {"user_id": user_id}
        if deleted:
            query["rule_id"] = {"$nin": tuple(deleted)}
        if enabled is not None:
            query["enabled"] = enabled
        collection = self.database[self.repository.RULES_COLLECTION]
        total = await collection.count_documents(query)
        cursor = (
            collection.find(query)
            .sort([("updated_at", DESCENDING), ("rule_id", ASCENDING)])
            .skip((page - 1) * page_size)
            .limit(page_size)
        )
        items = [
            self.repository._parse(AlertRule, item).model_dump(mode="json")
            async for item in cursor
        ]
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    async def get_rule_detail(self, *, user_id: str, rule_id: str) -> dict[str, Any]:
        rule = await self._owned_rule(user_id, rule_id)
        states = await self._documents(
            self.repository.STATES_COLLECTION,
            {"user_id": user_id, "rule_id": rule_id},
            sort=[("last_evaluated_at", DESCENDING), ("scope_key", ASCENDING)],
            limit=100,
        )
        events = await self._documents(
            self.repository.EVENTS_COLLECTION,
            {"user_id": user_id, "rule_id": rule_id},
            sort=[("created_at", DESCENDING), ("event_id", DESCENDING)],
            limit=20,
        )
        return {
            "rule": rule.model_dump(mode="json"),
            "states": [self._public_document(item) for item in states],
            "recent_events": [
                self.repository._parse(AlertEvent, item).model_dump(mode="json")
                for item in events
            ],
        }

    async def update_rule(
        self,
        *,
        user_id: str,
        rule_id: str,
        expected_version: int,
        payload: dict[str, Any],
    ) -> AlertRule:
        current = await self._owned_rule(user_id, rule_id)
        if current.version != expected_version:
            raise self._version_conflict(current.version)
        self._enforce_immutable_update(current, payload)
        immutable = {
            "rule_id": current.rule_id,
            "user_id": current.user_id,
            "origin": current.origin.value,
            "action": current.action.value,
            "automation_id": current.automation_id,
            "paper_account_id": current.paper_account_id,
            "version": current.version,
            "condition_version": current.condition_version,
            "created_at": current.created_at,
            "updated_at": current.updated_at,
            "state": current.state.model_dump(mode="python"),
        }
        merged = current.model_dump(mode="python")
        merged.update(payload)
        merged.update(immutable)
        proposed = self._validate_rule(merged)
        if proposed.enabled:
            await self._validate_dependencies(proposed)
        try:
            updated, _ = await self.repository.update_rule(
                proposed,
                user_id=user_id,
                expected_version=expected_version,
                updated_at=self._now(),
            )
            return updated
        except AlertRepositoryConflict as exc:
            raise self._version_conflict() from exc

    async def set_enabled(
        self,
        *,
        user_id: str,
        rule_id: str,
        expected_version: int,
        enabled: bool,
    ) -> AlertRule:
        current = await self._owned_rule(user_id, rule_id)
        if current.version != expected_version:
            raise self._version_conflict(current.version)
        proposed = current.model_copy(update={"enabled": enabled})
        proposed = self._validate_rule(proposed)
        if enabled:
            await self._validate_dependencies(proposed)
        try:
            updated, _ = await self.repository.update_rule(
                proposed,
                user_id=user_id,
                expected_version=expected_version,
                updated_at=self._now(),
            )
            return updated
        except AlertRepositoryConflict as exc:
            raise self._version_conflict() from exc

    async def delete_rule(
        self, *, user_id: str, rule_id: str, expected_version: int
    ) -> dict[str, Any]:
        await self.ensure_indexes()
        current = await self._owned_rule(user_id, rule_id)
        if current.version != expected_version:
            raise self._version_conflict(current.version)
        if current.enabled:
            current = await self.set_enabled(
                user_id=user_id,
                rule_id=rule_id,
                expected_version=expected_version,
                enabled=False,
            )
        deleted_at = self._now()
        await self.database[self.TOMBSTONES_COLLECTION].update_one(
            {"rule_id": rule_id, "user_id": user_id},
            {
                "$setOnInsert": {
                    "rule_id": rule_id,
                    "user_id": user_id,
                    "deleted_at": deleted_at,
                    "last_version": current.version,
                }
            },
            upsert=True,
        )
        return {
            "rule_id": rule_id,
            "deleted_at": deleted_at.isoformat(),
            "last_version": current.version,
            "events_retained": True,
        }

    def validate_payload(self, *, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        candidate = dict(payload)
        candidate.setdefault("user_id", user_id)
        if candidate.get("user_id") != user_id:
            raise AlertApiError(
                "ALERT_RULE_FORBIDDEN", "Cannot validate another user's rule", status_code=403
            )
        try:
            self._enforce_public_rule(candidate)
        except AlertApiError as exc:
            return {
                "valid": False,
                "rule": None,
                "errors": [{"code": exc.code, "message": exc.message, "path": "action"}],
                "warnings": [],
                "error_code": exc.code,
            }
        report = self.validator.validate(candidate)
        return {
            "valid": report.valid,
            "rule": report.rule.model_dump(mode="json") if report.rule else None,
            "errors": [issue.__dict__ for issue in report.errors],
            "warnings": [issue.__dict__ for issue in report.warnings],
            "error_code": None if report.valid else self._validation_code(payload, report.errors),
        }

    async def preview(self, *, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        candidate = dict(payload)
        candidate.setdefault("user_id", user_id)
        if candidate.get("user_id") != user_id:
            raise AlertApiError(
                "ALERT_RULE_FORBIDDEN", "Cannot preview another user's rule", status_code=403
            )
        self._enforce_public_rule(candidate)
        rule = self._validate_rule(candidate)
        evaluated_at = self._now()
        try:
            resolution = await self.scope_resolver.resolve(
                rule, evaluated_at=evaluated_at
            )
            targets = tuple((user_id, symbol) for symbol in resolution.targets)
            observations = await self.snapshot_loader.load(
                AlertSnapshotRequest(
                    market=rule.market,
                    evaluated_at=evaluated_at,
                    rules=(rule,),
                    targets=targets,
                    dependencies=rule_dependencies(rule),
                )
            )
        except AlertApiError:
            raise
        except Exception as exc:
            raise AlertApiError(
                "ALERT_DEPENDENCY_UNAVAILABLE",
                "Alert preview dependencies are unavailable",
                status_code=503,
            ) from exc
        market_date = _market_date(rule.market, evaluated_at, MarketCalendarService)
        results = []
        for symbol in resolution.targets:
            observation = observations.get((user_id, symbol))
            if observation is None:
                continue
            evaluation = self.evaluator.evaluate(
                rule,
                observation,
                evaluated_at=evaluated_at,
                market_date=market_date,
            )
            results.append(
                {
                    "symbol": symbol,
                    "condition_state": evaluation.condition_state.value,
                    "value": evaluation.value,
                    "quote_time": observation.quote_time.isoformat(),
                    "ingested_at": observation.ingested_at.isoformat(),
                    "evaluated_at": evaluation.evaluated_at.isoformat(),
                    "source": observation.source,
                    "quality_status": observation.quality_status.value,
                }
            )
        return {
            "rule_id": rule.rule_id,
            "evaluated_at": evaluated_at.isoformat(),
            "universe_snapshot_id": resolution.universe_snapshot_id,
            "symbols_checksum": resolution.symbols_checksum,
            "results": results,
            "state_persisted": False,
            "notification_sent": False,
        }

    async def send_test_notification(self, *, user_id: str, rule_id: str) -> dict[str, Any]:
        rule = await self._owned_rule(user_id, rule_id)
        now = self._now()
        symbol = getattr(rule.scope, "symbol", None)
        test_event_id = f"test:{uuid4()}"
        metadata = {
            "alert_event_id": test_event_id,
            "rule_id": rule.rule_id,
            "rule_version": rule.version,
            "market": rule.market.value,
            "symbol": symbol,
            "stock_name": symbol,
            "trigger_type": rule.alert_type.value,
            "severity": rule.severity.value,
            "observed_value": None,
            "threshold": _threshold(rule),
            "unit": _unit(rule),
            "quote_time": now.isoformat(),
            "evaluated_at": now.isoformat(),
            "latency_seconds": "0",
            "source": "alert_test",
            "quality_status": AlertQualityStatus.VALID.value,
            "campaign_id": None,
            "position_id": getattr(rule.scope, "position_id", None),
            "deep_link": f"/alerts/rules/{rule.rule_id}",
            "is_test": True,
        }
        notification_id = await self.notifications.create_and_publish(
            NotificationCreate(
                user_id=user_id,
                type="alert",
                title=f"[测试] {rule.name}",
                content="这是一条测试通知，不代表真实市场条件已触发。",
                link=metadata["deep_link"],
                source="alert_test",
                severity={
                    AlertSeverity.INFO: "info",
                    AlertSeverity.WARNING: "warning",
                    AlertSeverity.CRITICAL: "error",
                }[rule.severity],
                metadata=metadata,
            ),
            publish_realtime=AlertChannel.WEBSOCKET in rule.channels,
        )
        return {
            "notification_id": notification_id,
            "test_event_id": test_event_id,
            "is_test": True,
        }

    async def list_events(
        self,
        *,
        user_id: str,
        page: int,
        page_size: int,
        rule_id: str | None = None,
        symbol: str | None = None,
        severity: str | None = None,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> dict[str, Any]:
        query: dict[str, Any] = {"user_id": user_id}
        if rule_id:
            query["rule_id"] = rule_id
        if symbol:
            query["symbol"] = symbol
        if severity:
            query["severity"] = severity
        if start_at or end_at:
            created: dict[str, str] = {}
            if start_at:
                created["$gte"] = start_at.astimezone(timezone.utc).isoformat()
            if end_at:
                created["$lte"] = end_at.astimezone(timezone.utc).isoformat()
            query["created_at"] = created
        collection = self.database[self.repository.EVENTS_COLLECTION]
        total = await collection.count_documents(query)
        cursor = (
            collection.find(query)
            .sort([("created_at", DESCENDING), ("event_id", DESCENDING)])
            .skip((page - 1) * page_size)
            .limit(page_size)
        )
        items = [
            self.repository._parse(AlertEvent, item).model_dump(mode="json")
            async for item in cursor
        ]
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    async def acknowledge_event(self, *, user_id: str, event_id: str) -> AlertEvent:
        collection = self.database[self.repository.EVENTS_COLLECTION]
        document = await collection.find_one({"event_id": event_id, "user_id": user_id})
        if document is None:
            other = await collection.find_one({"event_id": event_id}, {"user_id": 1})
            if other is not None:
                raise AlertApiError(
                    "ALERT_RULE_FORBIDDEN", "Alert event belongs to another user", status_code=403
                )
            raise AlertApiError(
                "ALERT_RULE_NOT_FOUND", "Alert event was not found", status_code=404
            )
        event = self.repository._parse(AlertEvent, document)
        if event.severity != AlertSeverity.CRITICAL:
            raise AlertApiError(
                "ALERT_INVALID_CONDITION",
                "Only critical alert events can be acknowledged",
                status_code=409,
            )
        if event.acknowledged_at is not None:
            return event
        updated = await collection.find_one_and_update(
            {
                "event_id": event_id,
                "user_id": user_id,
                "severity": AlertSeverity.CRITICAL.value,
                "acknowledged_at": None,
            },
            {"$set": {"acknowledged_at": self._now().isoformat()}},
            return_document=ReturnDocument.AFTER,
        )
        if updated is None:
            updated = await collection.find_one({"event_id": event_id, "user_id": user_id})
        return self.repository._parse(AlertEvent, updated)

    async def health(self, *, user_id: str) -> dict[str, Any]:
        now = self._now()
        enabled_rules = await self.database[self.repository.RULES_COLLECTION].count_documents(
            {"user_id": user_id, "enabled": True}
        )
        recent_events = await self._documents(
            self.repository.EVENTS_COLLECTION,
            {"user_id": user_id},
            sort=[("created_at", DESCENDING)],
            limit=100,
        )
        runs = await self._documents(
            "alert_evaluation_runs", {}, sort=[("started_at", DESCENDING)], limit=50
        )
        latencies = []
        for item in recent_events:
            try:
                latencies.append(float(item.get("latency_seconds", 0)))
            except (TypeError, ValueError):
                pass
        failures = sum(item.get("status") in {"failed", "cancelled"} for item in runs)
        latest_quote = await self.database["market_quotes"].find_one(
            {}, sort=[("ingested_at", DESCENDING), ("updated_at", DESCENDING)]
        )
        return {
            "status": "degraded" if failures else "healthy",
            "checked_at": now.isoformat(),
            "owner": {
                "enabled_rule_count": enabled_rules,
                "recent_event_count": len(recent_events),
            },
            "evaluation_batches": {
                "recent_count": len(runs),
                "failure_count": failures,
                "last_status": runs[0].get("status") if runs else None,
                "last_completed_at": runs[0].get("completed_at") if runs else None,
            },
            "latency_seconds": {
                "sample_count": len(latencies),
                "average": sum(latencies) / len(latencies) if latencies else None,
                "maximum": max(latencies) if latencies else None,
            },
            "data_sources": {
                "market_quotes": {
                    "available": latest_quote is not None,
                    "source": (latest_quote or {}).get("source")
                    or (latest_quote or {}).get("data_source"),
                    "last_ingested_at": (latest_quote or {}).get("ingested_at")
                    or (latest_quote or {}).get("updated_at"),
                }
            },
        }

    async def _owned_rule(self, user_id: str, rule_id: str) -> AlertRule:
        deleted = await self.database[self.TOMBSTONES_COLLECTION].find_one(
            {"rule_id": rule_id, "user_id": user_id}
        )
        if deleted is not None:
            raise AlertApiError(
                "ALERT_RULE_NOT_FOUND", "Alert rule was not found", status_code=404
            )
        rule = await self.repository.get_rule(rule_id, user_id=user_id)
        if rule is not None:
            return rule
        other = await self.database[self.repository.RULES_COLLECTION].find_one(
            {"rule_id": rule_id}, {"user_id": 1}
        )
        if other is not None:
            raise AlertApiError(
                "ALERT_RULE_FORBIDDEN", "Alert rule belongs to another user", status_code=403
            )
        raise AlertApiError(
            "ALERT_RULE_NOT_FOUND", "Alert rule was not found", status_code=404
        )

    async def _active_rule_count(self, user_id: str) -> int:
        deleted = await self._deleted_ids(user_id)
        query: dict[str, Any] = {"user_id": user_id}
        if deleted:
            query["rule_id"] = {"$nin": tuple(deleted)}
        return await self.database[self.repository.RULES_COLLECTION].count_documents(query)

    async def _deleted_ids(self, user_id: str) -> set[str]:
        cursor = self.database[self.TOMBSTONES_COLLECTION].find(
            {"user_id": user_id}, {"rule_id": 1}
        )
        return {str(item["rule_id"]) async for item in cursor}

    async def _validate_dependencies(self, rule: AlertRule) -> None:
        try:
            resolution = await self.scope_resolver.resolve(rule, evaluated_at=self._now())
        except Exception as exc:
            raise AlertApiError(
                "ALERT_DEPENDENCY_UNAVAILABLE",
                "Alert rule scope dependency is unavailable",
                status_code=409,
            ) from exc
        dynamic_scope = isinstance(
            rule.scope, (StrategyUniverseScope, PaperPositionScope)
        ) or (isinstance(rule.scope, WatchlistScope) and rule.scope.watchlist_id is not None)
        if dynamic_scope and not resolution.targets:
            raise AlertApiError(
                "ALERT_DEPENDENCY_UNAVAILABLE",
                "Alert rule scope resolves to no available targets",
                status_code=409,
            )
        if isinstance(rule.scope, PaperAccountScope):
            account = await self.database["paper_accounts"].find_one(
                {"user_id": rule.user_id, "account_id": rule.scope.account_id}
            )
            if account is None:
                raise AlertApiError(
                    "ALERT_DEPENDENCY_UNAVAILABLE",
                    "Paper account dependency is unavailable",
                    status_code=409,
                )
        for factor_id, version in self._factor_references(rule):
            job = await self.database["factor_jobs"].find_one(
                {
                    "user_id": rule.user_id,
                    "status": {"$in": ("completed", "ready")},
                    "request.factors": {
                        "$elemMatch": {"factor_id": factor_id, "version": version}
                    },
                }
            )
            if job is None:
                raise AlertApiError(
                    "ALERT_DEPENDENCY_UNAVAILABLE",
                    f"Factor dependency {factor_id}@{version} is unavailable",
                    status_code=409,
                )

    def _validate_rule(self, payload: AlertRule | dict[str, Any]) -> AlertRule:
        raw = payload.model_dump(mode="python") if isinstance(payload, AlertRule) else payload
        report = self.validator.validate(raw)
        if report.valid:
            assert report.rule is not None
            return report.rule
        code = self._validation_code(raw, report.errors)
        raise AlertApiError(
            code,
            "Alert rule validation failed",
            status_code=422,
            details=[issue.__dict__ for issue in report.errors],
        )

    @staticmethod
    def _enforce_public_rule(payload: dict[str, Any]) -> None:
        """Keep internal automation and system rules out of the user HTTP API."""

        forbidden = (
            payload.get("origin") not in (None, AlertRuleOrigin.USER, AlertRuleOrigin.USER.value)
            or payload.get("action") not in (None, AlertAction.NOTIFY_ONLY, AlertAction.NOTIFY_ONLY.value)
            or payload.get("automation_id") not in (None, "")
            or payload.get("paper_account_id") not in (None, "")
        )
        if forbidden:
            raise AlertApiError(
                "ALERT_INVALID_CONDITION",
                "Public alert rules are notification-only user rules",
                status_code=422,
            )

    @staticmethod
    def _enforce_immutable_update(current: AlertRule, payload: dict[str, Any]) -> None:
        immutable = {
            "rule_id": current.rule_id,
            "user_id": current.user_id,
            "origin": current.origin.value,
            "action": current.action.value,
            "automation_id": current.automation_id,
            "paper_account_id": current.paper_account_id,
            "created_at": current.created_at,
            "condition_version": current.condition_version,
        }
        for field, expected in immutable.items():
            if field not in payload:
                continue
            supplied = payload[field]
            if isinstance(expected, datetime) and isinstance(supplied, str):
                try:
                    supplied = datetime.fromisoformat(supplied.replace("Z", "+00:00"))
                except ValueError:
                    pass
            if supplied != expected:
                raise AlertApiError(
                    "ALERT_RULE_VERSION_CONFLICT",
                    f"Alert rule field {field} is immutable",
                    status_code=409,
                )

    @staticmethod
    def _validation_code(payload: dict[str, Any], issues: Iterable[Any]) -> str:
        frequency = payload.get("frequency_seconds")
        if isinstance(frequency, (int, float)) and frequency < 30:
            return "ALERT_FREQUENCY_TOO_HIGH"
        if any(
            (getattr(issue, "path", None) or "").startswith(("scope", "market", "user_id"))
            for issue in issues
        ):
            return "ALERT_INVALID_SCOPE"
        return "ALERT_INVALID_CONDITION"

    @staticmethod
    def _factor_references(rule: AlertRule) -> set[tuple[str, int]]:
        references: set[tuple[str, int]] = set()
        pending = [rule.trigger.condition]
        while pending:
            condition = pending.pop()
            operands = ()
            if isinstance(condition, (AllAlertCondition, AnyAlertCondition)):
                pending.extend(condition.children)
            elif isinstance(condition, NotAlertCondition):
                pending.append(condition.child)
            elif isinstance(condition, (CompareAlertCondition, CrossAlertCondition)):
                operands = (condition.left, condition.right)
                if isinstance(condition, CompareAlertCondition) and condition.upper is not None:
                    operands += (condition.upper,)
            for operand in operands:
                if isinstance(operand, FactorOperand):
                    references.add((operand.factor_id, operand.version))
        return references

    async def _documents(
        self,
        collection: str,
        query: dict[str, Any],
        *,
        sort: list[tuple[str, int]],
        limit: int,
    ) -> list[dict[str, Any]]:
        cursor = self.database[collection].find(query).sort(sort).limit(limit)
        return [item async for item in cursor]

    @staticmethod
    def _public_document(document: dict[str, Any]) -> dict[str, Any]:
        result = dict(document)
        result.pop("_id", None)
        result.pop("record_checksum", None)
        return result

    @staticmethod
    def _version_conflict(current_version: int | None = None) -> AlertApiError:
        details = {"current_version": current_version} if current_version else None
        return AlertApiError(
            "ALERT_RULE_VERSION_CONFLICT",
            "Alert rule version does not match",
            status_code=409,
            details=details,
        )

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("alert API clock must be timezone-aware")
        return value.astimezone(timezone.utc)
