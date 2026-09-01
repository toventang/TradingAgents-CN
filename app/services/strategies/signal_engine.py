"""Deterministic strategy signal preview over fixed immutable snapshots."""

from __future__ import annotations

import hashlib
import math
import statistics
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.factor import (
    FactorDefinition,
    FactorSnapshot,
    FactorSnapshotStatus,
    FactorValueRow,
)
from app.models.strategy import (
    SYSTEM_USER_ID,
    StrategyDefinitionDSL,
    StrategySignal,
    StrategyVersion,
    StrategyVersionStatus,
    UniverseSnapshot,
)
from app.services.strategies.condition_tree import (
    ConditionContext,
    FactorHistory,
    evaluate_condition,
)
from app.services.strategies.validator import (
    DSLValidationError,
    SkillVersionAccess,
    StrategyDSLValidator,
)


class SignalInputError(ValueError):
    """Fixed snapshot inputs violate ownership, completeness, or time boundaries."""


class PositionState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str = Field(min_length=1, max_length=64)
    return_since_entry: float = 0
    holding_periods: int = Field(default=0, ge=0)

    @field_validator("return_since_entry")
    @classmethod
    def require_finite_return(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("return_since_entry must be finite")
        return value


class SignalEngineResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy_version_id: str
    universe_snapshot_id: str
    factor_snapshot_ids: tuple[str, ...]
    signal_date: date
    as_of: datetime
    signals: tuple[StrategySignal, ...]

    @field_validator("as_of")
    @classmethod
    def require_aware_as_of(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        return value.astimezone(timezone.utc)


class DeterministicSignalEngine:
    def __init__(self, validator: StrategyDSLValidator | None = None):
        self.validator = validator or StrategyDSLValidator()

    def evaluate(
        self,
        *,
        version: StrategyVersion,
        universe: UniverseSnapshot,
        factor_snapshots: Sequence[FactorSnapshot],
        factor_rows: Sequence[FactorValueRow],
        as_of: datetime,
        user_id: str | None = None,
        metadata_by_symbol: Mapping[str, Mapping[str, Any]] | None = None,
        positions: Mapping[str, PositionState] | None = None,
        portfolio_drawdown: float = 0,
        cooldown_remaining: int = 0,
        additional_factors: Mapping[tuple[str, int], FactorDefinition] | None = None,
        skills: Mapping[str, SkillVersionAccess] | None = None,
    ) -> SignalEngineResult:
        evaluation_as_of = _aware_utc(as_of, "as_of")
        owner = user_id or universe.user_id
        self._validate_owner_and_version(version, universe, owner)
        report = self.validator.validate(
            version.definition,
            market=version.market,
            user_id=owner,
            additional_factors=additional_factors,
            skills=skills,
        )
        if not report.valid:
            raise DSLValidationError(report)
        assert report.definition is not None
        definition = report.definition
        if (
            definition.universe.snapshot_id is not None
            and definition.universe.snapshot_id != universe.universe_snapshot_id
        ):
            raise SignalInputError("DSL universe snapshot_id does not match the input")
        self._validate_frozen_dependencies(
            version,
            report.factor_dependencies,
            report.skill_dependencies,
        )
        ordered_snapshots = self._validate_snapshots(
            universe,
            factor_snapshots,
            owner=owner,
            as_of=evaluation_as_of,
            minimum_history=definition.data.minimum_history,
        )
        history = self._build_history(
            universe,
            ordered_snapshots,
            factor_rows,
            definition,
        )
        signals = self._evaluate_signals(
            version=version,
            universe=universe,
            snapshots=ordered_snapshots,
            definition=definition,
            history=history,
            as_of=evaluation_as_of,
            owner=owner,
            metadata_by_symbol=metadata_by_symbol or {},
            positions=positions or {},
            portfolio_drawdown=portfolio_drawdown,
            cooldown_remaining=cooldown_remaining,
        )
        return SignalEngineResult(
            strategy_version_id=version.strategy_version_id,
            universe_snapshot_id=universe.universe_snapshot_id,
            factor_snapshot_ids=tuple(item.snapshot_id for item in ordered_snapshots),
            signal_date=universe.trade_date,
            as_of=evaluation_as_of,
            signals=signals,
        )

    execute = evaluate

    @staticmethod
    def _validate_owner_and_version(
        version: StrategyVersion,
        universe: UniverseSnapshot,
        owner: str,
    ) -> None:
        if universe.user_id != owner:
            raise SignalInputError("universe snapshot is not owner-visible")
        if version.user_id not in {owner, SYSTEM_USER_ID}:
            raise SignalInputError("strategy version is not owner-visible")
        if version.market != universe.market:
            raise SignalInputError("strategy and universe markets do not match")
        if version.status == StrategyVersionStatus.VALIDATING:
            raise SignalInputError("a validating strategy cannot be executed")
        if universe.as_of.astimezone(_market_zone(universe.market)).date() != universe.trade_date:
            raise SignalInputError("universe snapshot as_of must fall on its market trade date")

    @staticmethod
    def _validate_frozen_dependencies(
        version, resolved_factor_dependencies, resolved_skill_dependencies
    ) -> None:
        if version.status not in {
            StrategyVersionStatus.PUBLISHED,
            StrategyVersionStatus.DEPRECATED,
        }:
            return
        frozen = {
            (item.factor_id, item.version, item.checksum)
            for item in version.factor_dependencies
        }
        resolved = {
            (item.factor_id, item.version, item.checksum)
            for item in resolved_factor_dependencies
        }
        if frozen != resolved:
            raise SignalInputError(
                "published strategy factor dependencies do not match the validated DSL"
            )
        frozen_skills = {
            (item.skill_id, item.version, item.checksum)
            for item in version.skill_dependencies
        }
        resolved_skills = {
            (item.skill_id, item.version, item.checksum)
            for item in resolved_skill_dependencies
        }
        if frozen_skills != resolved_skills:
            raise SignalInputError(
                "published strategy Skill dependencies do not match the validated DSL"
            )

    @staticmethod
    def _validate_snapshots(
        universe: UniverseSnapshot,
        snapshots: Sequence[FactorSnapshot],
        *,
        owner: str,
        as_of: datetime,
        minimum_history: int,
    ) -> tuple[FactorSnapshot, ...]:
        if not snapshots:
            raise SignalInputError("at least one ready factor snapshot is required")
        if universe.as_of > as_of:
            raise SignalInputError("universe snapshot was not visible by evaluation as_of")
        ordered = tuple(sorted(snapshots, key=lambda item: (item.trade_date, item.snapshot_id)))
        if len({item.snapshot_id for item in ordered}) != len(ordered):
            raise SignalInputError("factor snapshot IDs must be unique")
        if len({item.trade_date for item in ordered}) != len(ordered):
            raise SignalInputError("factor snapshots must have unique trade dates")
        if len(ordered) < minimum_history:
            raise SignalInputError(
                f"factor snapshots provide {len(ordered)} periods; {minimum_history} required"
            )
        for snapshot in ordered:
            if snapshot.status != FactorSnapshotStatus.READY:
                raise SignalInputError("signal evaluation requires ready factor snapshots")
            if snapshot.user_id != owner:
                raise SignalInputError("factor snapshot is not owner-visible")
            if snapshot.market != universe.market:
                raise SignalInputError("factor snapshot market does not match universe")
            if snapshot.universe_snapshot_id != universe.universe_snapshot_id:
                raise SignalInputError("factor snapshots must use the fixed universe snapshot")
            if snapshot.trade_date > universe.trade_date:
                raise SignalInputError("future factor snapshot trade_date is not visible")
            if (
                snapshot.as_of.astimezone(_market_zone(snapshot.market)).date()
                != snapshot.trade_date
            ):
                raise SignalInputError(
                    "factor snapshot as_of must fall on its market trade date"
                )
            if snapshot.as_of > as_of:
                raise SignalInputError("future factor snapshot as_of is not visible")
            if snapshot.published_at is None or snapshot.published_at > as_of:
                raise SignalInputError("factor snapshot was not published by evaluation as_of")
        if ordered[-1].trade_date != universe.trade_date:
            raise SignalInputError("latest factor snapshot must match the signal trade date")
        return ordered

    @staticmethod
    def _build_history(
        universe: UniverseSnapshot,
        snapshots: Sequence[FactorSnapshot],
        rows: Sequence[FactorValueRow],
        definition: StrategyDefinitionDSL,
    ) -> dict[str, dict[str, tuple[float | None, ...]]]:
        snapshot_by_id = {item.snapshot_id: item for item in snapshots}
        member_symbols = {item.symbol for item in universe.members}
        row_by_key: dict[tuple[str, str], FactorValueRow] = {}
        for row in rows:
            snapshot = snapshot_by_id.get(row.snapshot_id)
            if snapshot is None:
                raise SignalInputError("factor row references an unselected snapshot")
            if row.market != universe.market or row.symbol not in member_symbols:
                raise SignalInputError("factor row falls outside the fixed universe")
            if row.trade_date != snapshot.trade_date:
                raise SignalInputError("factor row trade_date does not match its snapshot")
            key = (row.snapshot_id, row.symbol)
            if key in row_by_key:
                raise SignalInputError("factor rows must be unique per snapshot and symbol")
            row_by_key[key] = row

        allowed_quality = set(definition.data.allowed_quality)
        history: dict[str, dict[str, tuple[float | None, ...]]] = {}
        for symbol in sorted(member_symbols):
            factor_values: dict[str, tuple[float | None, ...]] = {}
            for feature in definition.features:
                series: list[float | None] = []
                for snapshot in snapshots:
                    row = row_by_key.get((snapshot.snapshot_id, symbol))
                    value = None if row is None else row.values.get(feature.factor_id)
                    quality = None if row is None else row.quality.get(feature.factor_id)
                    quality_ok = quality is None or str(quality).lower() in allowed_quality
                    if (
                        value is None
                        or not quality_ok
                        or not math.isfinite(float(value))
                    ):
                        series.append(None)
                    else:
                        series.append(float(value))
                factor_values[feature.factor_id] = tuple(series)
            history[symbol] = factor_values
        return history

    def _evaluate_signals(
        self,
        *,
        version: StrategyVersion,
        universe: UniverseSnapshot,
        snapshots: Sequence[FactorSnapshot],
        definition: StrategyDefinitionDSL,
        history: FactorHistory,
        as_of: datetime,
        owner: str,
        metadata_by_symbol: Mapping[str, Mapping[str, Any]],
        positions: Mapping[str, PositionState],
        portfolio_drawdown: float,
        cooldown_remaining: int,
    ) -> tuple[StrategySignal, ...]:
        if not math.isfinite(portfolio_drawdown):
            raise SignalInputError("portfolio_drawdown must be finite")
        if cooldown_remaining < 0:
            raise SignalInputError("cooldown_remaining cannot be negative")
        if any(key != value.symbol for key, value in positions.items()):
            raise SignalInputError("position mapping keys must match position symbols")
        universe_symbols = {item.symbol for item in universe.members}
        eligible = {
            symbol
            for symbol in universe_symbols
            if _passes_universe_filters(
                definition,
                metadata_by_symbol.get(symbol),
            )
        }
        scoped_history = {symbol: history[symbol] for symbol in sorted(eligible)}
        condition_results = {}
        candidates: list[str] = []
        for symbol in sorted(eligible):
            if symbol in positions:
                continue
            if definition.entry.condition is None:
                condition_results[symbol] = None
                candidates.append(symbol)
                continue
            result = evaluate_condition(
                definition.entry.condition,
                ConditionContext(symbol=symbol, history_by_symbol=scoped_history),
            )
            condition_results[symbol] = result
            if result.passed and not result.missing_factors:
                candidates.append(symbol)

        scores, ranking_contributions, missing_ranking = _rank_candidates(
            candidates,
            definition,
            scoped_history,
        )
        candidates = [symbol for symbol in candidates if symbol not in missing_ranking]
        if definition.portfolio.weighting == "fixed_weight":
            fixed_symbols = set(definition.portfolio.fixed_weights)
            candidates = [symbol for symbol in candidates if symbol in fixed_symbols]
            scores = {symbol: scores[symbol] for symbol in candidates}
            ranking_contributions = {
                symbol: ranking_contributions.get(symbol, {}) for symbol in candidates
            }
        tie_desc = (
            definition.entry.ranking is not None
            and definition.entry.ranking.tie_breaker == "symbol_desc"
        )
        ranked = sorted(candidates, reverse=tie_desc)
        ranked.sort(key=lambda symbol: scores.get(symbol, 1.0), reverse=True)
        ranks = {symbol: index + 1 for index, symbol in enumerate(ranked)}
        non_positive_scores = (
            {
                symbol
                for symbol in ranked
                if scores.get(symbol, 0) <= 0
            }
            if definition.portfolio.weighting == "score_weight"
            else set()
        )
        selectable_ranked = [
            symbol for symbol in ranked if symbol not in non_positive_scores
        ]
        cutoff = _selection_cutoff(definition, len(selectable_ranked))
        selected = set(selectable_ranked[:cutoff])
        can_rebalance = _is_rebalance_day(definition, universe.trade_date)
        drawdown_stopped = (
            definition.risk.max_drawdown_stop is not None
            and portfolio_drawdown <= -definition.risk.max_drawdown_stop
        )
        if not can_rebalance or drawdown_stopped or cooldown_remaining > 0:
            selected.clear()

        signals: list[StrategySignal] = []
        all_symbols = sorted(universe_symbols | set(positions))
        latest_snapshot_id = snapshots[-1].snapshot_id
        for symbol in all_symbols:
            contributions: dict[str, float] = {}
            rank = ranks.get(symbol)
            score = scores.get(symbol)
            signal_type = "hold"
            reasons: list[str] = []
            position = positions.get(symbol)
            if position is not None:
                signal_type, reasons, contributions = _position_signal(
                    symbol,
                    position,
                    definition,
                    scoped_history,
                    symbol in eligible,
                )
            elif symbol not in eligible:
                reasons.append("UNIVERSE_FILTERED")
            elif symbol in missing_ranking:
                reasons.append("MISSING_FACTOR")
            elif symbol not in candidates:
                result = condition_results.get(symbol)
                if result is not None:
                    contributions.update(
                        {f"condition:{key}": value for key, value in result.contributions.items()}
                    )
                    reasons.append(
                        "MISSING_FACTOR"
                        if result.missing_factors
                        else "ENTRY_CONDITION_FAILED"
                    )
                else:
                    reasons.append("ENTRY_CONDITION_FAILED")
            elif symbol in selected:
                signal_type = "buy"
                reasons.append("ENTRY_SELECTED")
            elif not can_rebalance:
                reasons.append("NOT_REBALANCE_DAY")
            elif drawdown_stopped:
                reasons.append("RISK_DRAWDOWN_STOP")
            elif cooldown_remaining > 0:
                reasons.append("COOLDOWN_ACTIVE")
            elif symbol in non_positive_scores:
                reasons.append("NON_POSITIVE_SCORE")
            else:
                reasons.append("RANK_CUTOFF")

            result = condition_results.get(symbol)
            if result is not None:
                contributions.update(
                    {f"condition:{key}": value for key, value in result.contributions.items()}
                )
            contributions.update(ranking_contributions.get(symbol, {}))
            signals.append(
                StrategySignal(
                    signal_id=_signal_id(
                        version.strategy_version_id,
                        universe.universe_snapshot_id,
                        universe.trade_date.isoformat(),
                        symbol,
                        signal_type,
                    ),
                    user_id=owner,
                    strategy_version_id=version.strategy_version_id,
                    universe_snapshot_id=universe.universe_snapshot_id,
                    factor_snapshot_id=latest_snapshot_id,
                    market=universe.market,
                    symbol=symbol,
                    signal_date=universe.trade_date,
                    signal_type=signal_type,
                    score=score,
                    rank=rank,
                    reason_codes=tuple(dict.fromkeys(reasons)),
                    input_contributions=dict(sorted(contributions.items())),
                    as_of=as_of,
                    created_at=as_of,
                )
            )
        return tuple(signals)


def _rank_candidates(
    candidates: Sequence[str],
    definition: StrategyDefinitionDSL,
    history: FactorHistory,
) -> tuple[dict[str, float], dict[str, dict[str, float]], set[str]]:
    if definition.entry.ranking is None:
        return ({symbol: 1.0 for symbol in candidates}, {}, set())
    scores = {symbol: 0.0 for symbol in candidates}
    contributions = {symbol: {} for symbol in candidates}
    missing: set[str] = set()
    for ranking_factor in definition.entry.ranking.factors:
        factor_id = ranking_factor.factor.factor_id
        lag = ranking_factor.factor.lag
        values: dict[str, float] = {}
        for symbol in candidates:
            series = history.get(symbol, {}).get(factor_id, ())
            if len(series) <= lag or series[-1 - lag] is None:
                missing.add(symbol)
            else:
                values[symbol] = float(series[-1 - lag])
        normalized = _normalize(values, ranking_factor.normalization)
        direction = 1.0 if ranking_factor.higher_is_better else -1.0
        for symbol, value in normalized.items():
            contribution = ranking_factor.weight * direction * value
            scores[symbol] += contribution
            contributions[symbol][factor_id] = contribution
    for symbol in missing:
        scores.pop(symbol, None)
        contributions.pop(symbol, None)
    return scores, contributions, missing


def _normalize(values: Mapping[str, float], method: str) -> dict[str, float]:
    if not values:
        return {}
    if method == "rank":
        ordered = sorted(values, key=lambda symbol: (values[symbol], symbol))
        if len(ordered) == 1:
            return {ordered[0]: 0.0}
        return {
            symbol: (2 * index / (len(ordered) - 1)) - 1
            for index, symbol in enumerate(ordered)
        }
    raw = list(values.values())
    if method == "robust_zscore":
        center = statistics.median(raw)
        scale = statistics.median(abs(value - center) for value in raw) * 1.4826
    else:
        center = statistics.fmean(raw)
        scale = statistics.pstdev(raw)
    if scale == 0:
        return {symbol: 0.0 for symbol in values}
    return {symbol: (value - center) / scale for symbol, value in values.items()}


def _selection_cutoff(definition: StrategyDefinitionDSL, candidate_count: int) -> int:
    ranking = definition.entry.ranking
    if ranking is None:
        requested = candidate_count
    elif ranking.top_n is not None:
        requested = ranking.top_n
    else:
        assert ranking.top_percent is not None
        requested = max(1, math.ceil(candidate_count * ranking.top_percent))
    requested = min(requested, definition.portfolio.max_positions)
    if definition.portfolio.weighting == "fixed_weight":
        requested = min(requested, len(definition.portfolio.fixed_weights))
    return max(0, requested)


def _passes_universe_filters(
    definition: StrategyDefinitionDSL,
    metadata: Mapping[str, Any] | None,
) -> bool:
    spec = definition.universe
    if spec.snapshot_id is not None:
        # Snapshot identity is checked by the engine; this branch deliberately
        # has no per-symbol behavior.
        pass
    filters_active = any(
        (
            spec.minimum_listing_days,
            spec.include_industries,
            spec.exclude_industries,
            spec.minimum_market_cap is not None,
            spec.maximum_market_cap is not None,
        )
    ) or spec.exclude_st or spec.exclude_delisting or spec.exclude_suspended
    if not filters_active:
        return True
    if metadata is None:
        return False
    try:
        listing_days = int(metadata.get("listing_days", -1))
    except (TypeError, ValueError):
        return False
    if listing_days < spec.minimum_listing_days:
        return False
    if spec.exclude_st and bool(metadata.get("is_st", True)):
        return False
    if spec.exclude_delisting and bool(metadata.get("is_delisting", True)):
        return False
    if spec.exclude_suspended and bool(metadata.get("is_suspended", True)):
        return False
    industry = metadata.get("industry")
    if spec.include_industries and industry not in spec.include_industries:
        return False
    if industry in spec.exclude_industries:
        return False
    market_cap = metadata.get("market_cap")
    try:
        numeric_market_cap = None if market_cap is None else float(market_cap)
    except (TypeError, ValueError):
        return False
    if numeric_market_cap is not None and not math.isfinite(numeric_market_cap):
        return False
    if spec.minimum_market_cap is not None and (
        numeric_market_cap is None or numeric_market_cap < spec.minimum_market_cap
    ):
        return False
    if spec.maximum_market_cap is not None and (
        numeric_market_cap is None or numeric_market_cap > spec.maximum_market_cap
    ):
        return False
    return True


def _position_signal(
    symbol: str,
    position: PositionState,
    definition: StrategyDefinitionDSL,
    history: FactorHistory,
    remains_eligible: bool,
) -> tuple[str, list[str], dict[str, float]]:
    reasons: list[str] = []
    contributions: dict[str, float] = {}
    if not remains_eligible:
        reasons.append("LEFT_UNIVERSE")
    if definition.exit.condition is not None and symbol in history:
        result = evaluate_condition(
            definition.exit.condition,
            ConditionContext(symbol=symbol, history_by_symbol=history),
        )
        contributions.update(
            {f"exit:{key}": value for key, value in result.contributions.items()}
        )
        if result.passed and not result.missing_factors:
            reasons.append("EXIT_CONDITION_MET")
    take_profit = definition.exit.take_profit or definition.risk.take_profit
    stop_loss = definition.exit.stop_loss or definition.risk.stop_loss
    if take_profit is not None and position.return_since_entry >= take_profit:
        reasons.append("TAKE_PROFIT")
    if stop_loss is not None and position.return_since_entry <= -stop_loss:
        reasons.append("STOP_LOSS")
    if (
        definition.exit.max_holding_periods is not None
        and position.holding_periods >= definition.exit.max_holding_periods
    ):
        reasons.append("TIME_EXIT")
    if reasons:
        return "sell", reasons, contributions
    return "hold", ["POSITION_HELD"], contributions


def _is_rebalance_day(definition: StrategyDefinitionDSL, signal_date) -> bool:
    rule = definition.rebalance
    if rule.frequency == "daily":
        return True
    if rule.frequency == "weekly":
        return signal_date.weekday() == rule.weekday
    return signal_date.day == rule.day_of_month


def _signal_id(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SignalInputError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _market_zone(market) -> ZoneInfo:
    return ZoneInfo(
        {
            "CN": "Asia/Shanghai",
            "HK": "Asia/Hong_Kong",
            "US": "America/New_York",
        }[market.value]
    )
