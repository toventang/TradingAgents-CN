"""Static validation for the closed, executable-free strategy DSL."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field as dataclass_field
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError

from app.models.factor import FactorDefinition, FactorStatus
from app.models.strategy import (
    SYSTEM_USER_ID,
    AllCondition,
    AnyCondition,
    ChangedCondition,
    CrossCondition,
    FrozenFactorDependency,
    FrozenSkillDependency,
    NotCondition,
    StrategyCondition,
    StrategyDefinitionDSL,
    StrategyValidationIssue,
    StrategyValidationResult,
    utc_now,
)
from app.models.symbol import Market
from app.services.factors.registry import FactorRegistry, global_factor_registry
from app.services.strategies.condition_tree import (
    collect_condition_factors,
    condition_tree_stats,
    impossible_all_constraints,
)


class SkillVersionAccess(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    skill_version_id: str = Field(min_length=1, max_length=128)
    skill_id: str = Field(min_length=1, max_length=128)
    version: StrictInt = Field(ge=1)
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["draft", "published", "deprecated"]
    user_id: str
    visibility: Literal["private", "shared_readonly", "system"] = "private"

    def readable_by(self, user_id: str) -> bool:
        return (
            self.user_id == user_id
            or self.user_id == SYSTEM_USER_ID
            or self.visibility in {"shared_readonly", "system"}
        )


@dataclass(frozen=True)
class DSLValidationReport:
    definition: StrategyDefinitionDSL | None
    errors: tuple[StrategyValidationIssue, ...]
    warnings: tuple[StrategyValidationIssue, ...]
    factor_dependencies: tuple[FrozenFactorDependency, ...] = ()
    skill_dependencies: tuple[FrozenSkillDependency, ...] = ()
    validated_at: datetime = dataclass_field(default_factory=utc_now)

    @property
    def valid(self) -> bool:
        return not self.errors and self.definition is not None

    def as_lifecycle_result(self) -> StrategyValidationResult:
        return StrategyValidationResult(
            valid=self.valid,
            errors=self.errors,
            warnings=self.warnings,
            validated_at=self.validated_at,
        )


class DSLValidationError(ValueError):
    def __init__(self, report: DSLValidationReport):
        self.report = report
        message = "; ".join(item.message for item in report.errors)
        super().__init__(message or "strategy DSL validation failed")


class StrategyDSLValidator:
    def __init__(
        self,
        registry: FactorRegistry | None = None,
        *,
        max_depth: int = 10,
        max_nodes: int = 200,
        clock: Callable[[], datetime] = utc_now,
    ):
        if max_depth < 1 or max_nodes < 1:
            raise ValueError("condition-tree limits must be positive")
        self.registry = registry or global_factor_registry
        self.max_depth = max_depth
        self.max_nodes = max_nodes
        self._clock = clock

    def validate(
        self,
        definition: StrategyDefinitionDSL | Mapping[str, Any],
        *,
        market: Market,
        user_id: str,
        additional_factors: Mapping[tuple[str, int], FactorDefinition] | None = None,
        skills: Mapping[str, SkillVersionAccess] | None = None,
    ) -> DSLValidationReport:
        errors: list[StrategyValidationIssue] = []
        warnings: list[StrategyValidationIssue] = []
        try:
            parsed = (
                definition
                if isinstance(definition, StrategyDefinitionDSL)
                else StrategyDefinitionDSL.model_validate(definition)
            )
        except ValidationError as exc:
            for item in exc.errors(include_url=False):
                path = ".".join(str(part) for part in item["loc"])
                errors.append(
                    _issue(
                        "DSL_SCHEMA_INVALID",
                        str(item["msg"]),
                        path=path or None,
                    )
                )
            return DSLValidationReport(
                definition=None,
                errors=tuple(errors),
                warnings=(),
                validated_at=self._clock(),
            )

        self._validate_condition_trees(parsed, errors)
        self._validate_static_conflicts(parsed, market, errors, warnings)
        factor_dependencies = self._validate_factors(
            parsed,
            market=market,
            additional_factors=additional_factors or {},
            errors=errors,
            warnings=warnings,
        )
        skill_dependencies = self._validate_skills(
            parsed,
            user_id=user_id,
            skills=skills or {},
            errors=errors,
        )
        return DSLValidationReport(
            definition=parsed,
            errors=tuple(errors),
            warnings=tuple(warnings),
            factor_dependencies=factor_dependencies,
            skill_dependencies=skill_dependencies,
            validated_at=self._clock(),
        )

    def validate_or_raise(
        self,
        definition: StrategyDefinitionDSL | Mapping[str, Any],
        *,
        market: Market,
        user_id: str,
        additional_factors: Mapping[tuple[str, int], FactorDefinition] | None = None,
        skills: Mapping[str, SkillVersionAccess] | None = None,
    ) -> StrategyDefinitionDSL:
        report = self.validate(
            definition,
            market=market,
            user_id=user_id,
            additional_factors=additional_factors,
            skills=skills,
        )
        if not report.valid:
            raise DSLValidationError(report)
        assert report.definition is not None
        return report.definition

    def validate_strategy_spec(
        self,
        definition: StrategyDefinitionDSL | Mapping[str, Any],
        *,
        market: Market = Market.CN,
        user_id: str = "validation",
    ) -> set[str]:
        """Convenience entry point returning the validated factor ID set."""

        report = self.validate(definition, market=market, user_id=user_id)
        if not report.valid:
            raise DSLValidationError(report)
        return {item.factor_id for item in report.factor_dependencies}

    def _validate_condition_trees(
        self,
        definition: StrategyDefinitionDSL,
        errors: list[StrategyValidationIssue],
    ) -> None:
        trees = (
            ("entry.condition", definition.entry.condition),
            ("exit.condition", definition.exit.condition),
        )
        for path, condition in trees:
            if condition is None:
                continue
            stats = condition_tree_stats(condition)
            if stats.depth > self.max_depth:
                errors.append(
                    _issue(
                        "CONDITION_TREE_TOO_DEEP",
                        f"condition tree depth {stats.depth} exceeds {self.max_depth}",
                        path=path,
                    )
                )
            if stats.nodes > self.max_nodes:
                errors.append(
                    _issue(
                        "CONDITION_TREE_TOO_LARGE",
                        f"condition tree node count {stats.nodes} exceeds {self.max_nodes}",
                        path=path,
                    )
                )
            for factor_id in impossible_all_constraints(condition):
                errors.append(
                    _issue(
                        "IMPOSSIBLE_CONDITION",
                        f"conjunctive bounds for {factor_id} can never be true",
                        path=path,
                    )
                )

    def _validate_static_conflicts(
        self,
        definition: StrategyDefinitionDSL,
        market: Market,
        errors: list[StrategyValidationIssue],
        warnings: list[StrategyValidationIssue],
    ) -> None:
        if definition.benchmark.market != market:
            errors.append(
                _issue(
                    "BENCHMARK_MARKET_MISMATCH",
                    "benchmark market must match the strategy market",
                    path="benchmark.market",
                )
            )
        execution = definition.execution
        if execution.execution_time in {"same_open", "same_close"}:
            errors.append(
                _issue(
                    "ILLEGAL_EXECUTION_TIMING",
                    "signals cannot execute at the price point that creates them",
                    path="execution.execution_time",
                )
            )
        if execution.execution_time == "next_open" and execution.price != "open":
            errors.append(
                _issue(
                    "EXECUTION_PRICE_MISMATCH",
                    "next_open execution requires open price",
                    path="execution.price",
                )
            )
        if execution.execution_time == "next_close" and execution.price not in {
            "close",
            "vwap",
        }:
            errors.append(
                _issue(
                    "EXECUTION_PRICE_MISMATCH",
                    "next_close execution requires close or vwap price",
                    path="execution.price",
                )
            )
        portfolio = definition.portfolio
        investable = 1 - portfolio.min_cash_ratio
        capacity = portfolio.max_positions * portfolio.max_position_weight
        if portfolio.weighting != "fixed_weight" and capacity + 1e-12 < investable:
            errors.append(
                _issue(
                    "PORTFOLIO_CAPACITY_CONFLICT",
                    "position count and per-position cap cannot allocate the investable ratio",
                    path="portfolio",
                )
            )
        if portfolio.max_industry_weight < portfolio.max_position_weight:
            warnings.append(
                _issue(
                    "INDUSTRY_CAP_TIGHTER_THAN_POSITION_CAP",
                    "industry cap will further constrain the per-position maximum",
                    path="portfolio.max_industry_weight",
                )
            )
        ranking = definition.entry.ranking
        if ranking is not None and ranking.top_n is not None:
            if ranking.top_n > portfolio.max_positions:
                warnings.append(
                    _issue(
                        "RANKING_EXCEEDS_PORTFOLIO_CAP",
                        "ranking cutoff exceeds max_positions and will be capped",
                        path="entry.ranking.top_n",
                    )
                )
        required_history = _required_history(definition)
        if definition.data.minimum_history < required_history:
            errors.append(
                _issue(
                    "INSUFFICIENT_DECLARED_HISTORY",
                    f"minimum_history must be at least {required_history}",
                    path="data.minimum_history",
                )
            )

    def _validate_factors(
        self,
        definition: StrategyDefinitionDSL,
        *,
        market: Market,
        additional_factors: Mapping[tuple[str, int], FactorDefinition],
        errors: list[StrategyValidationIssue],
        warnings: list[StrategyValidationIssue],
    ) -> tuple[FrozenFactorDependency, ...]:
        feature_map = {
            (item.factor_id, item.version): item for item in definition.features
        }
        referenced = _factor_references(definition)
        for key in sorted(referenced - set(feature_map)):
            errors.append(
                _issue(
                    "UNDECLARED_FACTOR_REFERENCE",
                    f"factor {key[0]} v{key[1]} is referenced but absent from features",
                    path="features",
                )
            )
        for key in sorted(set(feature_map) - referenced):
            warnings.append(
                _issue(
                    "UNUSED_FACTOR_FEATURE",
                    f"factor {key[0]} v{key[1]} is declared but unused",
                    path="features",
                )
            )

        dependencies: list[FrozenFactorDependency] = []
        for key, feature in sorted(feature_map.items()):
            factor = additional_factors.get(key)
            if factor is None:
                candidate = self.registry.get_by_id(feature.factor_id)
                if candidate is not None and candidate.version == feature.version:
                    factor = candidate
            if factor is None:
                errors.append(
                    _issue(
                        "UNKNOWN_FACTOR_VERSION",
                        f"factor {feature.factor_id} v{feature.version} is not registered",
                        path="features",
                    )
                )
                continue
            if factor.status != FactorStatus.ACTIVE:
                errors.append(
                    _issue(
                        "FACTOR_NOT_ACTIVE",
                        f"factor {feature.factor_id} v{feature.version} is not active",
                        path="features",
                    )
                )
            if market not in factor.supported_markets:
                errors.append(
                    _issue(
                        "FACTOR_MARKET_UNSUPPORTED",
                        f"factor {feature.factor_id} does not support {market.value}",
                        path="features",
                    )
                )
            try:
                factor.resolve_params(feature.params)
            except ValueError as exc:
                errors.append(
                    _issue(
                        "FACTOR_PARAMS_INVALID",
                        f"{feature.factor_id}: {exc}",
                        path="features",
                    )
                )
            dependencies.append(
                FrozenFactorDependency(
                    factor_id=factor.factor_id,
                    version=factor.version,
                    checksum=factor.checksum,
                )
            )
        return tuple(dependencies)

    @staticmethod
    def _validate_skills(
        definition: StrategyDefinitionDSL,
        *,
        user_id: str,
        skills: Mapping[str, SkillVersionAccess],
        errors: list[StrategyValidationIssue],
    ) -> tuple[FrozenSkillDependency, ...]:
        if definition.analysis is None:
            return ()
        dependencies: list[FrozenSkillDependency] = []
        for version_id in definition.analysis.skill_version_ids:
            skill = skills.get(version_id)
            if skill is None:
                errors.append(
                    _issue(
                        "SKILL_VERSION_NOT_FOUND",
                        f"Skill version {version_id} was not found",
                        path="analysis.skill_version_ids",
                    )
                )
                continue
            if skill.status != "published":
                errors.append(
                    _issue(
                        "SKILL_VERSION_NOT_PUBLISHED",
                        f"Skill version {version_id} is not published",
                        path="analysis.skill_version_ids",
                    )
                )
            if not skill.readable_by(user_id):
                errors.append(
                    _issue(
                        "SKILL_VERSION_FORBIDDEN",
                        f"Skill version {version_id} is not readable by this user",
                        path="analysis.skill_version_ids",
                    )
                )
            dependencies.append(
                FrozenSkillDependency(
                    skill_id=skill.skill_id,
                    version=skill.version,
                    checksum=skill.checksum,
                )
            )
        return tuple(dependencies)


def _issue(code: str, message: str, *, path: str | None = None) -> StrategyValidationIssue:
    return StrategyValidationIssue(code=code, message=message, path=path)


def _factor_references(definition: StrategyDefinitionDSL) -> set[tuple[str, int]]:
    result: set[tuple[str, int]] = set()
    for condition in (definition.entry.condition, definition.exit.condition):
        if condition is not None:
            result.update(
                (item.factor_id, item.version)
                for item in collect_condition_factors(condition)
            )
    if definition.entry.ranking is not None:
        result.update(
            (item.factor.factor_id, item.factor.version)
            for item in definition.entry.ranking.factors
        )
    if definition.portfolio.volatility_factor is not None:
        factor = definition.portfolio.volatility_factor
        result.add((factor.factor_id, factor.version))
    return result


def _required_history(definition: StrategyDefinitionDSL) -> int:
    required = 1

    def visit(condition: StrategyCondition) -> None:
        nonlocal required
        for factor in collect_condition_factors(condition):
            required = max(required, factor.lag + 1)
        if isinstance(condition, (AllCondition, AnyCondition)):
            for child in condition.children:
                visit(child)
        elif isinstance(condition, NotCondition):
            visit(condition.child)
        elif isinstance(condition, CrossCondition):
            required = max(
                required,
                condition.periods
                + max(
                    getattr(condition.left, "lag", 0),
                    getattr(condition.right, "lag", 0),
                )
                + 1,
            )
        elif isinstance(condition, ChangedCondition):
            required = max(required, condition.periods + condition.factor.lag + 1)

    for condition in (definition.entry.condition, definition.exit.condition):
        if condition is not None:
            visit(condition)
    return required
