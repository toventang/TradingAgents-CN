"""Pure tri-state transition logic for one alert rule and scope key."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.alert import (
    AlertEvaluationMode,
    AlertEventKind,
    AlertRule,
    AlertRuleState,
    AlertSeverity,
    AlertStateValue,
    ConditionState,
    stable_checksum,
    utc_now,
)


class AlertStateTransitionError(ValueError):
    pass


class AlertEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    condition_state: ConditionState
    value: AlertStateValue = None
    evaluated_at: datetime
    market_date: date

    @field_validator("evaluated_at")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")
        return value.astimezone(timezone.utc)


class AlertEventDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: AlertEventKind
    severity: AlertSeverity
    direction: str
    condition_state: ConditionState
    current_value: AlertStateValue = None
    previous_value: AlertStateValue = None
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class AlertStateTransition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    state: AlertRuleState
    events: tuple[AlertEventDraft, ...] = ()
    disable_rule: bool = False
    suppression_reasons: tuple[str, ...] = ()
    duplicate_evaluation: bool = False


def initial_alert_state(
    rule: AlertRule,
    *,
    scope_key: str,
    symbol: str | None = None,
    now: datetime | None = None,
) -> AlertRuleState:
    return AlertRuleState(
        rule_id=rule.rule_id,
        user_id=rule.user_id,
        scope_key=scope_key,
        symbol=symbol,
        rule_version=rule.version,
        condition_version=rule.condition_version,
        updated_at=now or utc_now(),
    )


def reset_alert_state(
    state: AlertRuleState,
    rule: AlertRule,
    *,
    now: datetime | None = None,
) -> AlertRuleState:
    if state.rule_id != rule.rule_id or state.user_id != rule.user_id:
        raise AlertStateTransitionError("state and rule ownership do not match")
    return initial_alert_state(
        rule,
        scope_key=state.scope_key,
        symbol=state.symbol,
        now=now,
    ).model_copy(update={"state_revision": state.state_revision + 1})


def build_event_fingerprint(
    rule: AlertRule,
    state: AlertRuleState,
    *,
    direction: str,
    evaluated_at: datetime,
) -> str:
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("evaluated_at must be timezone-aware")
    timestamp = evaluated_at.astimezone(timezone.utc)
    bucket = int(timestamp.timestamp()) // rule.frequency_seconds
    return stable_checksum(
        {
            "rule_id": rule.rule_id,
            "scope_key": state.scope_key,
            "symbol": state.symbol,
            "direction": direction,
            "condition_version": rule.condition_version,
            "time_bucket": bucket,
        }
    )


class AlertStateMachine:
    """Apply one already-evaluated true/false/unknown observation."""

    def transition(
        self,
        rule: AlertRule,
        state: AlertRuleState,
        evaluation: AlertEvaluation,
    ) -> AlertStateTransition:
        self._validate_identity(rule, state)
        if state.condition_version != rule.condition_version:
            state = reset_alert_state(state, rule, now=evaluation.evaluated_at)
        elif state.rule_version != rule.version:
            state = state.model_copy(update={"rule_version": rule.version})
        if (
            state.last_evaluated_at is not None
            and evaluation.evaluated_at < state.last_evaluated_at
        ):
            raise AlertStateTransitionError(
                "evaluations must not precede the last persisted evaluation"
            )
        if evaluation.evaluated_at == state.last_evaluated_at:
            return AlertStateTransition(
                state=state,
                suppression_reasons=("DUPLICATE_EVALUATION",),
                duplicate_evaluation=True,
            )
        if not rule.enabled:
            return AlertStateTransition(
                state=state,
                suppression_reasons=("RULE_DISABLED",),
            )
        if rule.expires_at is not None and evaluation.evaluated_at >= rule.expires_at:
            return AlertStateTransition(
                state=state,
                suppression_reasons=("RULE_EXPIRED",),
            )

        previous_value = state.last_value
        previous_condition = state.last_condition_state
        previous_determined = state.last_determined_state
        events_today = (
            state.events_today if state.market_date == evaluation.market_date else 0
        )
        base_updates = {
            "last_value": evaluation.value,
            "last_condition_state": evaluation.condition_state,
            "last_evaluated_at": evaluation.evaluated_at,
            "market_date": evaluation.market_date,
            "events_today": events_today,
            "rule_version": rule.version,
            "condition_version": rule.condition_version,
            "state_revision": state.state_revision + 1,
            "updated_at": evaluation.evaluated_at,
        }
        if evaluation.condition_state == ConditionState.UNKNOWN:
            return self._unknown(
                rule,
                state,
                evaluation,
                previous_value=previous_value,
                base_updates=base_updates,
            )
        if evaluation.condition_state == ConditionState.FALSE:
            return self._false(
                rule,
                state,
                evaluation,
                previous_value=previous_value,
                base_updates=base_updates,
            )
        return self._true(
            rule,
            state,
            evaluation,
            previous_value=previous_value,
            previous_condition=previous_condition,
            previous_determined=previous_determined,
            base_updates=base_updates,
        )

    @staticmethod
    def _validate_identity(rule: AlertRule, state: AlertRuleState) -> None:
        if rule.rule_id != state.rule_id or rule.user_id != state.user_id:
            raise AlertStateTransitionError("state and rule ownership do not match")

    def _unknown(
        self,
        rule: AlertRule,
        state: AlertRuleState,
        evaluation: AlertEvaluation,
        *,
        previous_value: AlertStateValue,
        base_updates: dict,
    ) -> AlertStateTransition:
        count = state.consecutive_unknown + 1
        updates = {
            **base_updates,
            "true_since": None,
            "false_since": None,
            "unknown_since": state.unknown_since
            if state.last_condition_state == ConditionState.UNKNOWN
            else evaluation.evaluated_at,
            "consecutive_true": 0,
            "consecutive_false": 0,
            "consecutive_unknown": count,
            "edge_pending": False,
        }
        event: AlertEventDraft | None = None
        suppressions: list[str] = []
        if count >= 3 and not state.health_unknown_reported:
            fingerprint = build_event_fingerprint(
                rule,
                state,
                direction="unknown_health",
                evaluated_at=evaluation.evaluated_at,
            )
            if base_updates["events_today"] >= rule.max_events_per_day:
                suppressions.append("DAILY_QUOTA_REACHED")
            elif fingerprint == state.last_event_fingerprint:
                suppressions.append("DUPLICATE_FINGERPRINT")
            else:
                event = AlertEventDraft(
                    kind=AlertEventKind.RULE_HEALTH,
                    severity=AlertSeverity.WARNING,
                    direction="unknown_health",
                    condition_state=ConditionState.UNKNOWN,
                    current_value=evaluation.value,
                    previous_value=previous_value,
                    fingerprint=fingerprint,
                )
                updates.update(
                    {
                        "events_today": base_updates["events_today"] + 1,
                        "last_event_fingerprint": fingerprint,
                    }
                )
            if event is not None:
                updates["health_unknown_reported"] = True
        next_state = state.model_copy(update=updates)
        return AlertStateTransition(
            state=next_state,
            events=(() if event is None else (event,)),
            suppression_reasons=tuple(suppressions),
        )

    def _false(
        self,
        rule: AlertRule,
        state: AlertRuleState,
        evaluation: AlertEvaluation,
        *,
        previous_value: AlertStateValue,
        base_updates: dict,
    ) -> AlertStateTransition:
        count = state.consecutive_false + 1
        updates = {
            **base_updates,
            "last_determined_state": ConditionState.FALSE,
            "true_since": None,
            "false_since": state.false_since
            if state.last_condition_state == ConditionState.FALSE
            else evaluation.evaluated_at,
            "unknown_since": None,
            "consecutive_true": 0,
            "consecutive_false": count,
            "consecutive_unknown": 0,
            "edge_pending": False,
            "health_unknown_reported": False,
        }
        event: AlertEventDraft | None = None
        suppressions: list[str] = []
        if state.active_event_open and rule.recovery_enabled:
            fingerprint = build_event_fingerprint(
                rule,
                state,
                direction="recovered",
                evaluated_at=evaluation.evaluated_at,
            )
            if base_updates["events_today"] >= rule.max_events_per_day:
                suppressions.append("DAILY_QUOTA_REACHED")
            elif fingerprint == state.last_event_fingerprint:
                suppressions.append("DUPLICATE_FINGERPRINT")
            else:
                event = AlertEventDraft(
                    kind=AlertEventKind.RECOVERED,
                    severity=rule.severity,
                    direction="recovered",
                    condition_state=ConditionState.FALSE,
                    current_value=evaluation.value,
                    previous_value=previous_value,
                    fingerprint=fingerprint,
                )
                updates.update(
                    {
                        "events_today": base_updates["events_today"] + 1,
                        "last_event_fingerprint": fingerprint,
                    }
                )
        updates["active_event_open"] = False
        next_state = state.model_copy(update=updates)
        return AlertStateTransition(
            state=next_state,
            events=(() if event is None else (event,)),
            suppression_reasons=tuple(suppressions),
        )

    def _true(
        self,
        rule: AlertRule,
        state: AlertRuleState,
        evaluation: AlertEvaluation,
        *,
        previous_value: AlertStateValue,
        previous_condition: ConditionState,
        previous_determined: ConditionState | None,
        base_updates: dict,
    ) -> AlertStateTransition:
        continuing_true = previous_condition == ConditionState.TRUE
        count = state.consecutive_true + 1 if continuing_true else 1
        true_since = state.true_since if continuing_true else evaluation.evaluated_at
        edge_pending = state.edge_pending if continuing_true else (
            previous_determined != ConditionState.TRUE
        )
        updates = {
            **base_updates,
            "last_determined_state": ConditionState.TRUE,
            "true_since": true_since,
            "false_since": None,
            "unknown_since": None,
            "consecutive_true": count,
            "consecutive_false": 0,
            "consecutive_unknown": 0,
            "edge_pending": edge_pending,
            "health_unknown_reported": False,
        }
        qualified = self._duration_qualified(rule, count, true_since, evaluation.evaluated_at)
        if rule.evaluation_mode == AlertEvaluationMode.LEVEL:
            eligible = qualified
        else:
            eligible = edge_pending and qualified
        if not eligible:
            return AlertStateTransition(state=state.model_copy(update=updates))

        fingerprint = build_event_fingerprint(
            rule,
            state,
            direction="triggered",
            evaluated_at=evaluation.evaluated_at,
        )
        suppressions: list[str] = []
        if state.cooldown_until is not None and evaluation.evaluated_at < state.cooldown_until:
            suppressions.append("COOLDOWN_ACTIVE")
        if base_updates["events_today"] >= rule.max_events_per_day:
            suppressions.append("DAILY_QUOTA_REACHED")
        if fingerprint == state.last_event_fingerprint:
            suppressions.append("DUPLICATE_FINGERPRINT")
        if suppressions:
            if rule.evaluation_mode != AlertEvaluationMode.LEVEL:
                updates["edge_pending"] = False
            return AlertStateTransition(
                state=state.model_copy(update=updates),
                suppression_reasons=tuple(suppressions),
            )

        event = AlertEventDraft(
            kind=AlertEventKind.TRIGGERED,
            severity=rule.severity,
            direction="triggered",
            condition_state=ConditionState.TRUE,
            current_value=evaluation.value,
            previous_value=previous_value,
            fingerprint=fingerprint,
        )
        updates.update(
            {
                "active_event_open": True,
                "edge_pending": False,
                "last_triggered_at": evaluation.evaluated_at,
                "cooldown_until": evaluation.evaluated_at
                + timedelta(seconds=rule.cooldown_seconds),
                "events_today": base_updates["events_today"] + 1,
                "last_event_fingerprint": fingerprint,
            }
        )
        return AlertStateTransition(
            state=state.model_copy(update=updates),
            events=(event,),
            disable_rule=rule.evaluation_mode == AlertEvaluationMode.ONCE,
        )

    @staticmethod
    def _duration_qualified(
        rule: AlertRule,
        consecutive_true: int,
        true_since: datetime,
        evaluated_at: datetime,
    ) -> bool:
        if rule.trigger.for_evaluations is not None:
            return consecutive_true >= rule.trigger.for_evaluations
        if rule.trigger.for_seconds is not None:
            return (
                evaluated_at - true_since
                >= timedelta(seconds=rule.trigger.for_seconds)
            )
        return True
