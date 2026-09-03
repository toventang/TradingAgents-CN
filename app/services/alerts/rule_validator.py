"""Static validation and version semantics for the closed alert-rule DSL."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from app.models.alert import (
    SYSTEM_USER_ID,
    AlertAction,
    AlertCondition,
    AlertEvaluationMode,
    AlertMarket,
    AlertRule,
    AlertRuleOrigin,
    AlertRuleStateSummary,
    AlertScopeType,
    AlertType,
    AllAlertCondition,
    AnyAlertCondition,
    ChangeRateOperand,
    CompareAlertCondition,
    CrossAlertCondition,
    NotAlertCondition,
    StrategyUniverseScope,
    SymbolScope,
    WatchlistScope,
    utc_now,
)
from app.models.symbol import infer_cn_exchange


SYSTEM_ALERT_TYPES = {
    AlertType.DATASOURCE_DOWN,
    AlertType.DATASOURCE_LATENCY,
    AlertType.FACTOR_JOB_FAILED,
    AlertType.SCHEDULER_JOB_FAILED,
    AlertType.WORKER_HEARTBEAT_LOST,
    AlertType.NOTIFICATION_DELIVERY_FAILED,
}
ACCOUNT_ALERT_TYPES = {
    AlertType.STOP_LOSS_NEAR,
    AlertType.STOP_LOSS_TRIGGERED,
    AlertType.TAKE_PROFIT_NEAR,
    AlertType.TAKE_PROFIT_TRIGGERED,
    AlertType.TRAILING_STOP_TRIGGERED,
    AlertType.POSITION_DRAWDOWN,
    AlertType.ACCOUNT_DRAWDOWN,
    AlertType.POSITION_WEIGHT_EXCEEDED,
    AlertType.INDUSTRY_WEIGHT_EXCEEDED,
    AlertType.CASH_BELOW,
}
POSITION_ALERT_TYPES = {
    AlertType.STOP_LOSS_NEAR,
    AlertType.STOP_LOSS_TRIGGERED,
    AlertType.TAKE_PROFIT_NEAR,
    AlertType.TAKE_PROFIT_TRIGGERED,
    AlertType.TRAILING_STOP_TRIGGERED,
    AlertType.POSITION_DRAWDOWN,
    AlertType.POSITION_WEIGHT_EXCEEDED,
}
NEW_HIGH_LOW_TYPES = {AlertType.NEW_HIGH, AlertType.NEW_LOW}


@dataclass(frozen=True)
class AlertValidationIssue:
    code: str
    message: str
    path: str | None = None


@dataclass(frozen=True)
class AlertValidationReport:
    rule: AlertRule | None
    errors: tuple[AlertValidationIssue, ...]
    warnings: tuple[AlertValidationIssue, ...] = ()

    @property
    def valid(self) -> bool:
        return self.rule is not None and not self.errors


class AlertRuleValidationError(ValueError):
    def __init__(self, report: AlertValidationReport):
        self.report = report
        super().__init__(
            "; ".join(issue.message for issue in report.errors)
            or "alert rule validation failed"
        )


class AlertRuleValidator:
    def __init__(self, *, max_depth: int = 10, max_nodes: int = 200):
        if max_depth < 1 or max_nodes < 1:
            raise ValueError("condition-tree limits must be positive")
        self.max_depth = max_depth
        self.max_nodes = max_nodes

    def validate(self, value: AlertRule | dict[str, Any]) -> AlertValidationReport:
        try:
            # ``model_copy(update=...)`` deliberately skips Pydantic validation.
            # Re-parse model instances as well so nested updates cannot smuggle raw
            # dictionaries or otherwise bypass the closed alert-rule schema.
            payload = (
                {field: getattr(value, field) for field in AlertRule.model_fields}
                if isinstance(value, AlertRule)
                else value
            )
            rule = AlertRule.model_validate(payload)
        except ValidationError as exc:
            errors = tuple(
                AlertValidationIssue(
                    code="ALERT_SCHEMA_INVALID",
                    message=str(item["msg"]),
                    path=".".join(str(part) for part in item["loc"]) or None,
                )
                for item in exc.errors(include_url=False)
            )
            return AlertValidationReport(rule=None, errors=errors)

        errors: list[AlertValidationIssue] = []
        warnings: list[AlertValidationIssue] = []
        self._validate_scope(rule, errors)
        self._validate_action(rule, errors)
        self._validate_alert_type(rule, errors)
        self._validate_condition_tree(rule.trigger.condition, errors)
        if (
            rule.evaluation_mode == AlertEvaluationMode.ONCE
            and rule.recovery_enabled
        ):
            warnings.append(
                self._issue(
                    "ONCE_RECOVERY_UNREACHABLE",
                    "once rules are disabled after their first trigger, so recovery is not evaluated",
                    "recovery_enabled",
                )
            )
        return AlertValidationReport(
            rule=rule,
            errors=tuple(errors),
            warnings=tuple(warnings),
        )

    def validate_or_raise(self, value: AlertRule | dict[str, Any]) -> AlertRule:
        report = self.validate(value)
        if not report.valid:
            raise AlertRuleValidationError(report)
        assert report.rule is not None
        return report.rule

    def prepare_update(
        self,
        current: AlertRule,
        proposed: AlertRule | dict[str, Any],
        *,
        updated_at: datetime | None = None,
    ) -> tuple[AlertRule, bool]:
        parsed = self.validate_or_raise(proposed)
        if parsed.rule_id != current.rule_id or parsed.user_id != current.user_id:
            raise ValueError("rule_id and user_id are immutable")
        resets_state = state_reset_required(current, parsed)
        candidate = parsed.model_copy(
            update={
                "version": current.version + 1,
                "condition_version": current.condition_version
                + (1 if resets_state else 0),
                "created_at": current.created_at,
                "updated_at": updated_at or utc_now(),
                "state": (
                    AlertRuleStateSummary()
                    if resets_state
                    else current.state.model_copy(deep=True)
                ),
            }
        )
        return self.validate_or_raise(candidate), resets_state

    def _validate_scope(
        self, rule: AlertRule, errors: list[AlertValidationIssue]
    ) -> None:
        scope_type = rule.scope.scope_type
        if rule.market == AlertMarket.SYSTEM:
            if scope_type != AlertScopeType.SYSTEM:
                errors.append(
                    self._issue(
                        "SYSTEM_MARKET_SCOPE_INVALID",
                        "system market requires system scope",
                        "scope",
                    )
                )
            if rule.user_id != SYSTEM_USER_ID or rule.origin != AlertRuleOrigin.SYSTEM:
                errors.append(
                    self._issue(
                        "SYSTEM_RULE_OWNER_INVALID",
                        "system rules must be owned by system and have system origin",
                        "user_id",
                    )
                )
        elif scope_type == AlertScopeType.SYSTEM:
            errors.append(
                self._issue(
                    "SYSTEM_SCOPE_MARKET_INVALID",
                    "system scope requires system market",
                    "market",
                )
            )

        if rule.origin == AlertRuleOrigin.SYSTEM and (
            rule.market != AlertMarket.SYSTEM or rule.user_id != SYSTEM_USER_ID
        ):
            errors.append(
                self._issue(
                    "SYSTEM_ORIGIN_INVALID",
                    "system-origin rules require system market and system ownership",
                    "origin",
                )
            )
        if rule.user_id == SYSTEM_USER_ID and rule.origin != AlertRuleOrigin.SYSTEM:
            errors.append(
                self._issue(
                    "SYSTEM_OWNER_ORIGIN_INVALID",
                    "system-owned rules require system origin",
                    "origin",
                )
            )

        symbols: tuple[str, ...] = ()
        if isinstance(rule.scope, SymbolScope):
            symbols = (rule.scope.symbol,)
        elif isinstance(rule.scope, WatchlistScope):
            symbols = rule.scope.symbols
        for index, symbol in enumerate(symbols):
            if not _valid_symbol(rule.market, symbol):
                errors.append(
                    self._issue(
                        "SCOPE_SYMBOL_INVALID",
                        f"symbol {symbol!r} is not canonical for {rule.market.value}",
                        f"scope.symbols.{index}",
                    )
                )

        if isinstance(rule.scope, StrategyUniverseScope):
            if not rule.scope.strategy_version_id:
                errors.append(
                    self._issue(
                        "STRATEGY_SCOPE_VERSION_REQUIRED",
                        "strategy universe must reference an immutable version",
                        "scope.strategy_version_id",
                    )
                )

    def _validate_action(
        self, rule: AlertRule, errors: list[AlertValidationIssue]
    ) -> None:
        if rule.origin == AlertRuleOrigin.AUTOMATION and rule.automation_id is None:
            errors.append(
                self._issue(
                    "AUTOMATION_ID_REQUIRED",
                    "automation-origin rule requires automation_id",
                    "automation_id",
                )
            )
        if rule.origin != AlertRuleOrigin.AUTOMATION and rule.automation_id is not None:
            errors.append(
                self._issue(
                    "AUTOMATION_ID_FORBIDDEN",
                    "automation_id is only allowed for automation-origin rules",
                    "automation_id",
                )
            )
        if rule.action == AlertAction.PAPER_TRADE:
            if rule.origin != AlertRuleOrigin.AUTOMATION or rule.automation_id is None:
                errors.append(
                    self._issue(
                        "PAPER_TRADE_ACTION_FORBIDDEN",
                        "paper_trade is restricted to internal automation rules",
                        "action",
                    )
                )
            if rule.paper_account_id is None:
                errors.append(
                    self._issue(
                        "PAPER_ACCOUNT_REQUIRED",
                        "paper_trade action requires paper_account_id",
                        "paper_account_id",
                    )
                )
            if rule.market == AlertMarket.SYSTEM:
                errors.append(
                    self._issue(
                        "SYSTEM_PAPER_TRADE_FORBIDDEN",
                        "system health rules cannot request paper trades",
                        "action",
                    )
                )
        elif rule.paper_account_id is not None:
            errors.append(
                self._issue(
                    "PAPER_ACCOUNT_FORBIDDEN",
                    "paper_account_id is only allowed for paper_trade actions",
                    "paper_account_id",
                )
            )

    def _validate_alert_type(
        self, rule: AlertRule, errors: list[AlertValidationIssue]
    ) -> None:
        scope_type = rule.scope.scope_type
        if (rule.alert_type in SYSTEM_ALERT_TYPES) != (
            scope_type == AlertScopeType.SYSTEM
        ):
            errors.append(
                self._issue(
                    "ALERT_TYPE_SCOPE_MISMATCH",
                    "system alert types and system scope must be used together",
                    "alert_type",
                )
            )
        if rule.alert_type in ACCOUNT_ALERT_TYPES:
            allowed = (
                {AlertScopeType.PAPER_POSITION}
                if rule.alert_type in POSITION_ALERT_TYPES
                else {AlertScopeType.PAPER_ACCOUNT}
            )
            if scope_type not in allowed:
                errors.append(
                    self._issue(
                        "ACCOUNT_ALERT_SCOPE_MISMATCH",
                        "account or position alert uses an incompatible scope",
                        "scope",
                    )
                )
        elif scope_type in {
            AlertScopeType.PAPER_POSITION,
            AlertScopeType.PAPER_ACCOUNT,
        }:
            errors.append(
                self._issue(
                    "NON_ACCOUNT_ALERT_SCOPE_MISMATCH",
                    "non-account alert cannot use a paper account scope",
                    "scope",
                )
            )
        if rule.alert_type in NEW_HIGH_LOW_TYPES and rule.lookback_window is None:
            errors.append(
                self._issue(
                    "LOOKBACK_WINDOW_REQUIRED",
                    "new_high and new_low require a 5 to 250 session lookback",
                    "lookback_window",
                )
            )
        if rule.alert_type not in NEW_HIGH_LOW_TYPES and rule.lookback_window is not None:
            errors.append(
                self._issue(
                    "LOOKBACK_WINDOW_FORBIDDEN",
                    "lookback_window is only valid for new_high and new_low",
                    "lookback_window",
                )
            )
        if rule.alert_type == AlertType.HIGH_SEVERITY_EVENT:
            if not rule.event_categories:
                errors.append(
                    self._issue(
                        "EVENT_CATEGORY_REQUIRED",
                        "high_severity_event requires at least one event category",
                        "event_categories",
                    )
                )
        elif rule.event_categories:
            errors.append(
                self._issue(
                    "EVENT_CATEGORY_FORBIDDEN",
                    "event_categories are only valid for high_severity_event",
                    "event_categories",
                )
            )

    def _validate_condition_tree(
        self,
        condition: AlertCondition,
        errors: list[AlertValidationIssue],
    ) -> None:
        depth, nodes = _condition_stats(condition)
        if depth > self.max_depth:
            errors.append(
                self._issue(
                    "ALERT_CONDITION_TOO_DEEP",
                    f"condition tree depth {depth} exceeds {self.max_depth}",
                    "trigger.condition",
                )
            )
        if nodes > self.max_nodes:
            errors.append(
                self._issue(
                    "ALERT_CONDITION_TOO_LARGE",
                    f"condition tree has {nodes} nodes, above {self.max_nodes}",
                    "trigger.condition",
                )
            )
        for node in _walk_conditions(condition):
            operands = []
            if isinstance(node, (CompareAlertCondition, CrossAlertCondition)):
                operands.extend((node.left, node.right))
                if isinstance(node, CompareAlertCondition) and node.upper is not None:
                    operands.append(node.upper)
            for operand in operands:
                if isinstance(operand, ChangeRateOperand):
                    if operand.window_seconds < 30:
                        errors.append(
                            self._issue(
                                "CHANGE_RATE_WINDOW_INVALID",
                                "change-rate window must be at least 30 seconds",
                                "trigger.condition",
                            )
                        )

    @staticmethod
    def _issue(code: str, message: str, path: str | None) -> AlertValidationIssue:
        return AlertValidationIssue(code=code, message=message, path=path)


def state_reset_required(current: AlertRule, proposed: AlertRule) -> bool:
    """Return whether an update changes the condition evaluation identity."""

    fields = (
        "alert_type",
        "scope",
        "market",
        "trigger",
        "frequency_seconds",
        "active_schedule",
        "evaluation_mode",
        "lookback_window",
        "event_categories",
    )
    return any(getattr(current, field) != getattr(proposed, field) for field in fields)


def _condition_stats(condition: AlertCondition) -> tuple[int, int]:
    if isinstance(condition, (AllAlertCondition, AnyAlertCondition)):
        children = [_condition_stats(child) for child in condition.children]
        return 1 + max(depth for depth, _ in children), 1 + sum(
            nodes for _, nodes in children
        )
    if isinstance(condition, NotAlertCondition):
        depth, nodes = _condition_stats(condition.child)
        return depth + 1, nodes + 1
    return 1, 1


def _walk_conditions(condition: AlertCondition):
    yield condition
    if isinstance(condition, (AllAlertCondition, AnyAlertCondition)):
        for child in condition.children:
            yield from _walk_conditions(child)
    elif isinstance(condition, NotAlertCondition):
        yield from _walk_conditions(condition.child)


def _valid_symbol(market: AlertMarket, symbol: str) -> bool:
    if market == AlertMarket.CN:
        return infer_cn_exchange(symbol) is not None
    if market == AlertMarket.HK:
        return bool(re.fullmatch(r"\d{4,5}", symbol)) and int(symbol) != 0
    if market == AlertMarket.US:
        return bool(re.fullmatch(r"[A-Z]{1,5}(?:\.[A-Z])?", symbol))
    return False
