"""Deterministic point-in-time resolution for published financial facts."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from app.models.market_data import PointInTimeFact


DEFAULT_FLOW_FIELDS = (
    "revenue",
    "net_profit",
    "eps",
    "operating_cashflow",
    "gross_profit",
    "operating_profit",
    "free_cashflow",
    "nopat",
    "cost_of_revenue",
    "ebit",
    "ebitda",
    "interest_expense",
    "cash_dividend",
)


@dataclass(frozen=True)
class FinancialEvidence:
    fact_id: str
    report_period: str
    publish_at: datetime
    ingested_at: datetime | None
    source: str
    source_version: str


@dataclass(frozen=True)
class ResolvedFinancialReport:
    report_period: str
    period_ordinal: int
    publish_at: datetime
    values: Mapping[str, float]
    evidence: Mapping[str, tuple[FinancialEvidence, ...]]


@dataclass(frozen=True)
class PointInTimeSnapshot:
    as_of: datetime
    market: str
    symbol: str
    current_period: str | None
    values: Mapping[str, float]
    evidence: Mapping[str, tuple[FinancialEvidence, ...]]
    reports: tuple[ResolvedFinancialReport, ...] = field(default_factory=tuple)
    flow_basis: str = "quarterly"

    def value(self, field_name: str) -> float | None:
        value = self.values.get(field_name)
        return None if value is None or not np.isfinite(value) else float(value)


def resolve_point_in_time(
    facts: Iterable[PointInTimeFact | Mapping[str, Any]] | pd.DataFrame,
    *,
    as_of: datetime,
    market: str | None = None,
    symbol: str | None = None,
    flow_basis: str = "quarterly",
    flow_fields: Iterable[str] = DEFAULT_FLOW_FIELDS,
) -> PointInTimeSnapshot:
    """Resolve one symbol's facts exactly as they were visible at ``as_of``.

    Restatements update only their report period.  A late older report never
    replaces a newer report as the current period, but can update historical
    transformations after its publication.  ``flow_basis='ytd'`` converts
    cumulative year-to-date flows into standalone quarters before TTM sums.
    """
    as_of_utc = _aware_utc(as_of, "as_of")
    if flow_basis not in {"quarterly", "ytd"}:
        raise ValueError("flow_basis must be 'quarterly' or 'ytd'")
    rows = [_normalize_fact(item) for item in _iter_facts(facts)]
    normalized_market = str(getattr(market, "value", market or ""))
    if market is not None:
        rows = [row for row in rows if row["market"] == normalized_market]
    if symbol is not None:
        rows = [row for row in rows if row["symbol"] == symbol]
    rows = [row for row in rows if row["publish_at"] <= as_of_utc]

    identities = {(row["market"], row["symbol"]) for row in rows}
    if len(identities) > 1:
        raise ValueError("resolve_point_in_time requires exactly one market and symbol")
    resolved_market, resolved_symbol = next(
        iter(identities), (normalized_market, str(symbol or ""))
    )
    reports = _resolve_reports(rows, flow_basis, tuple(flow_fields))
    if not reports:
        return PointInTimeSnapshot(
            as_of=as_of_utc,
            market=resolved_market,
            symbol=resolved_symbol,
            current_period=None,
            values={},
            evidence={},
            reports=(),
            flow_basis=flow_basis,
        )

    current = reports[-1]
    values = dict(current.values)
    evidence = dict(current.evidence)
    _add_ttm_values(values, evidence, reports, tuple(flow_fields))
    return PointInTimeSnapshot(
        as_of=as_of_utc,
        market=resolved_market,
        symbol=resolved_symbol,
        current_period=current.report_period,
        values=values,
        evidence=evidence,
        reports=reports,
        flow_basis=flow_basis,
    )


def point_in_time_snapshots(
    facts: Iterable[PointInTimeFact | Mapping[str, Any]] | pd.DataFrame,
    evaluation_times: Iterable[datetime],
    **options: Any,
) -> tuple[PointInTimeSnapshot, ...]:
    """Build a causal timeline; values change only after a publication event."""
    materialized = list(_iter_facts(facts))
    return tuple(
        resolve_point_in_time(materialized, as_of=as_of, **options)
        for as_of in evaluation_times
    )


def _resolve_reports(
    rows: list[dict[str, Any]],
    flow_basis: str,
    flow_fields: tuple[str, ...],
) -> tuple[ResolvedFinancialReport, ...]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    labels: dict[int, str] = {}
    for row in rows:
        ordinal, label = _quarter(row["report_period"])
        grouped.setdefault(ordinal, []).append(row)
        labels[ordinal] = label

    reports: list[ResolvedFinancialReport] = []
    for ordinal in sorted(grouped):
        values: dict[str, float] = {}
        evidence: dict[str, tuple[FinancialEvidence, ...]] = {}
        ordered = sorted(
            grouped[ordinal], key=lambda row: (row["publish_at"], row["fact_id"])
        )
        for row in ordered:
            item_evidence = FinancialEvidence(
                fact_id=row["fact_id"],
                report_period=row["report_period"],
                publish_at=row["publish_at"],
                ingested_at=row["ingested_at"],
                source=row["source"],
                source_version=row["source_version"],
            )
            for name, raw_value in row["data"].items():
                value = _finite_number(raw_value)
                if value is None:
                    values.pop(name, None)
                    evidence.pop(name, None)
                else:
                    values[name] = value
                    evidence[name] = (item_evidence,)
        reports.append(
            ResolvedFinancialReport(
                report_period=labels[ordinal],
                period_ordinal=ordinal,
                publish_at=max(row["publish_at"] for row in ordered),
                values=values,
                evidence=evidence,
            )
        )

    if flow_basis == "ytd":
        reports = _convert_ytd_to_quarters(reports, flow_fields)
    return tuple(reports)


def _convert_ytd_to_quarters(
    reports: list[ResolvedFinancialReport],
    flow_fields: tuple[str, ...],
) -> list[ResolvedFinancialReport]:
    by_ordinal = {report.period_ordinal: report for report in reports}
    converted: list[ResolvedFinancialReport] = []
    for report in reports:
        quarter = report.period_ordinal % 4 + 1
        values = dict(report.values)
        evidence = dict(report.evidence)
        if quarter > 1:
            previous = by_ordinal.get(report.period_ordinal - 1)
            for name in flow_fields:
                if name not in values:
                    continue
                if previous is None or name not in previous.values:
                    values.pop(name, None)
                    evidence.pop(name, None)
                    continue
                values[name] = values[name] - previous.values[name]
                evidence[name] = _merge_evidence(
                    evidence.get(name, ()), previous.evidence.get(name, ())
                )
        converted.append(
            ResolvedFinancialReport(
                report_period=report.report_period,
                period_ordinal=report.period_ordinal,
                publish_at=report.publish_at,
                values=values,
                evidence=evidence,
            )
        )
    return converted


def _add_ttm_values(
    values: dict[str, float],
    evidence: dict[str, tuple[FinancialEvidence, ...]],
    reports: tuple[ResolvedFinancialReport, ...],
    flow_fields: tuple[str, ...],
) -> None:
    if len(reports) < 4:
        return
    latest = reports[-4:]
    if any(
        latest[index].period_ordinal + 1 != latest[index + 1].period_ordinal
        for index in range(3)
    ):
        return
    for field_name in flow_fields:
        target = f"{field_name}_ttm"
        if target in values or any(field_name not in report.values for report in latest):
            continue
        values[target] = float(sum(report.values[field_name] for report in latest))
        evidence[target] = _merge_evidence(
            *(report.evidence.get(field_name, ()) for report in latest)
        )


def _iter_facts(
    facts: Iterable[PointInTimeFact | Mapping[str, Any]] | pd.DataFrame,
) -> Iterable[PointInTimeFact | Mapping[str, Any]]:
    if isinstance(facts, pd.DataFrame):
        return facts.to_dict(orient="records")
    return facts


def _normalize_fact(item: PointInTimeFact | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(item, PointInTimeFact):
        raw = item.model_dump()
    elif isinstance(item, Mapping):
        raw = dict(item)
    else:
        raise TypeError("financial facts must be PointInTimeFact or mapping values")
    required = ("fact_id", "market", "symbol", "report_period", "publish_at")
    missing = [name for name in required if raw.get(name) is None]
    if missing:
        raise ValueError(f"financial fact missing fields: {missing}")
    metadata = {
        "fact_id", "market", "symbol", "report_period", "publish_at", "ingested_at",
        "fact_type", "source", "source_version", "data",
    }
    data = dict(raw.get("data") or {})
    data.update({name: value for name, value in raw.items() if name not in metadata})
    return {
        "fact_id": str(raw["fact_id"]),
        "market": str(getattr(raw["market"], "value", raw["market"])),
        "symbol": str(raw["symbol"]),
        "report_period": str(raw["report_period"]),
        "publish_at": _aware_utc(raw["publish_at"], "publish_at"),
        "ingested_at": (
            None if raw.get("ingested_at") is None
            else _aware_utc(raw["ingested_at"], "ingested_at")
        ),
        "source": str(raw.get("source") or "unknown"),
        "source_version": str(raw.get("source_version") or "unknown"),
        "data": data,
    }


def _quarter(value: str) -> tuple[int, str]:
    text = str(value).strip().upper()
    if re.fullmatch(r"\d{4}", text):
        raise ValueError(f"quarter is required in report_period: {value}")
    match = re.fullmatch(r"(\d{4})\s*[-/]?\s*Q([1-4])", text)
    if match:
        year, quarter = int(match.group(1)), int(match.group(2))
    else:
        try:
            period = pd.Period(pd.Timestamp(text), freq="Q")
        except (TypeError, ValueError) as exc:
            raise ValueError(f"unsupported quarterly report_period: {value}") from exc
        year, quarter = period.year, period.quarter
    return year * 4 + quarter - 1, f"{year}Q{quarter}"


def _aware_utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _finite_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if np.isfinite(numeric) else None


def _merge_evidence(
    *groups: tuple[FinancialEvidence, ...],
) -> tuple[FinancialEvidence, ...]:
    unique: dict[tuple[str, str, datetime], FinancialEvidence] = {}
    for group in groups:
        for item in group:
            unique[(item.fact_id, item.report_period, item.publish_at)] = item
    return tuple(sorted(unique.values(), key=lambda item: (item.publish_at, item.fact_id)))
