"""Atomic alert-state application and durable evaluation-run statistics."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pymongo import ASCENDING, DESCENDING, ReturnDocument

from app.models.alert import (
    AlertEvent,
    AlertQualityStatus,
    AlertRule,
    AlertRuleState,
    stable_checksum,
)
from app.repositories.alert_repository import (
    AlertRepository,
    AlertRepositoryConflict,
)
from app.services.alerts.state_machine import (
    AlertEvaluation,
    AlertStateMachine,
    AlertStateTransition,
    initial_alert_state,
)


class EvaluationRunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    SKIPPED_LOCKED = "skipped_locked"
    CANCELLED = "cancelled"
    FAILED = "failed"


class AlertEventEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    quote_time: datetime
    ingested_at: datetime
    source: str = Field(min_length=1, max_length=128)
    quality_status: AlertQualityStatus
    actual_symbols: tuple[str, ...] = ()
    universe_snapshot_id: str | None = None

    @field_validator("quote_time", "ingested_at")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("event evidence timestamps must be timezone-aware")
        return value.astimezone(timezone.utc)


class PersistedAlertEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    state: AlertRuleState
    transition: AlertStateTransition
    events: tuple[AlertEvent, ...] = ()
    created_event_count: int = Field(default=0, ge=0)


class AlertEvaluationRun(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str = Field(min_length=1, max_length=128)
    market: str = Field(min_length=1, max_length=16)
    frequency_seconds: int = Field(ge=30, le=86_400)
    time_bucket: int = Field(ge=0)
    owner_token: str | None = Field(default=None, max_length=128)
    status: EvaluationRunStatus = EvaluationRunStatus.RUNNING
    group_count: int = Field(default=0, ge=0)
    rule_count: int = Field(default=0, ge=0)
    target_count: int = Field(default=0, ge=0)
    evaluated_count: int = Field(default=0, ge=0)
    unknown_count: int = Field(default=0, ge=0)
    event_count: int = Field(default=0, ge=0)
    skipped_count: int = Field(default=0, ge=0)
    error_code: str | None = Field(default=None, max_length=128)
    started_at: datetime
    completed_at: datetime | None = None

    @field_validator("started_at", "completed_at")
    @classmethod
    def normalize_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("evaluation run timestamps must be timezone-aware")
        return value.astimezone(timezone.utc)


class AlertStateRepository:
    RUNS_COLLECTION = "alert_evaluation_runs"

    def __init__(
        self,
        db=None,
        *,
        alerts: AlertRepository | None = None,
        state_machine: AlertStateMachine | None = None,
        max_cas_attempts: int = 4,
    ):
        if max_cas_attempts < 1:
            raise ValueError("max_cas_attempts must be positive")
        self.alerts = alerts or AlertRepository(db)
        self.state_machine = state_machine or AlertStateMachine()
        self.max_cas_attempts = max_cas_attempts
        self._indexes_ready = False
        self._index_lock = asyncio.Lock()

    def get_db(self):
        return self.alerts.get_db()

    async def ensure_indexes(self) -> None:
        await self.alerts.ensure_indexes()
        if self._indexes_ready:
            return
        async with self._index_lock:
            if self._indexes_ready:
                return
            runs = self.get_db()[self.RUNS_COLLECTION]
            await runs.create_index(
                [("run_id", ASCENDING)],
                unique=True,
                name="alert_evaluation_run_id",
            )
            await runs.create_index(
                [
                    ("market", ASCENDING),
                    ("frequency_seconds", ASCENDING),
                    ("time_bucket", ASCENDING),
                ],
                unique=True,
                name="alert_evaluation_batch_identity",
            )
            await runs.create_index(
                [("status", ASCENDING), ("started_at", DESCENDING)],
                name="alert_evaluation_run_state_started",
            )
            self._indexes_ready = True

    async def list_enabled_rules(
        self,
        *,
        market: str,
        frequency_seconds: int,
        evaluated_at: datetime,
    ) -> tuple[AlertRule, ...]:
        query: dict[str, Any] = {
            "market": market,
            "frequency_seconds": frequency_seconds,
            "enabled": True,
            "$or": [
                {"expires_at": None},
                {"expires_at": {"$gt": _aware_utc(evaluated_at).isoformat()}},
            ],
        }
        cursor = self.get_db()[self.alerts.RULES_COLLECTION].find(query).sort(
            [("user_id", ASCENDING), ("rule_id", ASCENDING)]
        )
        documents = await cursor.to_list(length=None)
        return tuple(self.alerts._parse(AlertRule, item) for item in documents)

    async def apply(
        self,
        rule: AlertRule,
        *,
        scope_key: str,
        symbol: str | None,
        evaluation: AlertEvaluation,
        evidence: AlertEventEvidence,
    ) -> PersistedAlertEvaluation:
        for attempt in range(self.max_cas_attempts):
            persisted = await self.alerts.get_state(
                rule.rule_id,
                user_id=rule.user_id,
                scope_key=scope_key,
            )
            state = persisted or initial_alert_state(
                rule,
                scope_key=scope_key,
                symbol=symbol,
                now=evaluation.evaluated_at,
            )
            transition = self.state_machine.transition(rule, state, evaluation)
            try:
                if persisted is None:
                    saved = await self.alerts.create_state(transition.state)
                elif transition.state == persisted:
                    saved = persisted
                else:
                    saved = await self.alerts.replace_state(
                        transition.state,
                        expected_revision=persisted.state_revision,
                    )
            except AlertRepositoryConflict:
                if attempt + 1 == self.max_cas_attempts:
                    raise
                continue

            events: list[AlertEvent] = []
            created_count = 0
            for draft in transition.events:
                event = AlertEvent(
                    rule_id=rule.rule_id,
                    rule_version=rule.version,
                    condition_version=rule.condition_version,
                    user_id=rule.user_id,
                    scope_key=scope_key,
                    symbol=symbol,
                    kind=draft.kind,
                    severity=draft.severity,
                    direction=draft.direction,
                    condition_state=draft.condition_state,
                    current_value=draft.current_value,
                    previous_value=draft.previous_value,
                    quote_time=evidence.quote_time,
                    ingested_at=evidence.ingested_at,
                    evaluated_at=evaluation.evaluated_at,
                    source=evidence.source,
                    latency_seconds=Decimal(
                        str(
                            (
                                evaluation.evaluated_at - evidence.quote_time
                            ).total_seconds()
                        )
                    ),
                    quality_status=evidence.quality_status,
                    stale=evidence.quality_status == AlertQualityStatus.STALE,
                    actual_symbol_count=len(evidence.actual_symbols),
                    actual_symbols_checksum=stable_checksum(evidence.actual_symbols),
                    universe_snapshot_id=evidence.universe_snapshot_id,
                    fingerprint=draft.fingerprint,
                    created_at=evaluation.evaluated_at,
                )
                stored, created = await self.alerts.append_event(event)
                events.append(stored)
                created_count += int(created)
            if transition.disable_rule:
                try:
                    await self.alerts.disable_once(
                        rule.rule_id,
                        user_id=rule.user_id,
                        expected_version=rule.version,
                    )
                except AlertRepositoryConflict:
                    pass
            return PersistedAlertEvaluation(
                state=saved,
                transition=transition,
                events=tuple(events),
                created_event_count=created_count,
            )
        raise AssertionError("unreachable CAS retry loop")

    async def start_run(self, run: AlertEvaluationRun) -> AlertEvaluationRun:
        await self.ensure_indexes()
        key = {
            "market": run.market,
            "frequency_seconds": run.frequency_seconds,
            "time_bucket": run.time_bucket,
        }
        await self.get_db()[self.RUNS_COLLECTION].update_one(
            key,
            {"$setOnInsert": run.model_dump(mode="json")},
            upsert=True,
        )
        document = await self.get_db()[self.RUNS_COLLECTION].find_one(key)
        if document is None:
            raise RuntimeError("evaluation run was not persisted")
        return _parse_run(document)

    async def finish_run(
        self,
        run_id: str,
        *,
        status: EvaluationRunStatus,
        completed_at: datetime,
        group_count: int = 0,
        rule_count: int = 0,
        target_count: int = 0,
        evaluated_count: int = 0,
        unknown_count: int = 0,
        event_count: int = 0,
        skipped_count: int = 0,
        error_code: str | None = None,
    ) -> AlertEvaluationRun:
        document = await self.get_db()[self.RUNS_COLLECTION].find_one_and_update(
            {"run_id": run_id, "status": EvaluationRunStatus.RUNNING.value},
            {
                "$set": {
                    "status": status.value,
                    "completed_at": _aware_utc(completed_at).isoformat(),
                    "group_count": group_count,
                    "rule_count": rule_count,
                    "target_count": target_count,
                    "evaluated_count": evaluated_count,
                    "unknown_count": unknown_count,
                    "event_count": event_count,
                    "skipped_count": skipped_count,
                    "error_code": error_code,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if document is None:
            existing = await self.get_db()[self.RUNS_COLLECTION].find_one(
                {"run_id": run_id}
            )
            if existing is None:
                raise KeyError(f"unknown alert evaluation run: {run_id}")
            return _parse_run(existing)
        return _parse_run(document)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc)


def _parse_run(document: dict[str, Any]) -> AlertEvaluationRun:
    payload = dict(document)
    payload.pop("_id", None)
    return AlertEvaluationRun.model_validate(payload)
