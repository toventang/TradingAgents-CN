from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import pytest

from app.models.alert import (
    AlertEventKind,
    AlertRule,
    ConditionState,
)
from app.services.alerts.state_machine import (
    AlertEvaluation,
    AlertStateMachine,
    AlertStateTransitionError,
    build_event_fingerprint,
    initial_alert_state,
)


NOW = datetime(2024, 1, 2, 9, 30, tzinfo=timezone.utc)
RULE_ID = str(UUID("00000000-0000-0000-0000-000000000040"))


def make_rule(**updates) -> AlertRule:
    values = {
        "rule_id": RULE_ID,
        "user_id": "owner",
        "name": "价格突破",
        "description": "价格超过阈值",
        "alert_type": "price_above",
        "scope": {"scope_type": "symbol", "symbol": "600000"},
        "market": "CN",
        "trigger": {
            "condition": {
                "type": "compare",
                "left": {"kind": "current_value"},
                "operator": "gt",
                "right": {"kind": "constant", "value": "10"},
            }
        },
        "evaluation_mode": "edge",
        "frequency_seconds": 60,
        "active_schedule": {"schedule_type": "market_hours"},
        "cooldown_seconds": 0,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(updates)
    return AlertRule.model_validate(values)


def observation(
    condition_state: ConditionState | str,
    seconds: int,
    *,
    value: str = "11",
    market_date=None,
) -> AlertEvaluation:
    at = NOW + timedelta(seconds=seconds)
    return AlertEvaluation(
        condition_state=condition_state,
        value=Decimal(value),
        evaluated_at=at,
        market_date=market_date or at.date(),
    )


def apply(machine, rule, state, condition_state, seconds, **kwargs):
    return machine.transition(
        rule,
        state,
        observation(condition_state, seconds, **kwargs),
    )


def test_edge_fires_on_false_to_true_only_and_recovers_on_false():
    rule = make_rule()
    machine = AlertStateMachine()
    state = initial_alert_state(rule, scope_key="CN:600000", symbol="600000", now=NOW)

    false_result = apply(machine, rule, state, "false", 0, value="9")
    assert false_result.events == ()
    first_true = apply(machine, rule, false_result.state, "true", 60)
    assert [event.kind for event in first_true.events] == [AlertEventKind.TRIGGERED]
    assert first_true.state.active_event_open is True

    persistent_true = apply(machine, rule, first_true.state, "true", 120, value="12")
    assert persistent_true.events == ()
    recovered = apply(machine, rule, persistent_true.state, "false", 180, value="8")
    assert [event.kind for event in recovered.events] == [AlertEventKind.RECOVERED]
    assert recovered.state.active_event_open is False


def test_unknown_is_not_false_and_health_warning_is_emitted_once():
    rule = make_rule()
    machine = AlertStateMachine()
    state = initial_alert_state(rule, scope_key="CN:600000", symbol="600000", now=NOW)
    triggered = apply(machine, rule, state, "true", 0)

    unknown_1 = apply(machine, rule, triggered.state, "unknown", 60)
    unknown_2 = apply(machine, rule, unknown_1.state, "unknown", 120)
    unknown_3 = apply(machine, rule, unknown_2.state, "unknown", 180)
    unknown_4 = apply(machine, rule, unknown_3.state, "unknown", 240)
    assert unknown_1.events == unknown_2.events == ()
    assert [event.kind for event in unknown_3.events] == [AlertEventKind.RULE_HEALTH]
    assert unknown_4.events == ()
    assert unknown_4.state.active_event_open is True

    true_again = apply(machine, rule, unknown_4.state, "true", 300)
    assert true_again.events == ()
    recovered = apply(machine, rule, true_again.state, "false", 360, value="9")
    assert [event.kind for event in recovered.events] == [AlertEventKind.RECOVERED]


def test_unknown_to_true_fires_when_no_prior_determined_true_state_exists():
    rule = make_rule()
    machine = AlertStateMachine()
    state = initial_alert_state(rule, scope_key="CN:600000", symbol="600000", now=NOW)
    unknown = apply(machine, rule, state, "unknown", 0)
    result = apply(machine, rule, unknown.state, "true", 60)
    assert [event.kind for event in result.events] == [AlertEventKind.TRIGGERED]


def test_unknown_health_retries_after_quota_resets_until_event_is_recorded():
    rule = make_rule(max_events_per_day=1)
    machine = AlertStateMachine()
    state = initial_alert_state(rule, scope_key="CN:600000", symbol="600000", now=NOW)
    state = state.model_copy(update={"events_today": 1, "market_date": NOW.date()})
    first = apply(machine, rule, state, "unknown", 0)
    second = apply(machine, rule, first.state, "unknown", 60)
    third = apply(machine, rule, second.state, "unknown", 120)
    assert third.events == ()
    assert third.suppression_reasons == ("DAILY_QUOTA_REACHED",)
    assert third.state.health_unknown_reported is False

    next_day = apply(
        machine,
        rule,
        third.state,
        "unknown",
        86_400,
        market_date=(NOW + timedelta(days=1)).date(),
    )
    assert [event.kind for event in next_day.events] == [AlertEventKind.RULE_HEALTH]
    assert next_day.state.health_unknown_reported is True


def test_level_mode_enforces_cooldown_daily_quota_and_market_date_reset():
    rule = make_rule(
        evaluation_mode="level",
        cooldown_seconds=60,
        max_events_per_day=2,
    )
    machine = AlertStateMachine()
    state = initial_alert_state(rule, scope_key="CN:600000", symbol="600000", now=NOW)

    first = apply(machine, rule, state, "true", 0)
    cooldown = apply(machine, rule, first.state, "true", 30)
    second = apply(machine, rule, cooldown.state, "true", 60)
    quota = apply(machine, rule, second.state, "true", 120)
    assert len(first.events) == len(second.events) == 1
    assert cooldown.events == ()
    assert "COOLDOWN_ACTIVE" in cooldown.suppression_reasons
    assert quota.events == () and quota.suppression_reasons == ("DAILY_QUOTA_REACHED",)

    next_day = apply(
        machine,
        rule,
        quota.state,
        "true",
        86_400,
        market_date=(NOW + timedelta(days=1)).date(),
    )
    assert len(next_day.events) == 1
    assert next_day.state.events_today == 1


def test_once_mode_requests_atomic_rule_disable_after_first_event():
    rule = make_rule(evaluation_mode="once")
    state = initial_alert_state(rule, scope_key="CN:600000", symbol="600000", now=NOW)
    result = apply(AlertStateMachine(), rule, state, "true", 0)
    assert len(result.events) == 1
    assert result.disable_rule is True


def test_duration_by_evaluation_count_requires_continuous_true_values():
    rule = make_rule(trigger={**make_rule().trigger.model_dump(), "for_evaluations": 3})
    machine = AlertStateMachine()
    state = initial_alert_state(rule, scope_key="CN:600000", symbol="600000", now=NOW)

    first = apply(machine, rule, state, "true", 0)
    interrupted = apply(machine, rule, first.state, "false", 60, value="9")
    one = apply(machine, rule, interrupted.state, "true", 120)
    two = apply(machine, rule, one.state, "true", 180)
    three = apply(machine, rule, two.state, "true", 240)
    assert first.events == interrupted.events == one.events == two.events == ()
    assert len(three.events) == 1
    assert three.state.consecutive_true == 3


def test_duration_by_seconds_uses_evaluation_timestamps():
    rule = make_rule(trigger={**make_rule().trigger.model_dump(), "for_seconds": 60})
    machine = AlertStateMachine()
    state = initial_alert_state(rule, scope_key="CN:600000", symbol="600000", now=NOW)
    first = apply(machine, rule, state, "true", 0)
    early = apply(machine, rule, first.state, "true", 59)
    qualified = apply(machine, rule, early.state, "true", 60)
    assert first.events == early.events == ()
    assert len(qualified.events) == 1


def test_duplicate_is_idempotent_and_out_of_order_evaluation_is_rejected():
    rule = make_rule()
    machine = AlertStateMachine()
    state = initial_alert_state(rule, scope_key="CN:600000", symbol="600000", now=NOW)
    result = apply(machine, rule, state, "false", 60, value="9")
    duplicate = apply(machine, rule, result.state, "false", 60, value="9")
    assert duplicate.duplicate_evaluation is True
    assert duplicate.state.state_revision == result.state.state_revision
    with pytest.raises(AlertStateTransitionError):
        apply(machine, rule, result.state, "false", 30, value="9")


def test_condition_version_resets_state_but_metadata_version_preserves_it():
    rule = make_rule()
    machine = AlertStateMachine()
    state = initial_alert_state(rule, scope_key="CN:600000", symbol="600000", now=NOW)
    active = apply(machine, rule, state, "true", 0).state

    renamed = rule.model_copy(update={"name": "新名称", "version": 2})
    metadata = apply(machine, renamed, active, "true", 60)
    assert metadata.state.rule_version == 2
    assert metadata.state.condition_version == 1
    assert metadata.state.last_triggered_at == NOW
    assert metadata.events == ()

    changed = renamed.model_copy(update={"version": 3, "condition_version": 2})
    reset = apply(machine, changed, metadata.state, "true", 120)
    assert reset.state.condition_version == 2
    assert reset.state.state_revision > metadata.state.state_revision
    assert reset.state.last_triggered_at == NOW + timedelta(seconds=120)
    assert len(reset.events) == 1


def test_fingerprint_covers_symbol_direction_condition_version_and_time_bucket():
    rule = make_rule()
    state = initial_alert_state(rule, scope_key="CN:600000", symbol="600000", now=NOW)
    first = build_event_fingerprint(rule, state, direction="triggered", evaluated_at=NOW)
    same_bucket = build_event_fingerprint(
        rule, state, direction="triggered", evaluated_at=NOW + timedelta(seconds=59)
    )
    next_bucket = build_event_fingerprint(
        rule, state, direction="triggered", evaluated_at=NOW + timedelta(seconds=60)
    )
    recovered = build_event_fingerprint(rule, state, direction="recovered", evaluated_at=NOW)
    other_symbol = state.model_copy(update={"symbol": "600001"})
    other = build_event_fingerprint(rule, other_symbol, direction="triggered", evaluated_at=NOW)
    new_condition = rule.model_copy(update={"version": 2, "condition_version": 2})
    versioned = build_event_fingerprint(
        new_condition, state, direction="triggered", evaluated_at=NOW
    )
    assert first == same_bucket
    assert len({first, next_bucket, recovered, other, versioned}) == 5
