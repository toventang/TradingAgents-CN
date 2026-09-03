from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.models.alert import (
    AlertAction,
    AlertEvent,
    AlertEventKind,
    AlertMarket,
    AlertQualityStatus,
    AlertRule,
    AlertRuleOrigin,
    AlertRuleStateSummary,
    AlertSeverity,
    AlertType,
    ConditionState,
    NewsEventCategory,
    stable_checksum,
)
from app.repositories.alert_repository import (
    AlertRepository,
    AlertRepositoryConflict,
)
from app.services.alerts.rule_validator import AlertRuleValidator
from app.services.alerts.state_machine import (
    AlertEvaluation,
    AlertStateMachine,
    initial_alert_state,
)
from tests.unit.domain_tasks.fakes import FakeCollection, _apply_update, _matches


NOW = datetime(2024, 1, 2, 9, 30, tzinfo=timezone.utc)
RULE_ID = str(UUID("00000000-0000-0000-0000-000000000040"))


def trigger(threshold: str = "10") -> dict:
    return {
        "condition": {
            "type": "compare",
            "left": {"kind": "current_value"},
            "operator": "gt",
            "right": {"kind": "constant", "value": threshold},
        }
    }


def make_rule(**updates) -> AlertRule:
    values = {
        "rule_id": RULE_ID,
        "user_id": "owner",
        "name": "价格突破",
        "description": "收盘价超过阈值",
        "alert_type": AlertType.PRICE_ABOVE,
        "scope": {"scope_type": "symbol", "symbol": "600000"},
        "market": AlertMarket.CN,
        "trigger": trigger(),
        "evaluation_mode": "edge",
        "frequency_seconds": 60,
        "active_schedule": {"schedule_type": "market_hours"},
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(updates)
    return AlertRule.model_validate(values)


def make_event(rule: AlertRule, **updates) -> AlertEvent:
    values = {
        "rule_id": rule.rule_id,
        "rule_version": rule.version,
        "condition_version": rule.condition_version,
        "user_id": rule.user_id,
        "scope_key": f"{rule.market.value}:600000",
        "symbol": "600000",
        "kind": AlertEventKind.TRIGGERED,
        "severity": AlertSeverity.WARNING,
        "direction": "triggered",
        "condition_state": ConditionState.TRUE,
        "current_value": Decimal("13"),
        "previous_value": Decimal("9"),
        "quote_time": NOW,
        "ingested_at": NOW + timedelta(seconds=1),
        "evaluated_at": NOW + timedelta(seconds=2),
        "source": "fixture",
        "latency_seconds": Decimal("2"),
        "quality_status": AlertQualityStatus.VALID,
        "actual_symbol_count": 1,
        "actual_symbols_checksum": stable_checksum(["600000"]),
        "fingerprint": stable_checksum({"event": rule.rule_id}),
        "created_at": NOW + timedelta(seconds=2),
    }
    values.update(updates)
    return AlertEvent.model_validate(values)


def issue_codes(report) -> set[str]:
    return {item.code for item in report.errors}


def test_closed_rule_schema_rejects_code_unknown_channels_and_ambiguous_scope():
    validator = AlertRuleValidator()
    payload = make_rule().model_dump(mode="json")
    payload["trigger"]["expression"] = "__import__('os').system('x')"
    report = validator.validate(payload)
    assert report.valid is False
    assert "ALERT_SCHEMA_INVALID" in issue_codes(report)

    payload = make_rule().model_dump(mode="json")
    payload["channels"] = ["email"]
    assert validator.validate(payload).valid is False

    payload = make_rule().model_dump(mode="json")
    payload["scope"] = {
        "scope_type": "watchlist",
        "watchlist_id": "watchlist-1",
        "symbols": ["600000"],
    }
    assert validator.validate(payload).valid is False


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("frequency_seconds", 29),
        ("frequency_seconds", 86_401),
        ("cooldown_seconds", -1),
        ("cooldown_seconds", 604_801),
        ("max_events_per_day", 0),
        ("max_events_per_day", 1_001),
    ),
)
def test_rule_frequency_cooldown_and_quota_bounds_are_closed(field, value):
    payload = make_rule().model_dump(mode="json")
    payload[field] = value
    assert AlertRuleValidator().validate(payload).valid is False


def test_event_evidence_timestamps_latency_quality_and_summary_are_consistent():
    event = make_event(make_rule())
    payload = event.model_dump(mode="python")

    invalid_latency = {**payload, "latency_seconds": Decimal("1")}
    with pytest.raises(ValueError, match="latency_seconds"):
        AlertEvent.model_validate(invalid_latency)

    invalid_stale = {**payload, "stale": True}
    with pytest.raises(ValueError, match="stale flag"):
        AlertEvent.model_validate(invalid_stale)

    missing_summary = {
        **payload,
        "actual_symbol_count": 1,
        "actual_symbols_checksum": None,
    }
    with pytest.raises(ValueError, match="symbol evidence"):
        AlertEvent.model_validate(missing_summary)

