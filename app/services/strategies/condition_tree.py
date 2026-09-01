"""Deterministic evaluation helpers for the closed strategy condition tree."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from app.models.strategy import (
    AllCondition,
    AnyCondition,
    ChangedCondition,
    CompareCondition,
    ConstantOperand,
    CrossCondition,
    FactorOperand,
    NotCondition,
    RankCondition,
    StrategyCompareOperator,
    StrategyCondition,
    StrategyOperand,
)


FactorSeries = Mapping[str, Sequence[float | None]]
FactorHistory = Mapping[str, FactorSeries]


@dataclass(frozen=True)
class ConditionTreeStats:
    depth: int
    nodes: int


@dataclass(frozen=True)
class ConditionEvaluation:
    passed: bool
    contributions: Mapping[str, float] = field(default_factory=dict)
    missing_factors: tuple[str, ...] = ()


@dataclass(frozen=True)
class ConditionContext:
    symbol: str
    history_by_symbol: FactorHistory

    def operand_value(
        self, operand: StrategyOperand, *, additional_lag: int = 0
    ) -> tuple[float | None, str | None]:
        if isinstance(operand, ConstantOperand):
            return operand.value, None
        factor_series = self.history_by_symbol.get(self.symbol, {}).get(operand.factor_id)
        offset = operand.lag + additional_lag
        if factor_series is None or len(factor_series) <= offset:
            return None, operand.factor_id
        value = factor_series[-1 - offset]
        if value is None or not math.isfinite(float(value)):
            return None, operand.factor_id
        return float(value), operand.factor_id


def condition_tree_stats(condition: StrategyCondition) -> ConditionTreeStats:
    if isinstance(condition, (AllCondition, AnyCondition)):
        children = [condition_tree_stats(child) for child in condition.children]
        return ConditionTreeStats(
            depth=1 + max(item.depth for item in children),
            nodes=1 + sum(item.nodes for item in children),
        )
    if isinstance(condition, NotCondition):
        child = condition_tree_stats(condition.child)
        return ConditionTreeStats(depth=1 + child.depth, nodes=1 + child.nodes)
    return ConditionTreeStats(depth=1, nodes=1)


def collect_condition_factors(
    condition: StrategyCondition,
) -> tuple[FactorOperand, ...]:
    result: list[FactorOperand] = []

    def add_operand(operand: StrategyOperand | None) -> None:
        if isinstance(operand, FactorOperand):
            result.append(operand)

    def visit(node: StrategyCondition) -> None:
        if isinstance(node, (AllCondition, AnyCondition)):
            for child in node.children:
                visit(child)
        elif isinstance(node, NotCondition):
            visit(node.child)
        elif isinstance(node, CompareCondition):
            add_operand(node.left)
            add_operand(node.right)
            add_operand(node.upper)
        elif isinstance(node, CrossCondition):
            add_operand(node.left)
            add_operand(node.right)
        elif isinstance(node, (RankCondition, ChangedCondition)):
            add_operand(node.factor)

    visit(condition)
    unique = {
        (item.factor_id, item.version, item.lag): item
        for item in result
    }
    return tuple(unique[key] for key in sorted(unique))


def evaluate_condition(
    condition: StrategyCondition, context: ConditionContext
) -> ConditionEvaluation:
    if isinstance(condition, AllCondition):
        children = [evaluate_condition(child, context) for child in condition.children]
        return _merge_evaluations(all(item.passed for item in children), children)
    if isinstance(condition, AnyCondition):
        children = [evaluate_condition(child, context) for child in condition.children]
        successful = [
            item for item in children if item.passed and not item.missing_factors
        ]
        if successful:
            return _merge_evaluations(True, successful)
        return _merge_evaluations(False, children)
    if isinstance(condition, NotCondition):
        child = evaluate_condition(condition.child, context)
        return ConditionEvaluation(
            passed=not child.passed,
            contributions=child.contributions,
            missing_factors=child.missing_factors,
        )
    if isinstance(condition, CompareCondition):
        return _evaluate_compare(condition, context)
    if isinstance(condition, CrossCondition):
        return _evaluate_cross(condition, context)
    if isinstance(condition, RankCondition):
        return _evaluate_rank(condition, context)
    if isinstance(condition, ChangedCondition):
        return _evaluate_changed(condition, context)
    raise TypeError(f"unsupported condition node: {type(condition).__name__}")


def impossible_all_constraints(condition: StrategyCondition) -> tuple[str, ...]:
    """Return factor IDs whose conjunction has contradictory numeric bounds."""

    flat: list[CompareCondition] = []

    def visit(node: StrategyCondition) -> None:
        if isinstance(node, AllCondition):
            for child in node.children:
                visit(child)
        elif isinstance(node, CompareCondition):
            flat.append(node)

    visit(condition)
    constraints: dict[str, _NumericConstraint] = {}
    for item in flat:
        normalized = _factor_constant_comparison(item)
        if normalized is None:
            continue
        factor_id, operator, lower, upper = normalized
        state = constraints.setdefault(factor_id, _NumericConstraint())
        state.apply(operator, lower, upper)
    return tuple(sorted(key for key, value in constraints.items() if value.impossible))


def _evaluate_compare(
    condition: CompareCondition, context: ConditionContext
) -> ConditionEvaluation:
    left, left_factor = context.operand_value(condition.left)
    right, right_factor = context.operand_value(condition.right)
    upper, upper_factor = (
        context.operand_value(condition.upper)
        if condition.upper is not None
        else (None, None)
    )
    missing = tuple(
        sorted(
            {
                factor_id
                for value, factor_id in (
                    (left, left_factor),
                    (right, right_factor),
                    (upper, upper_factor),
                )
                if factor_id is not None and value is None
            }
        )
    )
    contributions = _contributions(
        (left, left_factor), (right, right_factor), (upper, upper_factor)
    )
    if left is None or right is None:
        return ConditionEvaluation(False, contributions, missing)
    if condition.operator == StrategyCompareOperator.BETWEEN:
        passed = upper is not None and right <= left <= upper
    else:
        passed = _compare(left, condition.operator.value, right)
    return ConditionEvaluation(passed, contributions, missing)


def _evaluate_cross(
    condition: CrossCondition, context: ConditionContext
) -> ConditionEvaluation:
    current_left, left_factor = context.operand_value(condition.left)
    current_right, right_factor = context.operand_value(condition.right)
    prior_left, prior_left_factor = context.operand_value(
        condition.left, additional_lag=condition.periods
    )
    prior_right, prior_right_factor = context.operand_value(
        condition.right, additional_lag=condition.periods
    )
    pairs = (
        (current_left, left_factor),
        (current_right, right_factor),
        (prior_left, prior_left_factor),
        (prior_right, prior_right_factor),
    )
    missing = tuple(
        sorted({factor_id for value, factor_id in pairs if factor_id and value is None})
    )
    contributions = _contributions(*pairs)
    if any(value is None for value in (current_left, current_right, prior_left, prior_right)):
        return ConditionEvaluation(False, contributions, missing)
    assert current_left is not None and current_right is not None
    assert prior_left is not None and prior_right is not None
    if condition.type == "cross_up":
        passed = prior_left <= prior_right and current_left > current_right
    else:
        passed = prior_left >= prior_right and current_left < current_right
    return ConditionEvaluation(passed, contributions, missing)


def _evaluate_rank(
    condition: RankCondition, context: ConditionContext
) -> ConditionEvaluation:
    values: list[tuple[str, float]] = []
    for symbol in context.history_by_symbol:
        scoped = ConditionContext(symbol=symbol, history_by_symbol=context.history_by_symbol)
        value, _ = scoped.operand_value(condition.factor)
        if value is not None:
            values.append((symbol, value))
    values.sort(
        key=lambda item: (
            -item[1] if condition.higher_is_better else item[1],
            item[0],
        )
    )
    ranks = {symbol: index + 1 for index, (symbol, _) in enumerate(values)}
    current, _ = context.operand_value(condition.factor)
    if current is None or context.symbol not in ranks:
        return ConditionEvaluation(False, {}, (condition.factor.factor_id,))
    if condition.mode == "top_n":
        assert condition.top_n is not None
        passed = ranks[context.symbol] <= condition.top_n
    else:
        assert condition.percentile is not None
        cutoff = max(1, math.ceil(len(values) * condition.percentile))
        passed = ranks[context.symbol] <= cutoff
    return ConditionEvaluation(
        passed,
        {condition.factor.factor_id: current},
        (),
    )


def _evaluate_changed(
    condition: ChangedCondition, context: ConditionContext
) -> ConditionEvaluation:
    current, factor_id = context.operand_value(condition.factor)
    prior, _ = context.operand_value(
        condition.factor, additional_lag=condition.periods
    )
    if current is None or prior is None:
        return ConditionEvaluation(False, {}, (condition.factor.factor_id,))
    change = current - prior
    return ConditionEvaluation(
        _compare(change, condition.operator, condition.threshold),
        {factor_id or condition.factor.factor_id: change},
        (),
    )


def _merge_evaluations(
    passed: bool, children: Sequence[ConditionEvaluation]
) -> ConditionEvaluation:
    contributions: dict[str, float] = {}
    missing: set[str] = set()
    for child in children:
        contributions.update(child.contributions)
        missing.update(child.missing_factors)
    return ConditionEvaluation(passed, contributions, tuple(sorted(missing)))


def _contributions(*pairs: tuple[float | None, str | None]) -> dict[str, float]:
    return {
        factor_id: value
        for value, factor_id in pairs
        if value is not None and factor_id is not None
    }


def _compare(left: float, operator: str, right: float) -> bool:
    return {
        "gt": left > right,
        "gte": left >= right,
        "lt": left < right,
        "lte": left <= right,
        "eq": left == right,
        "neq": left != right,
    }[operator]


@dataclass
class _NumericConstraint:
    lower: float | None = None
    lower_inclusive: bool = True
    upper: float | None = None
    upper_inclusive: bool = True
    equals: float | None = None
    not_equals: set[float] = field(default_factory=set)

    def apply(
        self,
        operator: StrategyCompareOperator,
        value: float,
        upper: float | None,
    ) -> None:
        if operator in {StrategyCompareOperator.GT, StrategyCompareOperator.GTE}:
            inclusive = operator == StrategyCompareOperator.GTE
            if self.lower is None or value > self.lower:
                self.lower, self.lower_inclusive = value, inclusive
            elif value == self.lower:
                self.lower_inclusive = self.lower_inclusive and inclusive
        elif operator in {StrategyCompareOperator.LT, StrategyCompareOperator.LTE}:
            inclusive = operator == StrategyCompareOperator.LTE
            if self.upper is None or value < self.upper:
                self.upper, self.upper_inclusive = value, inclusive
            elif value == self.upper:
                self.upper_inclusive = self.upper_inclusive and inclusive
        elif operator == StrategyCompareOperator.EQ:
            if self.equals is None:
                self.equals = value
            elif self.equals != value:
                self.lower, self.upper = 1, 0
        elif operator == StrategyCompareOperator.NEQ:
            self.not_equals.add(value)
        elif operator == StrategyCompareOperator.BETWEEN:
            assert upper is not None
            self.apply(StrategyCompareOperator.GTE, value, None)
            self.apply(StrategyCompareOperator.LTE, upper, None)

    @property
    def impossible(self) -> bool:
        if self.lower is not None and self.upper is not None:
            if self.lower > self.upper:
                return True
            if self.lower == self.upper and not (
                self.lower_inclusive and self.upper_inclusive
            ):
                return True
        if self.equals is not None:
            if self.equals in self.not_equals:
                return True
            if self.lower is not None and (
                self.equals < self.lower
                or (self.equals == self.lower and not self.lower_inclusive)
            ):
                return True
            if self.upper is not None and (
                self.equals > self.upper
                or (self.equals == self.upper and not self.upper_inclusive)
            ):
                return True
        return False


def _factor_constant_comparison(
    condition: CompareCondition,
) -> tuple[
    str,
    StrategyCompareOperator,
    float,
    float | None,
] | None:
    if isinstance(condition.left, FactorOperand) and isinstance(
        condition.right, ConstantOperand
    ):
        upper = (
            condition.upper.value
            if isinstance(condition.upper, ConstantOperand)
            else None
        )
        return (
            condition.left.factor_id,
            condition.operator,
            condition.right.value,
            upper,
        )
    if (
        isinstance(condition.left, ConstantOperand)
        and isinstance(condition.right, FactorOperand)
        and condition.operator != StrategyCompareOperator.BETWEEN
    ):
        reverse = {
            StrategyCompareOperator.GT: StrategyCompareOperator.LT,
            StrategyCompareOperator.GTE: StrategyCompareOperator.LTE,
            StrategyCompareOperator.LT: StrategyCompareOperator.GT,
            StrategyCompareOperator.LTE: StrategyCompareOperator.GTE,
            StrategyCompareOperator.EQ: StrategyCompareOperator.EQ,
            StrategyCompareOperator.NEQ: StrategyCompareOperator.NEQ,
        }[condition.operator]
        return condition.right.factor_id, reverse, condition.left.value, None
    return None
