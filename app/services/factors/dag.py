"""One-shot factor dependency and shared-intermediate planning."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from app.models.factor import FactorCategory, FactorComputeRequest, FactorDefinition
from app.services.factors.registry import FactorRegistry, global_factor_registry


@dataclass(frozen=True, slots=True)
class FactorExecutionGroup:
    category: FactorCategory
    factor_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FactorExecutionLayer:
    depth: int
    factor_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FactorPlan:
    requested_factor_ids: tuple[str, ...]
    execution_order: tuple[str, ...]
    definitions: tuple[FactorDefinition, ...]
    layers: tuple[FactorExecutionLayer, ...]
    groups: tuple[FactorExecutionGroup, ...]
    required_columns: tuple[str, ...]
    common_intermediates: tuple[str, ...]
    resolved_params: dict[str, dict[str, Any]]
    checksum: str


class FactorDAGPlanner:
    def __init__(self, registry: FactorRegistry | None = None):
        self.registry = registry or global_factor_registry

    def plan(self, request: FactorComputeRequest) -> FactorPlan:
        """Validate versions/params and plan the full DAG exactly once."""
        requested_ids = tuple(item.factor_id for item in request.factors)
        refs = {item.factor_id: item for item in request.factors}
        for ref in request.factors:
            definition = self.registry.require(ref.factor_id)
            if definition.version != ref.version:
                raise ValueError(
                    f"factor version unavailable: {ref.factor_id} v{ref.version}"
                )
        definitions = tuple(self.registry.dependency_order(requested_ids))
        execution_order = tuple(item.factor_id for item in definitions)
        layers = _execution_layers(definitions)
        resolved_params = {
            definition.factor_id: definition.resolve_params(
                refs[definition.factor_id].params
                if definition.factor_id in refs else None
            )
            for definition in definitions
        }

        grouped: dict[FactorCategory, list[str]] = {}
        for definition in definitions:
            grouped.setdefault(definition.category, []).append(definition.factor_id)
        groups = tuple(
            FactorExecutionGroup(category=category, factor_ids=tuple(factor_ids))
            for category, factor_ids in grouped.items()
        )
        required_columns = tuple(sorted({
            column for definition in definitions for column in definition.required_columns
        }))
        intermediates = _common_intermediates(definitions)
        payload = {
            "requested_factor_ids": requested_ids,
            "execution_order": execution_order,
            "layers": [layer.factor_ids for layer in layers],
            "groups": [
                {"category": group.category.value, "factor_ids": group.factor_ids}
                for group in groups
            ],
            "required_columns": required_columns,
            "common_intermediates": intermediates,
            "resolved_params": resolved_params,
        }
        checksum = hashlib.sha256(
            json.dumps(
                payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")
        ).hexdigest()
        return FactorPlan(
            requested_factor_ids=requested_ids,
            execution_order=execution_order,
            definitions=definitions,
            layers=layers,
            groups=groups,
            required_columns=required_columns,
            common_intermediates=intermediates,
            resolved_params=resolved_params,
            checksum=checksum,
        )


def _common_intermediates(
    definitions: tuple[FactorDefinition, ...]
) -> tuple[str, ...]:
    factor_ids = {item.factor_id for item in definitions}
    categories = {item.category for item in definitions}
    result: set[str] = set()
    if categories & {
        FactorCategory.PRICE,
        FactorCategory.MOMENTUM,
        FactorCategory.VOLATILITY,
        FactorCategory.LIQUIDITY,
        FactorCategory.EVENT,
    }:
        result.add("simple_returns")
    if any(item.startswith(("log_ret_", "hist_vol_", "linear_slope_")) for item in factor_ids):
        result.add("log_returns")
    if categories & {FactorCategory.TREND, FactorCategory.VOLATILITY}:
        result.add("true_range")
    if categories & {FactorCategory.LIQUIDITY, FactorCategory.MOMENTUM}:
        result.add("typical_price")
    rolling_windows = sorted(
        {
            int(match.group(1))
            for factor_id in factor_ids
            for match in re.finditer(r"(?:^|_)(\d+)(?:d)?(?:_|$)", factor_id)
        }
    )
    result.update(f"rolling_window_{window}" for window in rolling_windows)
    return tuple(sorted(result))


def _execution_layers(
    definitions: tuple[FactorDefinition, ...]
) -> tuple[FactorExecutionLayer, ...]:
    selected = {item.factor_id for item in definitions}
    depths: dict[str, int] = {}
    grouped: dict[int, list[str]] = {}
    for definition in definitions:
        dependencies = [
            depths[item]
            for item in definition.dependencies
            if item in selected
        ]
        depth = max(dependencies, default=-1) + 1
        depths[definition.factor_id] = depth
        grouped.setdefault(depth, []).append(definition.factor_id)
    return tuple(
        FactorExecutionLayer(depth=depth, factor_ids=tuple(grouped[depth]))
        for depth in sorted(grouped)
    )