def test_scope_market_alert_type_and_specialized_fields_are_exact():
    validator = AlertRuleValidator()
    invalid_symbol = make_rule(
        scope={"scope_type": "symbol", "symbol": "AAPL"}
    )
    assert "SCOPE_SYMBOL_INVALID" in issue_codes(validator.validate(invalid_symbol))

    account_mismatch = make_rule(
        alert_type=AlertType.ACCOUNT_DRAWDOWN,
        scope={"scope_type": "symbol", "symbol": "600000"},
    )
    assert "ACCOUNT_ALERT_SCOPE_MISMATCH" in issue_codes(
        validator.validate(account_mismatch)
    )

    new_high = make_rule(alert_type=AlertType.NEW_HIGH)
    assert "LOOKBACK_WINDOW_REQUIRED" in issue_codes(validator.validate(new_high))
    assert validator.validate(
        make_rule(alert_type=AlertType.NEW_HIGH, lookback_window=20)
    ).valid

    news = make_rule(
        alert_type=AlertType.HIGH_SEVERITY_EVENT,
        event_categories=(NewsEventCategory.REGULATORY,),
    )
    assert validator.validate(news).valid


def test_system_and_paper_trade_permissions_cannot_be_escalated_by_user_rules():
    validator = AlertRuleValidator()
    user_trade = make_rule(
        action=AlertAction.PAPER_TRADE,
        paper_account_id="paper-1",
    )
    assert "PAPER_TRADE_ACTION_FORBIDDEN" in issue_codes(
        validator.validate(user_trade)
    )

    automation_trade = make_rule(
        action=AlertAction.PAPER_TRADE,
        origin=AlertRuleOrigin.AUTOMATION,
        automation_id="campaign-1",
        paper_account_id="paper-1",
    )
    assert validator.validate(automation_trade).valid

    invalid_system = make_rule(
        alert_type=AlertType.DATASOURCE_DOWN,
        market=AlertMarket.SYSTEM,
        scope={"scope_type": "system", "component": "market-data"},
    )
    assert "SYSTEM_RULE_OWNER_INVALID" in issue_codes(
        validator.validate(invalid_system)
    )

    system = make_rule(
        user_id="system",
        alert_type=AlertType.DATASOURCE_DOWN,
        market=AlertMarket.SYSTEM,
        scope={"scope_type": "system", "component": "market-data"},
        origin=AlertRuleOrigin.SYSTEM,
    )
    assert validator.validate(system).valid

    disguised_system = make_rule(origin=AlertRuleOrigin.SYSTEM)
    assert "SYSTEM_ORIGIN_INVALID" in issue_codes(
        validator.validate(disguised_system)
    )


def test_metadata_update_increments_rule_version_without_resetting_condition_state():
    validator = AlertRuleValidator()
    current = make_rule(
        state=AlertRuleStateSummary(
            evaluated_scope_count=3,
            triggered_scope_count=1,
            last_evaluated_at=NOW,
        )
    )
    updated, resets = validator.prepare_update(
        current,
        current.model_copy(update={"name": "新的显示名称"}),
        updated_at=NOW + timedelta(minutes=1),
    )

    assert resets is False
    assert updated.version == 2
    assert updated.condition_version == 1
    assert updated.state == current.state

    changed, resets = validator.prepare_update(
        updated,
        updated.model_copy(update={"trigger": trigger("11")}),
        updated_at=NOW + timedelta(minutes=2),
    )
    assert resets is True
    assert changed.version == 3
    assert changed.condition_version == 2
    assert changed.state == AlertRuleStateSummary()


class AlertFakeCollection(FakeCollection):
    async def update_one(self, query, update, upsert=False):
        async with self.lock:
            for document in self.documents:
                if _matches(document, query):
                    _apply_update(document, update)
                    return SimpleNamespace(upserted_id=None, matched_count=1)
            if not upsert:
                return SimpleNamespace(upserted_id=None, matched_count=0)
            document = deepcopy(query)
            document.update(deepcopy(update.get("$setOnInsert", {})))
            _apply_update(document, update)
            self.documents.append(document)
            return SimpleNamespace(
                upserted_id=f"{self.name}-{len(self.documents)}",
                matched_count=0,
            )

    async def update_many(self, query, update):
        count = 0
        async with self.lock:
            for document in self.documents:
                if _matches(document, query):
                    _apply_update(document, update)
                    count += 1
        return SimpleNamespace(modified_count=count)


class AlertFakeDatabase:
    def __init__(self):
        self.collections = {}

    def __getitem__(self, name):
        return self.collections.setdefault(name, AlertFakeCollection(name))


