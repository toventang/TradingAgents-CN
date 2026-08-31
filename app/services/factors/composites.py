"""Closed, deterministic composite-factor validation, scoring, and lifecycle."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import numpy as np
import pandas as pd

from app.models.factor import (
    CompositeArithmeticKind,
    CompositeCreateRequest,
    CompositeDefinition,
    CompositeDependencyVersion,
    CompositeEvaluationResult,
    CompositeFactorResource,
    CompositeFactorTerm,
    CompositeMissingKind,
    CompositeNeutralizeKind,
    CompositeScoreRow,
    CompositeStatus,
    CompositeTransformKind,
    CompositeUpdateRequest,
    CompositeValidateRequest,
    CompositeValidationIssue,
    CompositeValidationResponse,
    FactorDirection,
)
from app.models.symbol import Market
from app.repositories.factor_repository import (
    FactorCompositeConflict,
    FactorRepository,
)
from app.services.factors.registry import FactorRegistry, global_factor_registry


class CompositeDslError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "COMPOSITE_INVALID",
        factor_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.factor_id = factor_id


class CompositeNotFound(LookupError):
    pass


class CompositeStateConflict(RuntimeError):
    code = "COMPOSITE_STATE_CONFLICT"


class CompositeDslEngine:
    """Executes only the operations represented by the closed model enums."""

    MINIMUM_REMAINING_WEIGHT = 0.60

    def __init__(self, registry: FactorRegistry | None = None) -> None:
        self.registry = registry or global_factor_registry

    def resolve(
        self, market: Market, definition: CompositeDefinition
    ) -> tuple[CompositeDefinition, tuple[CompositeDependencyVersion, ...], str]:
        total_absolute_weight = math.fsum(abs(term.weight) for term in definition.terms)
        if not math.isfinite(total_absolute_weight) or total_absolute_weight <= 0:
            raise CompositeDslError("composite absolute weight sum must be positive")

        normalized_terms: list[CompositeFactorTerm] = []
        dependencies: list[CompositeDependencyVersion] = []
        for term in definition.terms:
            factor_id = term.factor.factor_id
            factor = self.registry.get_by_id(factor_id)
            if factor is None:
                raise CompositeDslError(
                    f"unknown factor dependency: {factor_id}",
                    code="COMPOSITE_FACTOR_NOT_FOUND",
                    factor_id=factor_id,
                )
            if factor.version != term.factor.version:
                raise CompositeDslError(
                    f"factor {factor_id} version {term.factor.version} is unavailable",
                    code="COMPOSITE_FACTOR_VERSION_MISMATCH",
                    factor_id=factor_id,
                )
            if market not in factor.supported_markets:
                raise CompositeDslError(
                    f"factor {factor_id} does not support market {market.value}",
                    code="COMPOSITE_FACTOR_MARKET_UNSUPPORTED",
                    factor_id=factor_id,
                )
            try:
                params = factor.resolve_params(term.factor.params)
            except ValueError as exc:
                raise CompositeDslError(
                    str(exc),
                    code="COMPOSITE_FACTOR_PARAMS_INVALID",
                    factor_id=factor_id,
                ) from exc
            normalized_term = term.model_copy(
                update={
                    "factor": term.factor.model_copy(update={"params": params}),
                    "weight": term.weight / total_absolute_weight,
                }
            )
            normalized_terms.append(normalized_term)
            dependencies.append(
                CompositeDependencyVersion(
                    factor_id=factor_id,
                    version=factor.version,
                    params=params,
                    definition_checksum=factor.checksum,
                    direction=factor.direction,
                    effective_multiplier=(
                        -1
                        if definition.auto_direction
                        and factor.direction == FactorDirection.NEGATIVE
                        else 1
                    ),
                )
            )
        normalized = definition.model_copy(update={"terms": tuple(normalized_terms)})
        checksum = _definition_checksum(market, normalized, tuple(dependencies))
        return normalized, tuple(dependencies), checksum

    def validation_response(
        self, request: CompositeValidateRequest
    ) -> CompositeValidationResponse:
        try:
            normalized, dependencies, checksum = self.resolve(
                request.market, request.definition
            )
        except CompositeDslError as exc:
            return CompositeValidationResponse(
                valid=False,
                issues=[
                    CompositeValidationIssue(
                        code=exc.code,
                        message=str(exc),
                        factor_id=exc.factor_id,
                    )
                ],
            )
        return CompositeValidationResponse(
            valid=True,
            normalized_definition=normalized,
            dependencies=dependencies,
            definition_checksum=checksum,
        )

    def score(
        self,
        frame: pd.DataFrame,
        definition: CompositeDefinition,
        dependencies: tuple[CompositeDependencyVersion, ...],
    ) -> CompositeEvaluationResult:
        factor_ids = tuple(term.factor.factor_id for term in definition.terms)
        required = {"symbol", *factor_ids}
        missing_columns = sorted(required - set(frame.columns))
        if missing_columns:
            raise CompositeDslError(
                f"composite input is missing columns: {missing_columns}",
                code="COMPOSITE_INPUT_COLUMNS_MISSING",
            )
        dependency_by_factor = {item.factor_id: item for item in dependencies}
        if set(dependency_by_factor) != set(factor_ids):
            raise CompositeDslError(
                "resolved dependency set does not match composite terms",
                code="COMPOSITE_DEPENDENCY_SET_MISMATCH",
            )
        weight_sum = math.fsum(abs(term.weight) for term in definition.terms)
        if not math.isclose(weight_sum, 1.0, rel_tol=0.0, abs_tol=1e-12):
            raise CompositeDslError(
                "composite weights must be normalized before scoring",
                code="COMPOSITE_WEIGHTS_NOT_NORMALIZED",
            )

        working = frame.copy(deep=True)
        if "trade_date" in working:
            working["trade_date"] = pd.to_datetime(working["trade_date"]).dt.date
            identity = ["symbol", "trade_date"]
        else:
            identity = ["symbol"]
        if working.duplicated(identity).any():
            raise CompositeDslError("composite input contains duplicate identities")
        for factor_id in factor_ids:
            working[factor_id] = pd.to_numeric(
                working[factor_id], errors="coerce"
            ).replace([np.inf, -np.inf], np.nan)

        original_count = len(working)
        working = _apply_filters(working, definition, factor_ids)
        if working.empty:
            return CompositeEvaluationResult(
                rows=[], eligible_symbols=0, filtered_symbols=original_count
            )

        group_column = "trade_date" if "trade_date" in working else None
        groups = (
            working.groupby(group_column, sort=True, dropna=False)
            if group_column
            else [(None, working)]
        )
        output_rows: list[CompositeScoreRow] = []
        for trade_date, group in groups:
            transformed = pd.DataFrame(index=group.index)
            for term in definition.terms:
                factor_id = term.factor.factor_id
                series = _transform(group[factor_id], term)
                series = series * dependency_by_factor[factor_id].effective_multiplier
                transformed[factor_id] = _neutralize(
                    series, group, definition.neutralize
                )

            group_rows: list[dict[str, Any]] = []
            for row_index in group.index:
                values = {
                    factor_id: _finite(transformed.at[row_index, factor_id])
                    for factor_id in factor_ids
                }
                scored = _combine(values, definition)
                if scored is None:
                    continue
                raw_score, coverage, contributions = scored
                group_rows.append(
                    {
                        "row_index": row_index,
                        "raw_score": raw_score,
                        "coverage": coverage,
                        "contributions": contributions,
                    }
                )
            if not group_rows:
                continue
            raw = pd.Series(
                {item["row_index"]: item["raw_score"] for item in group_rows},
                dtype=float,
            )
            normalized = _zscore(raw)
            ranks = raw.rank(method="average", pct=True)
            for item in group_rows:
                row_index = item["row_index"]
                output_rows.append(
                    CompositeScoreRow(
                        symbol=str(group.at[row_index, "symbol"]),
                        trade_date=None if group_column is None else trade_date,
                        raw_score=item["raw_score"],
                        normalized_score=_finite(normalized.at[row_index]),
                        rank=_finite(ranks.at[row_index]),
                        coverage_ratio=item["coverage"],
                        contributions=item["contributions"],
                    )
                )
        return CompositeEvaluationResult(
            rows=output_rows,
            eligible_symbols=len(output_rows),
            filtered_symbols=original_count - len(output_rows),
        )


class CompositeFactorService:
    def __init__(
        self,
        repository: FactorRepository,
        *,
        engine: CompositeDslEngine | None = None,
    ) -> None:
        self.repository = repository
        self.engine = engine or CompositeDslEngine()

    def validate(self, request: CompositeValidateRequest) -> CompositeValidationResponse:
        return self.engine.validation_response(request)

    async def create(
        self, *, user_id: str, request: CompositeCreateRequest
    ) -> CompositeFactorResource:
        normalized, dependencies, checksum = self._resolve(
            request.market, request.definition
        )
        now = datetime.now(timezone.utc)
        resource = CompositeFactorResource(
            composite_id=uuid4().hex,
            user_id=user_id,
            version=1,
            status=CompositeStatus.DRAFT,
            name=request.name,
            description=request.description,
            market=request.market,
            definition=normalized,
            dependencies=dependencies,
            definition_checksum=checksum,
            created_at=now,
            updated_at=now,
        )
        try:
            return await self.repository.create_composite(resource)
        except FactorCompositeConflict as exc:
            raise CompositeStateConflict(str(exc)) from exc

    async def update(
        self,
        *,
        user_id: str,
        composite_id: str,
        request: CompositeUpdateRequest,
    ) -> CompositeFactorResource:
        latest = await self.repository.get_latest_composite(
            composite_id, user_id=user_id
        )
        if latest is None:
            raise CompositeNotFound("composite factor was not found")
        normalized, dependencies, checksum = self._resolve(
            request.market, request.definition
        )
        now = datetime.now(timezone.utc)
        if latest.status == CompositeStatus.DRAFT:
            replacement = latest.model_copy(
                update={
                    "name": request.name,
                    "description": request.description,
                    "market": request.market,
                    "definition": normalized,
                    "dependencies": dependencies,
                    "definition_checksum": checksum,
                    "updated_at": now,
                }
            )
            updated = await self.repository.replace_composite_draft(
                replacement,
                expected_definition_checksum=latest.definition_checksum,
            )
            if updated is None:
                raise CompositeStateConflict("composite draft changed concurrently")
            return updated

        next_draft = CompositeFactorResource(
            composite_id=composite_id,
            user_id=user_id,
            version=latest.version + 1,
            status=CompositeStatus.DRAFT,
            name=request.name,
            description=request.description,
            market=request.market,
            definition=normalized,
            dependencies=dependencies,
            definition_checksum=checksum,
            created_at=now,
            updated_at=now,
        )
        try:
            return await self.repository.create_composite(next_draft)
        except FactorCompositeConflict as exc:
            raise CompositeStateConflict(str(exc)) from exc

    async def publish(
        self, *, user_id: str, composite_id: str
    ) -> CompositeFactorResource:
        latest = await self.repository.get_latest_composite(
            composite_id, user_id=user_id
        )
        if latest is None:
            raise CompositeNotFound("composite factor was not found")
        if latest.status != CompositeStatus.DRAFT:
            raise CompositeStateConflict("composite has no draft version to publish")
        published = await self.repository.publish_composite(
            composite_id=composite_id,
            user_id=user_id,
            version=latest.version,
            definition_checksum=latest.definition_checksum,
            published_at=datetime.now(timezone.utc),
        )
        if published is None:
            raise CompositeStateConflict("composite draft changed concurrently")
        return published

    def _resolve(
        self, market: Market, definition: CompositeDefinition
    ) -> tuple[CompositeDefinition, tuple[CompositeDependencyVersion, ...], str]:
        return self.engine.resolve(market, definition)


def _definition_checksum(
    market: Market,
    definition: CompositeDefinition,
    dependencies: tuple[CompositeDependencyVersion, ...],
) -> str:
    payload = {
        "market": market.value,
        "definition": definition.model_dump(mode="json"),
        "dependencies": [item.model_dump(mode="json") for item in dependencies],
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _apply_filters(
    frame: pd.DataFrame,
    definition: CompositeDefinition,
    factor_ids: tuple[str, ...],
) -> pd.DataFrame:
    filters = definition.filters
    mask = pd.Series(True, index=frame.index)
    if filters.minimum_factor_coverage > 0:
        weight_by_factor = {
            term.factor.factor_id: abs(term.weight) for term in definition.terms
        }
        coverage = sum(
            frame[factor_id].notna().astype(float) * weight_by_factor[factor_id]
            for factor_id in factor_ids
        )
        mask &= coverage >= filters.minimum_factor_coverage
    if (
        filters.minimum_market_cap_log is not None
        or filters.maximum_market_cap_log is not None
    ):
        _require_columns(frame, {"market_cap_log"})
        cap = pd.to_numeric(frame["market_cap_log"], errors="coerce").replace(
            [np.inf, -np.inf], np.nan
        )
        mask &= cap.notna()
        if filters.minimum_market_cap_log is not None:
            mask &= cap >= filters.minimum_market_cap_log
        if filters.maximum_market_cap_log is not None:
            mask &= cap <= filters.maximum_market_cap_log
    if filters.include_industries or filters.exclude_industries:
        _require_columns(frame, {"industry"})
        industries = frame["industry"].astype("string")
        if filters.include_industries:
            mask &= industries.isin(filters.include_industries)
        if filters.exclude_industries:
            mask &= ~industries.isin(filters.exclude_industries)
    if filters.minimum_listing_days is not None:
        _require_columns(frame, {"listing_days"})
        listing_days = pd.to_numeric(
            frame["listing_days"], errors="coerce"
        ).replace([np.inf, -np.inf], np.nan)
        mask &= listing_days >= filters.minimum_listing_days
    for enabled, column in (
        (filters.exclude_st, "is_st"),
        (filters.exclude_delisting, "is_delisting"),
        (filters.exclude_suspended, "is_suspended"),
    ):
        if enabled:
            _require_columns(frame, {column})
            invalid = frame[column].dropna().map(
                lambda value: not isinstance(value, (bool, np.bool_))
            )
            if invalid.any():
                raise CompositeDslError(
                    f"status filter column {column} must contain booleans",
                    code="COMPOSITE_FILTER_TYPE_INVALID",
                )
            mask &= ~frame[column].fillna(False).astype(bool)
    return frame.loc[mask].copy()


def _transform(series: pd.Series, term: CompositeFactorTerm) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").astype(float)
    kind = term.transform.kind
    if kind == CompositeTransformKind.IDENTITY:
        return values
    if kind == CompositeTransformKind.NEGATE:
        return -values
    if kind == CompositeTransformKind.LOG1P_ABS:
        return np.sign(values) * np.log1p(values.abs())
    if kind == CompositeTransformKind.WINSORIZE_MAD:
        median = values.median()
        mad = (values - median).abs().median()
        if not math.isfinite(mad) or mad == 0:
            return values
        distance = float(term.transform.mad_scale) * 1.4826 * mad
        return values.clip(lower=median - distance, upper=median + distance)
    if kind == CompositeTransformKind.WINSORIZE_QUANTILE:
        lower = values.quantile(float(term.transform.lower_quantile))
        upper = values.quantile(float(term.transform.upper_quantile))
        return values.clip(lower=lower, upper=upper)
    if kind == CompositeTransformKind.ZSCORE:
        return _zscore(values)
    if kind == CompositeTransformKind.ROBUST_ZSCORE:
        median = values.median()
        mad = (values - median).abs().median()
        if not math.isfinite(mad) or mad == 0:
            return pd.Series(np.nan, index=values.index, dtype=float)
        return (values - median) / (1.4826 * mad)
    if kind == CompositeTransformKind.PERCENTILE_RANK:
        return values.rank(method="average", pct=True)
    raise CompositeDslError(f"unsupported transform: {kind}")


def _neutralize(
    values: pd.Series,
    frame: pd.DataFrame,
    method: CompositeNeutralizeKind,
) -> pd.Series:
    if method == CompositeNeutralizeKind.NONE:
        return values
    if method in {
        CompositeNeutralizeKind.INDUSTRY,
        CompositeNeutralizeKind.INDUSTRY_AND_MARKET_CAP,
    }:
        _require_columns(frame, {"industry"})
        values = values - values.groupby(frame["industry"], dropna=False).transform(
            "mean"
        )
    if method in {
        CompositeNeutralizeKind.MARKET_CAP,
        CompositeNeutralizeKind.INDUSTRY_AND_MARKET_CAP,
    }:
        _require_columns(frame, {"market_cap_log"})
        control = pd.to_numeric(
            frame["market_cap_log"], errors="coerce"
        ).replace([np.inf, -np.inf], np.nan)
        if method == CompositeNeutralizeKind.INDUSTRY_AND_MARKET_CAP:
            control = control - control.groupby(
                frame["industry"], dropna=False
            ).transform("mean")
        values = _linear_residual(values, control)
    return values


def _linear_residual(values: pd.Series, control: pd.Series) -> pd.Series:
    result = pd.Series(np.nan, index=values.index, dtype=float)
    valid = values.notna() & control.notna()
    if valid.sum() < 2 or control.loc[valid].nunique() < 2:
        return result
    x = np.column_stack(
        [np.ones(int(valid.sum()), dtype=float), control.loc[valid].to_numpy(float)]
    )
    y = values.loc[valid].to_numpy(float)
    coefficients, _, _, _ = np.linalg.lstsq(x, y, rcond=None)
    result.loc[valid] = y - x @ coefficients
    return result


def _combine(
    values: dict[str, float | None], definition: CompositeDefinition
) -> tuple[float, float, dict[str, float]] | None:
    terms = {term.factor.factor_id: term for term in definition.terms}
    valid_ids = [factor_id for factor_id, value in values.items() if value is not None]
    coverage = math.fsum(abs(terms[factor_id].weight) for factor_id in valid_ids)
    if definition.missing == CompositeMissingKind.DROP_SYMBOL and len(valid_ids) != len(terms):
        return None
    if definition.missing == CompositeMissingKind.RENORMALIZE_WEIGHTS:
        if coverage + 1e-12 < CompositeDslEngine.MINIMUM_REMAINING_WEIGHT:
            return None
        active_ids = valid_ids
    else:
        active_ids = list(terms)
    if not active_ids:
        return None

    active_values = {
        factor_id: 0.0 if values[factor_id] is None else float(values[factor_id])
        for factor_id in active_ids
    }
    if definition.arithmetic == CompositeArithmeticKind.WEIGHTED_SUM:
        denominator = (
            coverage
            if definition.missing == CompositeMissingKind.RENORMALIZE_WEIGHTS
            else 1.0
        )
        contributions = {
            factor_id: terms[factor_id].weight / denominator * active_values[factor_id]
            for factor_id in active_ids
        }
        raw = math.fsum(contributions.values())
    elif definition.arithmetic == CompositeArithmeticKind.MEAN:
        contributions = {
            factor_id: active_values[factor_id] / len(active_ids)
            for factor_id in active_ids
        }
        raw = math.fsum(contributions.values())
    else:
        raw = _signed_geometric_mean(tuple(active_values.values()))
        if raw is None:
            return None
        contributions = {
            factor_id: raw / len(active_ids) for factor_id in active_ids
        }
    if not math.isfinite(raw) or any(
        not math.isfinite(value) for value in contributions.values()
    ):
        return None
    complete_contributions = {
        factor_id: contributions.get(factor_id, 0.0) for factor_id in terms
    }
    return raw, min(max(coverage, 0.0), 1.0), complete_contributions


def _signed_geometric_mean(values: tuple[float, ...]) -> float | None:
    if not values:
        return None
    if any(value == 0 for value in values):
        return 0.0
    signs = {1 if value > 0 else -1 for value in values}
    if len(signs) != 1:
        return None
    magnitude = math.exp(math.fsum(math.log(abs(value)) for value in values) / len(values))
    return magnitude if 1 in signs else -magnitude


def _zscore(values: pd.Series) -> pd.Series:
    mean = values.mean()
    std = values.std(ddof=0)
    if not math.isfinite(std) or std == 0:
        return pd.Series(np.nan, index=values.index, dtype=float)
    return (values - mean) / std


def _require_columns(frame: pd.DataFrame, columns: set[str]) -> None:
    missing = sorted(columns - set(frame.columns))
    if missing:
        raise CompositeDslError(
            f"composite operation requires columns: {missing}",
            code="COMPOSITE_CONTROL_COLUMNS_MISSING",
        )


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None
