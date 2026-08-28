"""Point-in-time implementations of the 51 V1 fundamental factors."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from app.models.factor import FactorCategory
from app.models.market_data import PointInTimeFact
from app.services.factors.calculators.common import (
    INSUFFICIENT_HISTORY,
    INVALID_DOMAIN,
    MISSING_INPUT,
    NON_FINITE_OUTPUT,
)
from app.services.factors.point_in_time import (
    FinancialEvidence,
    PointInTimeSnapshot,
    ResolvedFinancialReport,
    resolve_point_in_time,
)
from app.services.factors.registry import global_factor_registry


NON_POSITIVE_DENOMINATOR = "non_positive_denominator"
ZERO_DENOMINATOR = "zero_denominator"


class FundamentalFactorOutput(dict[str, float]):
    """Scalar factor values plus deterministic quality and evidence metadata."""

    def __init__(self, snapshot: PointInTimeSnapshot):
        super().__init__()
        self.snapshot = snapshot
        self.quality_reasons: dict[str, str | None] = {}
        self.provenance: dict[str, dict[str, Any]] = {}
        self.evidence: dict[str, tuple[FinancialEvidence, ...]] = {}

    def add(
        self,
        factor_id: str,
        value: float | None,
        *,
        reason: str | None = None,
        evidence: Iterable[FinancialEvidence] = (),
        provenance: Mapping[str, Any] | None = None,
    ) -> None:
        numeric = _number(value)
        if numeric is None:
            self[factor_id] = np.nan
            self.quality_reasons[factor_id] = reason or MISSING_INPUT
        else:
            self[factor_id] = numeric
            self.quality_reasons[factor_id] = None
        self.evidence[factor_id] = _merge_evidence(tuple(evidence))
        self.provenance[factor_id] = {
            "as_of": self.snapshot.as_of.isoformat(),
            "report_period": self.snapshot.current_period,
            **dict(provenance or {}),
        }


def calculate_fundamental_factors(
    data: (
        PointInTimeSnapshot
        | Iterable[PointInTimeFact | Mapping[str, Any]]
        | pd.DataFrame
        | Mapping[str, Any]
    ),
    *,
    as_of: datetime | None = None,
    market: str | None = None,
    symbol: str | None = None,
    market_values: Mapping[str, Any] | None = None,
    flow_basis: str = "quarterly",
) -> FundamentalFactorOutput:
    """Calculate exactly the registered V1 valuation/quality/growth factors."""
    snapshot = _coerce_snapshot(
        data, as_of=as_of, market=market, symbol=symbol, flow_basis=flow_basis
    )
    values = dict(snapshot.values)
    values.update(dict(market_values or {}))
    output = FundamentalFactorOutput(snapshot)
    _add_valuation(output, values, snapshot)
    _add_quality(output, values, snapshot)
    _add_growth(output, values, snapshot)

    expected = {
        definition.factor_id
        for category in (
            FactorCategory.VALUATION,
            FactorCategory.QUALITY,
            FactorCategory.GROWTH,
        )
        for definition in global_factor_registry.get_by_category(category)
    }
    if set(output) != expected:
        raise AssertionError("fundamental calculator output does not match V1 registry")
    return output


def _add_valuation(
    output: FundamentalFactorOutput,
    values: Mapping[str, Any],
    snapshot: PointInTimeSnapshot,
) -> None:
    ratio_inputs = {
        "pe_ttm": ("market_cap", "net_profit_ttm"),
        "pb_mrq": ("market_cap", "equity_mrq"),
        "ps_ttm": ("market_cap", "revenue_ttm"),
        "pcf_ttm": ("market_cap", "operating_cashflow_ttm"),
    }
    calculated: dict[str, float | None] = {}
    for factor_id, (numerator, denominator) in ratio_inputs.items():
        direct = _number(values.get(factor_id))
        if direct is not None:
            value = direct if direct > 0 else None
            reason = None if value is not None else NON_POSITIVE_DENOMINATOR
            evidence = _evidence(snapshot, factor_id)
            formula = f"published {factor_id}"
        else:
            value, reason = _positive_denominator_ratio(
                values.get(numerator), values.get(denominator)
            )
            evidence = _field_evidence(snapshot, numerator, denominator)
            formula = f"{numerator} / {denominator}"
        calculated[factor_id] = value
        output.add(
            factor_id, value, reason=reason, evidence=evidence,
            provenance={"formula": formula, "denominator_rule": "strictly_positive"},
        )

    for factor_id, source in (
        ("earnings_yield", "pe_ttm"),
        ("book_to_price", "pb_mrq"),
        ("sales_to_price", "ps_ttm"),
        ("cashflow_to_price", "pcf_ttm"),
    ):
        value, reason = _positive_denominator_ratio(1.0, calculated[source])
        output.add(
            factor_id, value, reason=reason, evidence=output.evidence[source],
            provenance={"formula": f"1 / {source}", "unit": "decimal"},
        )

    value, reason = _positive_denominator_ratio(
        values.get("cash_dividend_ttm"), values.get("market_cap")
    )
    output.add(
        "dividend_yield_ttm", value, reason=reason,
        evidence=_field_evidence(snapshot, "cash_dividend_ttm", "market_cap"),
        provenance={
            "formula": "cash_dividend_ttm / market_cap", "unit": "decimal",
            "denominator_rule": "strictly_positive",
        },
    )

    for factor_id, denominator in (
        ("ev_to_ebitda", "ebitda_ttm"),
        ("ev_to_ebit", "ebit_ttm"),
        ("ev_to_sales", "revenue_ttm"),
    ):
        value, reason = _positive_denominator_ratio(
            values.get("enterprise_value"), values.get(denominator)
        )
        output.add(
            factor_id, value, reason=reason,
            evidence=_field_evidence(snapshot, "enterprise_value", denominator),
            provenance={
                "formula": f"enterprise_value / {denominator}",
                "denominator_rule": "strictly_positive",
            },
        )

    growth = _number(values.get("historical_growth"))
    growth_source = "historical_disclosed_growth"
    growth_evidence = _evidence(snapshot, "historical_growth")
    if growth is None and _number(values.get("consensus_growth")) is not None:
        source = values.get("consensus_growth_source")
        consensus_evidence = _evidence(snapshot, "consensus_growth")
        if not (isinstance(source, str) and source.strip()) and consensus_evidence:
            evidence_source = consensus_evidence[-1].source
            if evidence_source and evidence_source != "unknown":
                source = evidence_source
        if isinstance(source, str) and source.strip():
            growth = _number(values.get("consensus_growth"))
            growth_source = source.strip()
            growth_evidence = consensus_evidence
    pe = calculated["pe_ttm"]
    if pe is None or growth is None:
        peg, peg_reason = None, MISSING_INPUT
    elif growth <= 0:
        peg, peg_reason = None, NON_POSITIVE_DENOMINATOR
    else:
        peg, peg_reason = pe / (growth * 100.0), None
    output.add(
        "peg", peg, reason=peg_reason,
        evidence=_merge_evidence(output.evidence["pe_ttm"], growth_evidence),
        provenance={
            "formula": "pe_ttm / (growth_decimal * 100)",
            "growth_source": growth_source, "percentage_storage": "decimal",
        },
    )

    for factor_id, source in (
        ("market_cap_log", "market_cap"),
        ("free_float_cap_log", "free_float_market_cap"),
    ):
        raw = _number(values.get(source))
        if raw is None:
            value, reason = None, MISSING_INPUT
        elif raw <= 0:
            value, reason = None, INVALID_DOMAIN
        else:
            value, reason = float(np.log(raw)), None
        output.add(
            factor_id, value, reason=reason, evidence=_evidence(snapshot, source),
            provenance={"formula": f"ln({source})", "domain": "strictly_positive"},
        )


def _add_quality(
    output: FundamentalFactorOutput,
    values: Mapping[str, Any],
    snapshot: PointInTimeSnapshot,
) -> None:
    ratios = {
        "roe_ttm": ("net_profit_ttm", "average_equity"),
        "roa_ttm": ("net_profit_ttm", "average_assets"),
        "roic_ttm": ("nopat_ttm", "invested_capital"),
        "gross_margin_ttm": ("gross_profit_ttm", "revenue_ttm"),
        "operating_margin_ttm": ("operating_profit_ttm", "revenue_ttm"),
        "net_margin_ttm": ("net_profit_ttm", "revenue_ttm"),
        "fcf_margin_ttm": ("free_cashflow_ttm", "revenue_ttm"),
        "cfo_to_net_income": ("operating_cashflow_ttm", "net_profit_ttm"),
        "asset_turnover_ttm": ("revenue_ttm", "average_assets"),
        "inventory_turnover_ttm": ("cost_of_revenue_ttm", "average_inventory"),
        "receivable_turnover_ttm": ("revenue_ttm", "average_receivables"),
        "current_ratio": ("current_assets", "current_liabilities"),
        "quick_ratio": ("quick_assets", "current_liabilities"),
        "cash_ratio": ("cash", "current_liabilities"),
        "debt_to_assets": ("total_debt", "total_assets"),
        "debt_to_equity": ("total_debt", "total_equity"),
        "interest_coverage": ("ebit_ttm", "interest_expense_ttm"),
        "operating_cashflow_ratio": ("operating_cashflow_ttm", "current_liabilities"),
        "goodwill_to_assets": ("goodwill", "total_assets"),
    }
    for factor_id, (numerator, denominator) in ratios.items():
        direct = _number(values.get(factor_id))
        if direct is not None:
            value, reason = direct, None
            evidence = _evidence(snapshot, factor_id)
            formula = f"published {factor_id}"
        else:
            value, reason = _positive_denominator_ratio(
                values.get(numerator), values.get(denominator)
            )
            evidence = _field_evidence(snapshot, numerator, denominator)
            formula = f"{numerator} / {denominator}"
        output.add(
            factor_id, value, reason=reason, evidence=evidence,
            provenance={
                "formula": formula, "denominator_rule": "strictly_positive",
                "unit": "decimal" if factor_id.endswith(("margin_ttm", "to_assets")) else "ratio",
            },
        )

    numerator = _number(values.get("net_profit_ttm"))
    cashflow = _number(values.get("operating_cashflow_ttm"))
    denominator = _number(values.get("average_assets"))
    if numerator is None or cashflow is None or denominator is None:
        accruals, reason = None, MISSING_INPUT
    elif denominator <= 0:
        accruals, reason = None, NON_POSITIVE_DENOMINATOR
    else:
        accruals, reason = (numerator - cashflow) / denominator, None
    output.add(
        "accruals_ratio", accruals, reason=reason,
        evidence=_field_evidence(
            snapshot, "net_profit_ttm", "operating_cashflow_ttm", "average_assets"
        ),
        provenance={
            "formula": "(net_profit_ttm-operating_cashflow_ttm)/average_assets",
            "unit": "decimal", "denominator_rule": "strictly_positive",
        },
    )


def _add_growth(
    output: FundamentalFactorOutput,
    values: Mapping[str, Any],
    snapshot: PointInTimeSnapshot,
) -> None:
    reports = snapshot.reports
    for factor_id, field_name in (
        ("revenue_yoy", "revenue"),
        ("net_profit_yoy", "net_profit"),
        ("eps_yoy", "eps"),
        ("cfo_yoy", "operating_cashflow"),
    ):
        value, reason, evidence = _latest_yoy(reports, field_name)
        output.add(
            factor_id, value, reason=reason, evidence=evidence,
            provenance={
                "formula": f"({field_name}_t-{field_name}_t-4)/abs({field_name}_t-4)",
                "lag_quarters": 4, "unit": "decimal",
            },
        )

    for factor_id, field_name in (
        ("revenue_cagr_3y", "revenue"),
        ("net_profit_cagr_3y", "net_profit"),
        ("eps_cagr_3y", "eps"),
    ):
        value, reason, evidence = _cagr(reports, field_name, years=3)
        output.add(
            factor_id, value, reason=reason, evidence=evidence,
            provenance={
                "formula": f"({field_name}_t/{field_name}_t-12)^(1/3)-1",
                "years": 3, "endpoint_rule": "both_strictly_positive", "unit": "decimal",
            },
        )

    for factor_id, field_name in (
        ("roe_change_yoy", "roe"),
        ("gross_margin_change_yoy", "gross_margin"),
    ):
        value, reason, evidence = _latest_difference(reports, field_name, lag=4)
        output.add(
            factor_id, value, reason=reason, evidence=evidence,
            provenance={
                "formula": f"{field_name}_t - {field_name}_t-4",
                "lag_quarters": 4, "unit": "decimal_point_change",
            },
        )

    for factor_id, field_name in (
        ("revenue_stability_8q", "revenue"),
        ("profit_stability_8q", "net_profit"),
    ):
        growth, evidence = _last_yoy_values(reports, field_name, count=8)
        value = None if growth is None else -float(np.std(growth, ddof=0))
        output.add(
            factor_id, value,
            reason=None if value is not None else INSUFFICIENT_HISTORY,
            evidence=evidence,
            provenance={
                "formula": f"-std(last_8_quarterly_{field_name}_yoy, ddof=0)",
                "window_quarters": 8, "unit": "decimal",
            },
        )

    for factor_id, field_name in (
        ("positive_profit_quarters_8q", "net_profit"),
        ("positive_cfo_quarters_8q", "operating_cashflow"),
    ):
        samples, evidence = _last_values(reports, field_name, count=8)
        value = None if samples is None else float(np.mean(np.asarray(samples) > 0))
        output.add(
            factor_id, value,
            reason=None if value is not None else INSUFFICIENT_HISTORY,
            evidence=evidence,
            provenance={
                "formula": f"count({field_name}>0,last_8_quarters)/8",
                "window_quarters": 8, "unit": "decimal",
            },
        )

    for factor_id, field_name in (
        ("consecutive_revenue_growth_q", "revenue"),
        ("consecutive_profit_growth_q", "net_profit"),
    ):
        value, reason, evidence = _consecutive_positive_yoy(reports, field_name, limit=8)
        output.add(
            factor_id, value, reason=reason, evidence=evidence,
            provenance={
                "formula": f"trailing_count({field_name}_yoy>0)",
                "maximum_quarters": 8,
            },
        )

    roe = output.get("roe_ttm")
    retention = _number(values.get("retention_ratio"))
    if roe is None or not np.isfinite(roe) or retention is None:
        sustainable, reason = None, MISSING_INPUT
    else:
        sustainable, reason = float(roe) * retention, None
    output.add(
        "sustainable_growth_rate", sustainable, reason=reason,
        evidence=_merge_evidence(output.evidence["roe_ttm"], _evidence(snapshot, "retention_ratio")),
        provenance={
            "formula": "roe_ttm * retention_ratio", "unit": "decimal",
            "percentage_storage": "decimal",
        },
    )


def _coerce_snapshot(
    data: Any,
    *,
    as_of: datetime | None,
    market: str | None,
    symbol: str | None,
    flow_basis: str,
) -> PointInTimeSnapshot:
    if isinstance(data, PointInTimeSnapshot):
        return data
    if isinstance(data, Mapping) and "publish_at" not in data:
        if as_of is None:
            raise ValueError("as_of is required for direct fundamental values")
        timestamp = as_of
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        values = {
            name: value for name, value in data.items()
            if name not in {"market", "symbol", "report_period"}
        }
        return PointInTimeSnapshot(
            as_of=timestamp,
            market=str(data.get("market", market or "")),
            symbol=str(data.get("symbol", symbol or "")),
            current_period=(
                None if data.get("report_period") is None else str(data["report_period"])
            ),
            values=values,
            evidence={},
            reports=(),
            flow_basis=flow_basis,
        )
    if as_of is None:
        raise ValueError("as_of is required when calculating from financial facts")
    return resolve_point_in_time(
        data, as_of=as_of, market=market, symbol=symbol, flow_basis=flow_basis
    )


def _positive_denominator_ratio(
    numerator: Any, denominator: Any
) -> tuple[float | None, str | None]:
    top, bottom = _number(numerator), _number(denominator)
    if top is None or bottom is None:
        return None, MISSING_INPUT
    if bottom <= 0:
        return None, NON_POSITIVE_DENOMINATOR
    result = top / bottom
    return (result, None) if np.isfinite(result) else (None, NON_FINITE_OUTPUT)


def _latest_yoy(
    reports: tuple[ResolvedFinancialReport, ...], field_name: str
) -> tuple[float | None, str | None, tuple[FinancialEvidence, ...]]:
    if not reports:
        return None, INSUFFICIENT_HISTORY, ()
    current = reports[-1]
    previous = _report_at(reports, current.period_ordinal - 4)
    if previous is None:
        return None, INSUFFICIENT_HISTORY, ()
    current_value = _number(current.values.get(field_name))
    previous_value = _number(previous.values.get(field_name))
    evidence = _report_evidence(current, previous, field_name=field_name)
    if current_value is None or previous_value is None:
        return None, MISSING_INPUT, evidence
    if previous_value == 0:
        return None, ZERO_DENOMINATOR, evidence
    return (current_value - previous_value) / abs(previous_value), None, evidence


def _latest_difference(
    reports: tuple[ResolvedFinancialReport, ...], field_name: str, *, lag: int
) -> tuple[float | None, str | None, tuple[FinancialEvidence, ...]]:
    if not reports:
        return None, INSUFFICIENT_HISTORY, ()
    current = reports[-1]
    previous = _report_at(reports, current.period_ordinal - lag)
    if previous is None:
        return None, INSUFFICIENT_HISTORY, ()
    current_value = _number(current.values.get(field_name))
    previous_value = _number(previous.values.get(field_name))
    evidence = _report_evidence(current, previous, field_name=field_name)
    if current_value is None or previous_value is None:
        return None, MISSING_INPUT, evidence
    return current_value - previous_value, None, evidence


def _cagr(
    reports: tuple[ResolvedFinancialReport, ...], field_name: str, *, years: int
) -> tuple[float | None, str | None, tuple[FinancialEvidence, ...]]:
    if not reports:
        return None, INSUFFICIENT_HISTORY, ()
    current = reports[-1]
    start = _report_at(reports, current.period_ordinal - years * 4)
    if start is None:
        return None, INSUFFICIENT_HISTORY, ()
    end_value, start_value = _number(current.values.get(field_name)), _number(start.values.get(field_name))
    evidence = _report_evidence(current, start, field_name=field_name)
    if end_value is None or start_value is None:
        return None, MISSING_INPUT, evidence
    if end_value <= 0 or start_value <= 0:
        return None, INVALID_DOMAIN, evidence
    return (end_value / start_value) ** (1.0 / years) - 1.0, None, evidence


def _last_values(
    reports: tuple[ResolvedFinancialReport, ...], field_name: str, *, count: int
) -> tuple[list[float] | None, tuple[FinancialEvidence, ...]]:
    if len(reports) < count:
        return None, ()
    selected = reports[-count:]
    if any(
        selected[index].period_ordinal + 1 != selected[index + 1].period_ordinal
        for index in range(count - 1)
    ):
        return None, ()
    values = [_number(report.values.get(field_name)) for report in selected]
    evidence = _merge_evidence(
        *(report.evidence.get(field_name, ()) for report in selected)
    )
    return (None, evidence) if any(value is None for value in values) else (values, evidence)


def _last_yoy_values(
    reports: tuple[ResolvedFinancialReport, ...], field_name: str, *, count: int
) -> tuple[list[float] | None, tuple[FinancialEvidence, ...]]:
    if not reports:
        return None, ()
    selected = reports[-count:]
    if len(selected) != count:
        return None, ()
    if any(
        selected[index].period_ordinal + 1 != selected[index + 1].period_ordinal
        for index in range(count - 1)
    ):
        return None, ()
    growth: list[float] = []
    evidence: list[FinancialEvidence] = []
    for current in selected:
        previous = _report_at(reports, current.period_ordinal - 4)
        if previous is None:
            return None, ()
        current_value = _number(current.values.get(field_name))
        previous_value = _number(previous.values.get(field_name))
        if current_value is None or previous_value is None or previous_value == 0:
            return None, ()
        growth.append((current_value - previous_value) / abs(previous_value))
        evidence.extend(_report_evidence(current, previous, field_name=field_name))
    return growth, _merge_evidence(tuple(evidence))


def _consecutive_positive_yoy(
    reports: tuple[ResolvedFinancialReport, ...], field_name: str, *, limit: int
) -> tuple[float | None, str | None, tuple[FinancialEvidence, ...]]:
    if not reports:
        return None, INSUFFICIENT_HISTORY, ()
    count = 0
    evidence: list[FinancialEvidence] = []
    evaluated = False
    latest_ordinal = reports[-1].period_ordinal
    for offset in range(limit):
        current = _report_at(reports, latest_ordinal - offset)
        if current is None:
            break
        previous = _report_at(reports, current.period_ordinal - 4)
        if previous is None:
            break
        current_value = _number(current.values.get(field_name))
        previous_value = _number(previous.values.get(field_name))
        if current_value is None or previous_value is None or previous_value == 0:
            if not evaluated:
                return None, MISSING_INPUT, ()
            break
        evaluated = True
        evidence.extend(_report_evidence(current, previous, field_name=field_name))
        growth = (current_value - previous_value) / abs(previous_value)
        if growth <= 0:
            break
        count += 1
    if not evaluated:
        return None, INSUFFICIENT_HISTORY, ()
    return float(min(count, limit)), None, _merge_evidence(tuple(evidence))


def _report_at(
    reports: tuple[ResolvedFinancialReport, ...], ordinal: int
) -> ResolvedFinancialReport | None:
    return next((report for report in reports if report.period_ordinal == ordinal), None)


def _report_evidence(
    *reports: ResolvedFinancialReport,
    field_name: str,
) -> tuple[FinancialEvidence, ...]:
    return _merge_evidence(*(report.evidence.get(field_name, ()) for report in reports))


def _field_evidence(
    snapshot: PointInTimeSnapshot, *field_names: str
) -> tuple[FinancialEvidence, ...]:
    return _merge_evidence(*(snapshot.evidence.get(name, ()) for name in field_names))


def _evidence(
    snapshot: PointInTimeSnapshot, field_name: str
) -> tuple[FinancialEvidence, ...]:
    return snapshot.evidence.get(field_name, ())


def _merge_evidence(
    *groups: tuple[FinancialEvidence, ...],
) -> tuple[FinancialEvidence, ...]:
    unique = {
        (item.fact_id, item.report_period, item.publish_at): item
        for group in groups for item in group
    }
    return tuple(sorted(unique.values(), key=lambda item: (item.publish_at, item.fact_id)))


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if np.isfinite(numeric) else None
