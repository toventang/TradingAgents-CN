"""Owner-scoped persistence for versioned alert rules, states, and events."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.core.database import get_mongo_db
from app.models.alert import (
    AlertAction,
    AlertEvent,
    AlertRule,
    AlertRuleRevision,
    AlertRuleState,
    ConditionState,
    PaperPositionScope,
    StrategyUniverseScope,
    WatchlistScope,
    stable_checksum,
    utc_now,
)
from app.services.alerts.rule_validator import AlertRuleValidator


class AlertRepositoryConflict(RuntimeError):
    pass


class AlertRepositoryNotFound(LookupError):
    pass


class AlertRepository:
    RULES_COLLECTION = "alert_rules"
    RULE_VERSIONS_COLLECTION = "alert_rule_versions"
    STATES_COLLECTION = "alert_rule_states"
    EVENTS_COLLECTION = "alert_events"

    def __init__(self, db=None, *, validator: AlertRuleValidator | None = None):
        self._db = db
        self.validator = validator or AlertRuleValidator()
        self._indexes_ready = False
        self._index_lock = asyncio.Lock()

    def get_db(self):
        return self._db if self._db is not None else get_mongo_db()

    async def ensure_indexes(self) -> None:
        if self._indexes_ready:
            return
        async with self._index_lock:
            if self._indexes_ready:
                return
            database = self.get_db()
            await database[self.RULES_COLLECTION].create_index(
                [("rule_id", ASCENDING)], unique=True, name="alert_rule_id"
            )
            await database[self.RULES_COLLECTION].create_index(
                [("user_id", ASCENDING), ("updated_at", DESCENDING)],
                name="alert_rule_owner_updated",
            )
            await database[self.RULES_COLLECTION].create_index(
                [
                    ("user_id", ASCENDING),
                    ("enabled", ASCENDING),
                    ("market", ASCENDING),
                    ("frequency_seconds", ASCENDING),
                ],
                name="alert_rule_evaluation_scan",
            )
            await database[self.RULE_VERSIONS_COLLECTION].create_index(
                [("rule_id", ASCENDING), ("version", ASCENDING)],
                unique=True,
                name="alert_rule_version_identity",
            )
            await database[self.RULE_VERSIONS_COLLECTION].create_index(
                [("user_id", ASCENDING), ("rule_id", ASCENDING), ("version", DESCENDING)],
                name="alert_rule_version_owner_history",
            )
            await database[self.STATES_COLLECTION].create_index(
                [
                    ("user_id", ASCENDING),
                    ("rule_id", ASCENDING),
                    ("scope_key", ASCENDING),
                ],
                unique=True,
                name="alert_state_scope_identity",
            )
            await database[self.STATES_COLLECTION].create_index(
                [
                    ("user_id", ASCENDING),
                    ("rule_id", ASCENDING),
                    ("last_evaluated_at", DESCENDING),
                ],
                name="alert_state_owner_evaluated",
            )
            await database[self.EVENTS_COLLECTION].create_index(
                [("fingerprint", ASCENDING)],
                unique=True,
                name="alert_event_fingerprint",
            )
            await database[self.EVENTS_COLLECTION].create_index(
                [
                    ("user_id", ASCENDING),
                    ("created_at", DESCENDING),
                    ("event_id", DESCENDING),
                ],
                name="alert_event_owner_created",
            )
            await database[self.EVENTS_COLLECTION].create_index(
                [
                    ("user_id", ASCENDING),
                    ("rule_id", ASCENDING),
                    ("evaluated_at", DESCENDING),
                ],
                name="alert_event_rule_history",
            )
            self._indexes_ready = True

    async def create_rule(self, rule: AlertRule) -> AlertRule:
        await self.ensure_indexes()
        parsed = self.validator.validate_or_raise(rule)
        if parsed.version != 1 or parsed.condition_version != 1:
            raise AlertRepositoryConflict("new alert rule must start at version 1")
        collection = self.get_db()[self.RULES_COLLECTION]
        await collection.update_one(
            {"rule_id": parsed.rule_id, "user_id": parsed.user_id},
            {"$setOnInsert": parsed.model_dump(mode="json")},
            upsert=True,
        )
        existing = await self.get_rule(parsed.rule_id, user_id=parsed.user_id)
        if existing is None:
            raise RuntimeError("alert rule upsert did not persist a document")
        if existing != parsed:
            raise AlertRepositoryConflict("rule_id already exists with different content")
        await self._store_revision(existing)
        return existing

    async def get_rule(self, rule_id: str, *, user_id: str) -> AlertRule | None:
        document = await self.get_db()[self.RULES_COLLECTION].find_one(
            {"rule_id": rule_id, "user_id": user_id}
        )
        return None if document is None else self._parse(AlertRule, document)

    async def update_rule(
        self,
        proposed: AlertRule,
        *,
        user_id: str,
        expected_version: int,
        updated_at: datetime | None = None,
    ) -> tuple[AlertRule, bool]:
        await self.ensure_indexes()
        current = await self.get_rule(proposed.rule_id, user_id=user_id)
        if current is None:
            raise AlertRepositoryNotFound("owner-scoped alert rule does not exist")
        if current.version != expected_version:
            raise AlertRepositoryConflict(
                f"expected rule version {expected_version}, found {current.version}"
            )
        candidate, resets_state = self.validator.prepare_update(
            current, proposed, updated_at=updated_at
        )
        document = await self.get_db()[self.RULES_COLLECTION].find_one_and_update(
            {
                "rule_id": current.rule_id,
                "user_id": user_id,
                "version": expected_version,
            },
            {"$set": candidate.model_dump(mode="json")},
            return_document=ReturnDocument.AFTER,
        )
        if document is None:
            raise AlertRepositoryConflict("alert rule changed concurrently")
        updated = self._parse(AlertRule, document)
        await self._store_revision(updated)
        await self._synchronize_states(updated, reset=resets_state)
        return updated, resets_state

    async def disable_once(
        self, rule_id: str, *, user_id: str, expected_version: int
    ) -> AlertRule:
        current = await self.get_rule(rule_id, user_id=user_id)
        if current is None:
            raise AlertRepositoryNotFound("owner-scoped alert rule does not exist")
        proposed = current.model_copy(update={"enabled": False})
        updated, resets_state = await self.update_rule(
            proposed,
            user_id=user_id,
            expected_version=expected_version,
        )
        if resets_state:
            raise AssertionError("disabling a once rule must not reset condition state")
        return updated

    async def create_state(self, state: AlertRuleState) -> AlertRuleState:
        await self.ensure_indexes()
        rule = await self.get_rule(state.rule_id, user_id=state.user_id)
        if rule is None:
            raise AlertRepositoryNotFound("state rule does not exist for owner")
        if (
            state.rule_version != rule.version
            or state.condition_version != rule.condition_version
        ):
            raise AlertRepositoryConflict("state version does not match current rule")
        key = {
            "user_id": state.user_id,
            "rule_id": state.rule_id,
            "scope_key": state.scope_key,
        }
        collection = self.get_db()[self.STATES_COLLECTION]
        await collection.update_one(
            key, {"$setOnInsert": state.model_dump(mode="json")}, upsert=True
        )
        existing = await self.get_state(
            state.rule_id, user_id=state.user_id, scope_key=state.scope_key
        )
        if existing is None:
            raise RuntimeError("alert state upsert did not persist a document")
        if existing.model_dump(mode="json") != state.model_dump(mode="json"):
            raise AlertRepositoryConflict("scope state already exists with different content")
        return existing

    async def get_state(
        self, rule_id: str, *, user_id: str, scope_key: str
    ) -> AlertRuleState | None:
        document = await self.get_db()[self.STATES_COLLECTION].find_one(
            {"rule_id": rule_id, "user_id": user_id, "scope_key": scope_key}
        )
        return None if document is None else self._parse(AlertRuleState, document)

    async def replace_state(
        self,
        state: AlertRuleState,
        *,
        expected_revision: int,
    ) -> AlertRuleState:
        await self.ensure_indexes()
        if state.state_revision != expected_revision + 1:
            raise AlertRepositoryConflict("new state revision must increment by one")
        rule = await self.get_rule(state.rule_id, user_id=state.user_id)
        if rule is None:
            raise AlertRepositoryNotFound("state rule does not exist for owner")
        if (
            state.rule_version != rule.version
            or state.condition_version != rule.condition_version
        ):
            raise AlertRepositoryConflict("state version does not match current rule")
        document = await self.get_db()[self.STATES_COLLECTION].find_one_and_update(
            {
                "rule_id": state.rule_id,
                "user_id": state.user_id,
                "scope_key": state.scope_key,
                "state_revision": expected_revision,
            },
            {"$set": state.model_dump(mode="json")},
            return_document=ReturnDocument.AFTER,
        )
        if document is None:
            raise AlertRepositoryConflict("alert state changed concurrently")
        return self._parse(AlertRuleState, document)

    async def append_event(self, event: AlertEvent) -> tuple[AlertEvent, bool]:
        """Insert by unique fingerprint and return ``(event, created)``."""

        await self.ensure_indexes()
        rule = await self.get_rule(event.rule_id, user_id=event.user_id)
        if rule is None:
            raise AlertRepositoryNotFound("event rule does not exist for owner")
        revision_document = await self.get_db()[self.RULE_VERSIONS_COLLECTION].find_one(
            {
                "rule_id": event.rule_id,
                "user_id": event.user_id,
                "version": event.rule_version,
            }
        )
        if revision_document is None:
            raise AlertRepositoryConflict("event references an unknown rule version")
        revision = self._parse(AlertRuleRevision, revision_document)
        if revision.condition_version != event.condition_version:
            raise AlertRepositoryConflict(
                "event condition version does not match its rule revision"
            )
        dynamic_scope = (
            isinstance(rule.scope, StrategyUniverseScope)
            or isinstance(rule.scope, PaperPositionScope)
            or (
                isinstance(rule.scope, WatchlistScope)
                and rule.scope.watchlist_id is not None
            )
        )
        if dynamic_scope and (
            event.actual_symbols_checksum is None
            or event.universe_snapshot_id is None
        ):
            raise AlertRepositoryConflict(
                "dynamic-scope events require symbol summary and universe snapshot evidence"
            )
        if event.stale and revision.rule.action == AlertAction.PAPER_TRADE:
            raise AlertRepositoryConflict(
                "stale data cannot create an automated paper-trade event"
            )
        payload = event.model_dump(mode="json")
        checksum = stable_checksum(self._event_identity_payload(payload))
        collection = self.get_db()[self.EVENTS_COLLECTION]
        try:
            result = await collection.update_one(
                {"fingerprint": event.fingerprint},
                {"$setOnInsert": {**payload, "record_checksum": checksum}},
                upsert=True,
            )
        except DuplicateKeyError:
            # A concurrent worker won the unique-fingerprint upsert. The
            # canonical stored event is inspected below to distinguish a true
            # idempotent replay from a conflicting fingerprint reuse.
            result = None
        document = await collection.find_one({"fingerprint": event.fingerprint})
        if document is None or document.get("record_checksum") != checksum:
            raise AlertRepositoryConflict(
                "event fingerprint already exists with different content"
            )
        return (
            self._parse(AlertEvent, document),
            result is not None and result.upserted_id is not None,
        )

    @staticmethod
    def _event_identity_payload(payload: dict[str, Any]) -> dict[str, Any]:
        """Exclude generated/mutable fields from logical event idempotency."""

        return {
            key: value
            for key, value in payload.items()
            if key not in {"event_id", "acknowledged_at", "created_at"}
        }

    async def _store_revision(self, rule: AlertRule) -> None:
        revision = AlertRuleRevision(
            rule_id=rule.rule_id,
            user_id=rule.user_id,
            version=rule.version,
            condition_version=rule.condition_version,
            rule=rule,
        )
        key = {"rule_id": rule.rule_id, "version": rule.version}
        collection = self.get_db()[self.RULE_VERSIONS_COLLECTION]
        payload = revision.model_dump(mode="json")
        await collection.update_one(
            key, {"$setOnInsert": payload}, upsert=True
        )
        document = await collection.find_one(key)
        if document is None:
            raise RuntimeError("alert rule revision was not persisted")
        existing = self._parse(AlertRuleRevision, document)
        if existing.checksum != revision.checksum:
            raise AlertRepositoryConflict(
                "immutable alert rule revision contains different content"
            )

    async def _synchronize_states(self, rule: AlertRule, *, reset: bool) -> None:
        now = rule.updated_at.isoformat()
        if reset:
            values: dict[str, Any] = {
                "last_value": None,
                "last_condition_state": ConditionState.UNKNOWN.value,
                "last_determined_state": None,
                "true_since": None,
                "false_since": None,
                "unknown_since": None,
                "consecutive_true": 0,
                "consecutive_false": 0,
                "consecutive_unknown": 0,
                "last_evaluated_at": None,
                "last_triggered_at": None,
                "cooldown_until": None,
                "events_today": 0,
                "market_date": None,
                "last_event_fingerprint": None,
                "active_event_open": False,
                "edge_pending": False,
                "health_unknown_reported": False,
                "rule_version": rule.version,
                "condition_version": rule.condition_version,
                "updated_at": now,
            }
        else:
            values = {"rule_version": rule.version, "updated_at": now}
        await self.get_db()[self.STATES_COLLECTION].update_many(
            {"rule_id": rule.rule_id, "user_id": rule.user_id},
            {"$set": values, "$inc": {"state_revision": 1}},
        )

    @staticmethod
    def _parse(model, document):
        payload = dict(document)
        payload.pop("_id", None)
        payload.pop("record_checksum", None)
        return model.model_validate(payload)
