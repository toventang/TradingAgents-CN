"""Leakage-safe, deterministic factor research analytics.

Feature values are read exclusively from immutable snapshots.  Future labels
are built in a separate frame with an explicit negative shift and joined only
on ``(symbol, trade_date)``.  No label column is ever available to the feature
construction path.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Protocol
from uuid import uuid4
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from app.models.domain_task import DomainTaskType
from app.models.factor import (
    FactorAnalysisAccepted,
    FactorAnalysisQualitySummary,
    FactorAnalysisRequest,
    FactorAnalysisResult,
    FactorAnalysisTaskPayload,
    FactorCorrelationMetric,
    FactorCorrelationWarning,
    FactorDailyIC,
    FactorDecayMetric,
    FactorDistributionSummary,
    FactorExposureMetric,
    FactorICMetric,
    FactorQuantileMetric,
    FactorSnapshot,
    FactorSnapshotStatus,
    FactorTimePoint,
    FactorTurnoverMetric,
)
from app.models.market_data import DailyBar, DataQualityStatus
from app.models.symbol import Market
from app.repositories.domain_task_repository import DomainTaskRepository
from app.repositories.factor_repository import FactorRepository
from app.services.domain_tasks import CancellationChecker, ProgressCallback
from app.services.market_data.market_data_service import MarketDataReadService


class FactorAnalysisError(ValueError):
    code = "FACTOR_ANALYSIS_INVALID"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.details = details or {}


class FactorAnalysisNotFound(LookupError):
    pass


class FactorAnalysisInsufficientSamples(FactorAnalysisError):
    code = "FACTOR_ANALYSIS_INSUFFICIENT_SAMPLES"


class FactorAnalysisLabelLoader(Protocol):
    async def __call__(
        self,
        *,
        symbol: str,
        market: Market,
        start_date: date,
        end_date: date,
        as_of: datetime,
        source_version: str,
    ) -> tuple[tuple[DailyBar, ...], str]: ...


async def _default_label_loader(
    *,
    symbol: str,
    market: Market,
    start_date: date,
    end_date: date,
    as_of: datetime,
    source_version: str,
) -> tuple[tuple[DailyBar, ...], str]:
    batch = await MarketDataReadService().read_daily_bars(
        symbol,
        market,
        start_date=start_date,
        end_date=end_date,
        as_of=as_of,
        source_version=source_version,
    )
    if batch.quality.status in {
        DataQualityStatus.INVALID,
        DataQualityStatus.UNAVAILABLE,
    }:
        return (), batch.source_version
    return tuple(batch.items), batch.source_version


def build_forward_returns(
    prices: pd.DataFrame, horizons: tuple[int, ...]
) -> pd.DataFrame:
    """Create labels with an explicit forward shift per canonical symbol.

    ``close.shift(-h) / close - 1`` is the only label definition.  The final
    ``h`` observations per symbol therefore remain missing and cannot leak a
    current or backward return into the research sample.
    """

    required = {"symbol", "trade_date", "close"}
    if not required.issubset(prices.columns):
        raise FactorAnalysisError(
            "price labels require symbol, trade_date, and close columns"
        )
    frame = prices.loc[:, ["symbol", "trade_date", "close"]].copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.replace([np.inf, -np.inf], np.nan)
    frame = frame.sort_values(["symbol", "trade_date"], kind="mergesort")
    if frame.duplicated(["symbol", "trade_date"]).any():
        raise FactorAnalysisError("price labels contain duplicate symbol/date rows")
    grouped = frame.groupby("symbol", sort=False)["close"]
    for horizon in horizons:
        future_close = grouped.shift(-horizon)
        label = future_close.div(frame["close"]).sub(1.0)
        frame[f"forward_{horizon}d"] = label.where(frame["close"] > 0)
    return frame


@dataclass(frozen=True)
class AnalyticsOutput:
    distributions: list[FactorDistributionSummary]
    time_series: list[FactorTimePoint]
    ic: list[FactorICMetric]
    quantile_returns: list[FactorQuantileMetric]
    turnover: list[FactorTurnoverMetric]
    correlations: list[FactorCorrelationMetric]
    warnings: list[FactorCorrelationWarning]
    exposures: list[FactorExposureMetric]
    decay: list[FactorDecayMetric]
    missing_labels: dict[str, int]


class FactorAnalytics:
    """Pure analytics over separately prepared feature and label frames."""

    def compute(
        self,
        features: pd.DataFrame,
        prices: pd.DataFrame,
        request: FactorAnalysisRequest,
    ) -> AnalyticsOutput:
        required = {"symbol", "trade_date", *request.factor_ids}
        if not required.issubset(features.columns):
            missing = sorted(required - set(features.columns))
            raise FactorAnalysisError(
                "feature frame is missing requested columns",
                details={"missing": missing},
            )
        feature_frame = features.copy()
        feature_frame["trade_date"] = pd.to_datetime(
            feature_frame["trade_date"]
        ).dt.date
        if feature_frame.duplicated(["symbol", "trade_date"]).any():
            raise FactorAnalysisError("features contain duplicate symbol/date rows")
        for factor_id in request.factor_ids:
            feature_frame[factor_id] = pd.to_numeric(
                feature_frame[factor_id], errors="coerce"
            ).replace([np.inf, -np.inf], np.nan)

        labels = build_forward_returns(prices, tuple(request.horizons))
        merged = feature_frame.merge(
            labels,
            on=["symbol", "trade_date"],
            how="left",
            validate="one_to_one",
        )
        missing_labels = {
            str(horizon): int(merged[f"forward_{horizon}d"].isna().sum())
            for horizon in request.horizons
        }
        distributions, time_series = _distribution_metrics(
            feature_frame, request.factor_ids
        )
        turnover = _turnover_metrics(feature_frame, request)
        turnover_by_factor = {item.factor_id: item for item in turnover}
        ic: list[FactorICMetric] = []
        quantile_returns: list[FactorQuantileMetric] = []
        insufficient: list[dict[str, Any]] = []
        for factor_id in request.factor_ids:
            for horizon in request.horizons:
                label_column = f"forward_{horizon}d"
                metric = _ic_metric(
                    merged,
                    factor_id,
                    label_column,
                    horizon,
                    request.min_cross_section,
                )
                ic.append(metric)
                if metric.sample_count < request.min_samples or metric.period_count == 0:
                    insufficient.append(
                        {
                            "factor_id": factor_id,
                            "horizon": horizon,
                            "sample_count": metric.sample_count,
                            "period_count": metric.period_count,
                            "required": request.min_samples,
                        }
                    )
                    continue
                quantile_returns.append(
                    _quantile_metric(
                        merged,
                        factor_id,
                        label_column,
                        horizon,
                        request,
                        turnover_by_factor[factor_id],
                    )
                )
        if insufficient:
            raise FactorAnalysisInsufficientSamples(
                "one or more factor/horizon samples are insufficient",
                details={"insufficient": insufficient},
            )
        correlations, warnings = _correlation_metrics(feature_frame, request)
        exposures = _exposure_metrics(feature_frame, request)
        decay = _decay_metrics(ic, request.factor_ids)
        return AnalyticsOutput(
            distributions=distributions,
            time_series=time_series,
            ic=ic,
            quantile_returns=quantile_returns,
            turnover=turnover,
            correlations=correlations,
            warnings=warnings,
            exposures=exposures,
            decay=decay,
            missing_labels=missing_labels,
        )


class FactorAnalysisService:
    def __init__(
        self,
        repository: FactorRepository,
        *,
        label_loader: FactorAnalysisLabelLoader | None = None,
        analytics: FactorAnalytics | None = None,
    ) -> None:
        self.repository = repository
        self.label_loader = label_loader or _default_label_loader
        self.analytics = analytics or FactorAnalytics()

    async def analyze(
        self,
        *,
        user_id: str,
        task_id: str,
        analysis_id: str,
        request: FactorAnalysisRequest,
        report_progress: ProgressCallback,
        is_cancelled: CancellationChecker,
    ) -> FactorAnalysisResult:
        existing = await self.repository.get_analysis_result(
            analysis_id, user_id=user_id
        )
        if existing is not None:
            await report_progress(
                1.0,
                "factor_analysis_complete",
                "Immutable factor analysis result already published",
            )
            return existing
        await report_progress(0.02, "factor_analysis_load", "Loading immutable factor snapshots")
        snapshots, rows = await self.repository.load_analysis_inputs(
            snapshot_ids=request.snapshot_ids,
            user_id=user_id,
        )
        _validate_snapshot_boundaries(snapshots, request)
        market = snapshots[0].market
        feature_frame, excluded_quality, missing_values = _feature_frame(
            rows, request.factor_ids, request.industry_by_symbol
        )
        symbols = tuple(sorted(feature_frame["symbol"].unique()))
        feature_start = min(snapshot.trade_date for snapshot in snapshots)
        feature_end = max(snapshot.trade_date for snapshot in snapshots)
        label_end = request.label_as_of.astimezone(_market_zone(market)).date()
        price_records: list[dict[str, Any]] = []
        label_versions: set[str] = set()
        for index, symbol in enumerate(symbols, 1):
            if await is_cancelled():
                from app.services.domain_tasks import TaskCancellationRequested

                raise TaskCancellationRequested("factor analysis was cancelled")
            bars, version = await self.label_loader(
                symbol=symbol,
                market=market,
                start_date=feature_start,
                end_date=label_end,
                as_of=request.label_as_of,
                source_version=request.label_source_version,
            )
            label_versions.add(version)
            label_versions.update(bar.source_version for bar in bars)
            price_records.extend(
                {
                    "symbol": bar.symbol,
                    "trade_date": bar.trade_date,
                    "close": bar.close,
                }
                for bar in bars
                if bar.close is not None
            )
            await report_progress(
                0.05 + 0.55 * index / max(len(symbols), 1),
                "factor_analysis_labels",
                f"Loaded forward-label prices for {index}/{len(symbols)} symbols",
            )
        if not price_records:
            raise FactorAnalysisInsufficientSamples(
                "no versioned close data is available for future-return labels",
                details={"label_source_version": request.label_source_version},
            )
        await report_progress(0.65, "factor_analysis_compute", "Computing factor diagnostics")
        output = self.analytics.compute(
            feature_frame,
            pd.DataFrame.from_records(price_records),
            request,
        )
        source_versions: dict[str, tuple[str, ...]] = {}
        for snapshot in snapshots:
            for source, version in snapshot.source_versions.items():
                source_versions.setdefault(source, ())
                source_versions[source] = tuple(
                    sorted(set(source_versions[source]) | {version})
                )
        result = FactorAnalysisResult(
            analysis_id=analysis_id,
            user_id=user_id,
            task_id=task_id,
            request_checksum=request.request_checksum,
            request=request,
            market=market,
            universe_snapshot_id=snapshots[0].universe_snapshot_id,
            feature_start=feature_start,
            feature_end=feature_end,
            feature_as_of_start=min(item.as_of for item in snapshots),
            feature_as_of_end=max(item.as_of for item in snapshots),
            factor_set_checksums={
                item.snapshot_id: item.factor_set_checksum for item in snapshots
            },
            source_versions=source_versions,
            transaction_cost_included=request.transaction_cost_bps > 0,
            distributions=output.distributions,
            time_series=output.time_series,
            ic=output.ic,
            quantile_returns=output.quantile_returns,
            turnover=output.turnover,
            correlations=output.correlations,
            correlation_warnings=output.warnings,
            exposures=output.exposures,
            decay=output.decay,
            quality=FactorAnalysisQualitySummary(
                snapshot_count=len(snapshots),
                row_count=len(feature_frame),
                excluded_quality_values=excluded_quality,
                missing_factor_values=missing_values,
                missing_labels_by_horizon=output.missing_labels,
                label_source_versions=tuple(sorted(label_versions)),
            ),
            created_at=datetime.now(timezone.utc),
        )
        await report_progress(0.95, "factor_analysis_persist", "Persisting immutable analysis result")
        persisted = await self.repository.save_analysis_result(result)
        await report_progress(1.0, "factor_analysis_complete", "Factor analysis completed")
        return persisted


class FactorAnalysisApiService:
    """Owner-scoped durable task creation and immutable result retrieval."""

    def __init__(
        self,
        *,
        factor_repository: FactorRepository,
        task_repository: DomainTaskRepository,
    ) -> None:
        self.factor_repository = factor_repository
        self.task_repository = task_repository

    async def create(
        self, *, user_id: str, request: FactorAnalysisRequest
    ) -> FactorAnalysisAccepted:
        snapshots, _ = await self.factor_repository.load_analysis_inputs(
            snapshot_ids=request.snapshot_ids,
            user_id=user_id,
            include_values=False,
        )
        _validate_snapshot_boundaries(snapshots, request)
        analysis_id = hashlib.sha256(
            f"{user_id}:{request.request_checksum}".encode("utf-8")
        ).hexdigest()
        generated_task_id = str(uuid4())
        payload = FactorAnalysisTaskPayload(
            analysis_id=analysis_id,
            request=request,
        )
        task = await self.task_repository.create_task(
            user_id=user_id,
            task_type=DomainTaskType.FACTOR_ANALYSIS,
            payload=payload.model_dump(mode="json"),
            idempotency_key=f"factor-analysis:{request.request_checksum}",
            task_id=generated_task_id,
            stage="factor_analysis_queued",
            message="Factor analysis queued",
        )
        return FactorAnalysisAccepted(
            analysis_id=analysis_id,
            task_id=task.task_id,
            request_checksum=request.request_checksum,
            deduplicated=task.task_id != generated_task_id,
        )

    async def get_result(
        self, *, user_id: str, analysis_id: str
    ) -> FactorAnalysisResult:
        result = await self.factor_repository.get_analysis_result(
            analysis_id, user_id=user_id
        )
        if result is None:
            raise FactorAnalysisNotFound("factor analysis result was not found")
        return result


def _feature_frame(
    rows: list[dict[str, Any]],
    factor_ids: tuple[str, ...],
    industry_by_symbol: dict[str, str],
) -> tuple[pd.DataFrame, int, int]:
    records: list[dict[str, Any]] = []
    excluded_quality = 0
    missing_values = 0
    good_quality = {None, "", "ok", "OK", "valid", "VALID"}
    for row in rows:
        values = row.get("values") or {}
        quality = row.get("quality") or {}
        record: dict[str, Any] = {
            "symbol": str(row["symbol"]),
            "trade_date": row["trade_date"],
            "industry": industry_by_symbol.get(str(row["symbol"])),
        }
        for factor_id in factor_ids:
            value = values.get(factor_id)
            if factor_id not in values or value is None:
                missing_values += 1
                record[factor_id] = np.nan
            elif quality.get(factor_id) not in good_quality:
                excluded_quality += 1
                record[factor_id] = np.nan
            else:
                record[factor_id] = _finite(value)
        # Exposure controls are structured factor values, never labels.
        for control in ("market_cap_log", "beta_60"):
            record[control] = _finite(values.get(control))
        records.append(record)
    if not records:
        raise FactorAnalysisError("selected snapshots contain no factor value rows")
    return pd.DataFrame.from_records(records), excluded_quality, missing_values


def _validate_snapshot_boundaries(
    snapshots: tuple[FactorSnapshot, ...], request: FactorAnalysisRequest
) -> None:
    if len(snapshots) != len(request.snapshot_ids):
        raise FactorAnalysisError("one or more ready snapshots were not found")
    if any(item.status != FactorSnapshotStatus.READY for item in snapshots):
        raise FactorAnalysisError("analysis requires ready snapshots")
    if len({item.market for item in snapshots}) != 1:
        raise FactorAnalysisError("analysis snapshots must use one market")
    if len({item.universe_snapshot_id for item in snapshots}) != 1:
        raise FactorAnalysisError("analysis snapshots must use one fixed universe")
    if len({item.trade_date for item in snapshots}) != len(snapshots):
        raise FactorAnalysisError("analysis snapshots must have unique trade dates")
    market = snapshots[0].market
    for snapshot in snapshots:
        local_as_of_date = snapshot.as_of.astimezone(_market_zone(market)).date()
        if local_as_of_date != snapshot.trade_date:
            raise FactorAnalysisError(
                "feature snapshot as_of must be on its trade date",
                details={"snapshot_id": snapshot.snapshot_id},
            )
    feature_end = max(item.trade_date for item in snapshots)
    label_date = request.label_as_of.astimezone(_market_zone(market)).date()
    if label_date <= feature_end:
        raise FactorAnalysisError("label_as_of must be after the final feature date")


def _distribution_metrics(
    frame: pd.DataFrame, factor_ids: tuple[str, ...]
) -> tuple[list[FactorDistributionSummary], list[FactorTimePoint]]:
    distributions: list[FactorDistributionSummary] = []
    points: list[FactorTimePoint] = []
    total = len(frame)
    for factor_id in factor_ids:
        values = frame[factor_id].dropna().astype(float)
        quantiles = values.quantile([0.01, 0.25, 0.5, 0.75, 0.99]) if len(values) else None
        extreme_rate = 0.0
        if quantiles is not None and len(values):
            iqr = float(quantiles.loc[0.75] - quantiles.loc[0.25])
            if iqr > 0:
                lower = float(quantiles.loc[0.25] - 3.0 * iqr)
                upper = float(quantiles.loc[0.75] + 3.0 * iqr)
                extreme_rate = float(((values < lower) | (values > upper)).mean())
        distributions.append(
            FactorDistributionSummary(
                factor_id=factor_id,
                total_observations=total,
                valid_observations=len(values),
                missing_rate=(total - len(values)) / total if total else 1.0,
                extreme_rate=extreme_rate,
                coverage_symbols=int(frame.loc[frame[factor_id].notna(), "symbol"].nunique()),
                mean=_series_value(values, "mean"),
                std=_series_value(values, "std"),
                minimum=_series_value(values, "min"),
                p01=None if quantiles is None else _finite(quantiles.loc[0.01]),
                p25=None if quantiles is None else _finite(quantiles.loc[0.25]),
                median=None if quantiles is None else _finite(quantiles.loc[0.5]),
                p75=None if quantiles is None else _finite(quantiles.loc[0.75]),
                p99=None if quantiles is None else _finite(quantiles.loc[0.99]),
                maximum=_series_value(values, "max"),
            )
        )
        for trade_date, group in frame.groupby("trade_date", sort=True):
            daily = group[factor_id].dropna().astype(float)
            points.append(
                FactorTimePoint(
                    factor_id=factor_id,
                    trade_date=trade_date,
                    mean=_series_value(daily, "mean"),
                    median=_series_value(daily, "median"),
                    std=_series_value(daily, "std"),
                    valid_observations=len(daily),
                    missing_rate=(len(group) - len(daily)) / len(group),
                )
            )
    return distributions, points


def _ic_metric(
    frame: pd.DataFrame,
    factor_id: str,
    label_column: str,
    horizon: int,
    min_cross_section: int,
) -> FactorICMetric:
    daily: list[FactorDailyIC] = []
    sample_count = 0
    sample_dates: list[date] = []
    for trade_date, group in frame.groupby("trade_date", sort=True):
        valid = group[[factor_id, label_column]].dropna()
        sample_count += len(valid)
        if len(valid):
            sample_dates.append(trade_date)
        pearson = rank_ic = None
        if (
            len(valid) >= min_cross_section
            and valid[factor_id].nunique() > 1
            and valid[label_column].nunique() > 1
        ):
            pearson = _finite(valid[factor_id].corr(valid[label_column]))
            rank_ic = _finite(
                valid[factor_id].rank(method="average").corr(
                    valid[label_column].rank(method="average")
                )
            )
        if pearson is not None or rank_ic is not None:
            daily.append(
                FactorDailyIC(
                    trade_date=trade_date,
                    sample_count=len(valid),
                    pearson=pearson,
                    rank=rank_ic,
                )
            )
    pearsons = [item.pearson for item in daily if item.pearson is not None]
    ranks = [item.rank for item in daily if item.rank is not None]
    pearson_mean, pearson_std, pearson_icir, pearson_positive = _ic_summary(pearsons)
    rank_mean, rank_std, rank_icir, rank_positive = _ic_summary(ranks)
    return FactorICMetric(
        factor_id=factor_id,
        horizon=horizon,
        sample_count=sample_count,
        period_count=len(daily),
        sample_start=min(sample_dates) if sample_dates else None,
        sample_end=max(sample_dates) if sample_dates else None,
        pearson_mean=pearson_mean,
        pearson_std=pearson_std,
        pearson_icir=pearson_icir,
        pearson_positive_ratio=pearson_positive,
        rank_mean=rank_mean,
        rank_std=rank_std,
        rank_icir=rank_icir,
        rank_positive_ratio=rank_positive,
        daily=daily,
    )


def _ic_summary(
    values: list[float],
) -> tuple[float | None, float | None, float | None, float | None]:
    if not values:
        return None, None, None, None
    array = np.asarray(values, dtype=float)
    mean = _finite(array.mean())
    std = _finite(array.std(ddof=1)) if len(array) > 1 else 0.0
    icir = None if not std else _finite(mean / std if mean is not None else None)
    return mean, std, icir, float((array > 0).mean())


def _quantile_memberships(
    group: pd.DataFrame, factor_id: str, quantiles: int
) -> pd.DataFrame:
    valid = group.loc[group[factor_id].notna()].sort_values(
        [factor_id, "symbol"], kind="mergesort"
    ).copy()
    if len(valid) < quantiles:
        return valid.iloc[0:0].assign(quantile=pd.Series(dtype=int))
    valid["quantile"] = (
        np.floor(np.arange(len(valid)) * quantiles / len(valid)).astype(int) + 1
    )
    return valid


def _turnover_metrics(
    frame: pd.DataFrame, request: FactorAnalysisRequest
) -> list[FactorTurnoverMetric]:
    result: list[FactorTurnoverMetric] = []
    for factor_id in request.factor_ids:
        previous_top: set[str] | None = None
        previous_bottom: set[str] | None = None
        top_values: list[float] = []
        bottom_values: list[float] = []
        for _, group in frame.groupby("trade_date", sort=True):
            ranked = _quantile_memberships(group, factor_id, request.quantiles)
            if ranked.empty:
                continue
            bottom = set(ranked.loc[ranked["quantile"] == 1, "symbol"])
            top = set(ranked.loc[ranked["quantile"] == request.quantiles, "symbol"])
            if previous_top is not None and previous_bottom is not None:
                top_values.append(_set_turnover(previous_top, top))
                bottom_values.append(_set_turnover(previous_bottom, bottom))
            previous_top, previous_bottom = top, bottom
        top_mean = _finite(np.mean(top_values)) if top_values else None
        bottom_mean = _finite(np.mean(bottom_values)) if bottom_values else None
        result.append(
            FactorTurnoverMetric(
                factor_id=factor_id,
                quantiles=request.quantiles,
                period_count=len(top_values),
                top_turnover=top_mean,
                bottom_turnover=bottom_mean,
                long_short_turnover=(
                    None
                    if top_mean is None or bottom_mean is None
                    else top_mean + bottom_mean
                ),
            )
        )
    return result


def _quantile_metric(
    frame: pd.DataFrame,
    factor_id: str,
    label_column: str,
    horizon: int,
    request: FactorAnalysisRequest,
    turnover: FactorTurnoverMetric,
) -> FactorQuantileMetric:
    buckets: dict[int, list[float]] = {
        index: [] for index in range(1, request.quantiles + 1)
    }
    for _, group in frame.groupby("trade_date", sort=True):
        ranked = _quantile_memberships(group, factor_id, request.quantiles)
        ranked = ranked.loc[ranked[label_column].notna()]
        for quantile, values in ranked.groupby("quantile", sort=True):
            buckets[int(quantile)].extend(values[label_column].astype(float).tolist())
    returns = {
        f"Q{index}": _finite(np.mean(values)) if values else None
        for index, values in buckets.items()
    }
    complete = [(index, returns[f"Q{index}"]) for index in buckets]
    monotonicity = None
    if all(value is not None for _, value in complete):
        monotonicity = _finite(
            pd.Series([value for _, value in complete], dtype=float).corr(
                pd.Series([index for index, _ in complete], dtype=float)
            )
        )
    low = returns["Q1"]
    high = returns[f"Q{request.quantiles}"]
    gross = None if low is None or high is None else high - low
    cost = request.transaction_cost_bps / 10_000.0
    net = gross
    if gross is not None and turnover.long_short_turnover is not None:
        net = gross - cost * turnover.long_short_turnover
    return FactorQuantileMetric(
        factor_id=factor_id,
        horizon=horizon,
        quantiles=request.quantiles,
        sample_count=sum(len(values) for values in buckets.values()),
        returns=returns,
        monotonicity=monotonicity,
        gross_long_short_return=gross,
        net_long_short_return=net,
    )


def _correlation_metrics(
    frame: pd.DataFrame, request: FactorAnalysisRequest
) -> tuple[list[FactorCorrelationMetric], list[FactorCorrelationWarning]]:
    metrics: list[FactorCorrelationMetric] = []
    warnings: list[FactorCorrelationWarning] = []
    for index, factor_a in enumerate(request.factor_ids):
        for factor_b in request.factor_ids[index:]:
            daily_values: list[float] = []
            samples = 0
            for _, group in frame.groupby("trade_date", sort=True):
                if factor_a == factor_b:
                    valid_self = group[factor_a].dropna()
                    if len(valid_self) >= request.min_cross_section and valid_self.nunique() > 1:
                        daily_values.append(1.0)
                        samples += len(valid_self)
                    continue
                valid = group[[factor_a, factor_b]].dropna()
                if (
                    len(valid) >= request.min_cross_section
                    and valid[factor_a].nunique() > 1
                    and valid[factor_b].nunique() > 1
                ):
                    correlation = _finite(valid[factor_a].corr(valid[factor_b]))
                    if correlation is not None:
                        daily_values.append(correlation)
                        samples += len(valid)
            value = _finite(np.mean(daily_values)) if daily_values else None
            metric = FactorCorrelationMetric(
                factor_a=factor_a,
                factor_b=factor_b,
                correlation=value,
                sample_count=samples,
                period_count=len(daily_values),
            )
            metrics.append(metric)
            if factor_a != factor_b and value is not None and abs(value) > request.correlation_threshold:
                warnings.append(
                    FactorCorrelationWarning(
                        factor_a=factor_a,
                        factor_b=factor_b,
                        correlation=value,
                        threshold=request.correlation_threshold,
                    )
                )
    return metrics, warnings


def _exposure_metrics(
    frame: pd.DataFrame, request: FactorAnalysisRequest
) -> list[FactorExposureMetric]:
    result: list[FactorExposureMetric] = []
    for factor_id in request.factor_ids:
        industry_values: dict[str, list[float]] = {}
        for _, group in frame.groupby("trade_date", sort=True):
            valid = group.loc[group[factor_id].notna(), [factor_id, "industry"]].copy()
            if len(valid) < 2:
                continue
            std = valid[factor_id].std(ddof=1)
            if not math.isfinite(std) or std == 0:
                continue
            valid["exposure"] = (valid[factor_id] - valid[factor_id].mean()) / std
            for industry, values in valid.loc[valid["industry"].notna()].groupby("industry"):
                industry_values.setdefault(str(industry), []).extend(
                    values["exposure"].astype(float).tolist()
                )
        industry_exposure = {
            industry: _finite(np.mean(values)) for industry, values in sorted(industry_values.items())
        }
        cap_corr, cap_samples = _average_daily_correlation(
            frame, factor_id, "market_cap_log", request.min_cross_section
        )
        beta_corr, beta_samples = _average_daily_correlation(
            frame, factor_id, "beta_60", request.min_cross_section
        )
        result.append(
            FactorExposureMetric(
                factor_id=factor_id,
                industry_exposure=industry_exposure,
                industry_sample_counts={
                    industry: len(values) for industry, values in sorted(industry_values.items())
                },
                market_cap_correlation=cap_corr,
                market_cap_sample_count=cap_samples,
                beta_correlation=beta_corr,
                beta_sample_count=beta_samples,
            )
        )
    return result


def _average_daily_correlation(
    frame: pd.DataFrame, factor_id: str, control: str, minimum: int
) -> tuple[float | None, int]:
    correlations: list[float] = []
    samples = 0
    if control not in frame:
        return None, 0
    for _, group in frame.groupby("trade_date", sort=True):
        valid = group[[factor_id, control]].dropna()
        if len(valid) >= minimum and valid[factor_id].nunique() > 1 and valid[control].nunique() > 1:
            value = _finite(valid[factor_id].corr(valid[control]))
            if value is not None:
                correlations.append(value)
                samples += len(valid)
    return (_finite(np.mean(correlations)) if correlations else None), samples


def _decay_metrics(
    metrics: list[FactorICMetric], factor_ids: tuple[str, ...]
) -> list[FactorDecayMetric]:
    return [
        FactorDecayMetric(
            factor_id=factor_id,
            rank_ic_by_horizon={
                str(item.horizon): item.rank_mean
                for item in metrics
                if item.factor_id == factor_id
            },
            pearson_ic_by_horizon={
                str(item.horizon): item.pearson_mean
                for item in metrics
                if item.factor_id == factor_id
            },
        )
        for factor_id in factor_ids
    ]


def _set_turnover(previous: set[str], current: set[str]) -> float:
    denominator = max(len(previous), len(current))
    return 0.0 if denominator == 0 else 1.0 - len(previous & current) / denominator


def _series_value(series: pd.Series, method: str) -> float | None:
    if series.empty:
        return None
    return _finite(getattr(series, method)())


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _market_zone(market: Market) -> ZoneInfo:
    return ZoneInfo(
        {
            Market.CN: "Asia/Shanghai",
            Market.HK: "Asia/Hong_Kong",
            Market.US: "America/New_York",
        }[market]
    )