@pytest.mark.asyncio
async def test_repository_versions_rules_resets_states_and_deduplicates_events():
    database = AlertFakeDatabase()
    repository = AlertRepository(database)
    rule = await repository.create_rule(make_rule())
    state = initial_alert_state(rule, scope_key="CN:600000", symbol="600000")
    state = AlertStateMachine().transition(
        rule,
        state,
        AlertEvaluation(
            condition_state=ConditionState.FALSE,
            value=Decimal("9"),
            evaluated_at=NOW + timedelta(seconds=1),
            market_date=NOW.date(),
        ),
    ).state
    await repository.create_state(state)

    metadata, reset = await repository.update_rule(
        rule.model_copy(update={"description": "仅修改说明"}),
        user_id="owner",
        expected_version=1,
        updated_at=NOW + timedelta(minutes=1),
    )
    assert reset is False and metadata.version == 2
    preserved = await repository.get_state(
        rule.rule_id, user_id="owner", scope_key="CN:600000"
    )
    assert preserved is not None
    assert preserved.last_condition_state == ConditionState.FALSE
    assert preserved.rule_version == 2

    changed, reset = await repository.update_rule(
        metadata.model_copy(update={"trigger": trigger("12")}),
        user_id="owner",
        expected_version=2,
        updated_at=NOW + timedelta(minutes=2),
    )
    assert reset is True and changed.condition_version == 2
    reset_state = await repository.get_state(
        rule.rule_id, user_id="owner", scope_key="CN:600000"
    )
    assert reset_state is not None
    assert reset_state.last_evaluated_at is None
    assert reset_state.last_determined_state is None
    assert reset_state.condition_version == 2
    assert await repository.get_rule(rule.rule_id, user_id="other") is None
    assert (
        await repository.get_state(
            rule.rule_id, user_id="other", scope_key="CN:600000"
        )
        is None
    )

    stale_state_write = reset_state.model_copy(
        update={
            "state_revision": reset_state.state_revision + 1,
            "rule_version": reset_state.rule_version - 1,
        }
    )
    with pytest.raises(AlertRepositoryConflict, match="state version"):
        await repository.replace_state(
            stale_state_write,
            expected_revision=reset_state.state_revision,
        )

    fingerprint = stable_checksum({"event": 1})
    event = make_event(changed, fingerprint=fingerprint)
    _, created = await repository.append_event(event)
    duplicate_attempt = event.model_copy(
        update={
            "event_id": str(UUID("00000000-0000-0000-0000-000000000041")),
            "created_at": event.created_at + timedelta(seconds=1),
        }
    )
    duplicate, created_again = await repository.append_event(duplicate_attempt)
    assert created is True and created_again is False
    assert duplicate.event_id == event.event_id
    assert len(database[repository.RULE_VERSIONS_COLLECTION].documents) == 3
    assert len(database[repository.EVENTS_COLLECTION].documents) == 1

    with pytest.raises(AlertRepositoryConflict):
        await repository.update_rule(
            changed,
            user_id="owner",
            expected_version=2,
        )

    with pytest.raises(AlertRepositoryConflict):
        await repository.append_event(
            duplicate_attempt.model_copy(update={"current_value": Decimal("14")})
        )


@pytest.mark.asyncio
async def test_repository_requires_dynamic_scope_evidence_and_blocks_stale_actions():
    dynamic_db = AlertFakeDatabase()
    dynamic_repository = AlertRepository(dynamic_db)
    dynamic_rule = await dynamic_repository.create_rule(
        make_rule(
            rule_id=str(UUID("00000000-0000-0000-0000-000000000042")),
            scope={
                "scope_type": "strategy_universe",
                "strategy_version_id": "strategy-v1",
            },
        )
    )
    without_snapshot = make_event(
        dynamic_rule,
        actual_symbol_count=0,
        actual_symbols_checksum=None,
    )
    with pytest.raises(AlertRepositoryConflict, match="dynamic-scope"):
        await dynamic_repository.append_event(without_snapshot)
    evidenced = without_snapshot.model_copy(
        update={
            "actual_symbols_checksum": stable_checksum([]),
            "universe_snapshot_id": "universe-2024-01-02",
        }
    )
    _, created = await dynamic_repository.append_event(evidenced)
    assert created is True

    automation_db = AlertFakeDatabase()
    automation_repository = AlertRepository(automation_db)
    automation_rule = await automation_repository.create_rule(
        make_rule(
            rule_id=str(UUID("00000000-0000-0000-0000-000000000043")),
            action=AlertAction.PAPER_TRADE,
            origin=AlertRuleOrigin.AUTOMATION,
            automation_id="campaign-1",
            paper_account_id="paper-1",
        )
    )
    stale_event = make_event(
        automation_rule,
        quality_status=AlertQualityStatus.STALE,
        stale=True,
    )
    with pytest.raises(AlertRepositoryConflict, match="stale data"):
        await automation_repository.append_event(stale_event)
