"""Validated in-process registry for immutable factor metadata."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable

from app.models.factor import FactorCategory, FactorDefinition, FactorGroup, FactorStatus
from app.models.symbol import Market
from app.services.factors.definitions.catalog import FACTOR_CATALOG


class FactorRegistry:
    def __init__(self, definitions: Iterable[FactorDefinition] | None = None):
        items = tuple(FACTOR_CATALOG if definitions is None else definitions)
        self._definitions: dict[str, FactorDefinition] = {}
        outputs: dict[str, str] = {}
        for definition in items:
            if definition.checksum != definition.content_checksum():
                raise ValueError(
                    f"Checksum mismatch for {definition.factor_id}; rebuild the FactorDefinition"
                )
            if definition.factor_id in self._definitions:
                raise ValueError(f"Duplicate factor_id: {definition.factor_id}")
            assert definition.output_column is not None
            if definition.output_column in outputs:
                raise ValueError(
                    f"Output collision: {definition.output_column} is emitted by "
                    f"{outputs[definition.output_column]} and {definition.factor_id}"
                )
            self._definitions[definition.factor_id] = definition
            outputs[definition.output_column] = definition.factor_id
        self._validate_dependencies()
        self._topological_ids = self._topological_order()

    def _validate_dependencies(self) -> None:
        known = set(self._definitions)
        for definition in self._definitions.values():
            unknown = set(definition.dependencies) - known
            if unknown:
                raise ValueError(
                    f"Unknown dependencies for {definition.factor_id}: {sorted(unknown)}"
                )

    def _topological_order(self) -> tuple[str, ...]:
        state: dict[str, int] = defaultdict(int)
        result: list[str] = []
        path: list[str] = []

        def visit(factor_id: str) -> None:
            if state[factor_id] == 2:
                return
            if state[factor_id] == 1:
                start = path.index(factor_id)
                cycle = path[start:] + [factor_id]
                raise ValueError(f"Dependency cycle: {' -> '.join(cycle)}")
            state[factor_id] = 1
            path.append(factor_id)
            for dependency in self._definitions[factor_id].dependencies:
                visit(dependency)
            path.pop()
            state[factor_id] = 2
            result.append(factor_id)

        for factor_id in self._definitions:
            visit(factor_id)
        return tuple(result)

    def get_all(self) -> tuple[FactorDefinition, ...]:
        return tuple(self._definitions.values())

    def get_by_id(self, factor_id: str) -> FactorDefinition | None:
        return self._definitions.get(factor_id)

    def require(self, factor_id: str) -> FactorDefinition:
        definition = self.get_by_id(factor_id)
        if definition is None:
            raise KeyError(f"unknown factor_id: {factor_id}")
        return definition

    def get_by_category(self, category: FactorCategory | str) -> tuple[FactorDefinition, ...]:
        normalized = FactorCategory(category)
        return tuple(item for item in self._definitions.values() if item.category == normalized)

    def get_by_market(self, market: Market | str) -> tuple[FactorDefinition, ...]:
        normalized = Market(market)
        return tuple(item for item in self._definitions.values() if normalized in item.supported_markets)

    def get_by_group(self, group: FactorGroup | str) -> tuple[FactorDefinition, ...]:
        normalized = FactorGroup(group)
        return tuple(item for item in self._definitions.values() if item.catalog_group == normalized)

    def get_by_status(self, status: FactorStatus | str) -> tuple[FactorDefinition, ...]:
        normalized = FactorStatus(status)
        return tuple(item for item in self._definitions.values() if item.status == normalized)

    def dependency_order(self, factor_ids: Iterable[str] | None = None) -> tuple[FactorDefinition, ...]:
        if factor_ids is None:
            selected = set(self._definitions)
        else:
            selected = set(factor_ids)
            unknown = selected - set(self._definitions)
            if unknown:
                raise KeyError(f"unknown factor IDs: {sorted(unknown)}")

            def include_dependencies(factor_id: str) -> None:
                for dependency in self._definitions[factor_id].dependencies:
                    if dependency not in selected:
                        selected.add(dependency)
                        include_dependencies(dependency)

            for factor_id in tuple(selected):
                include_dependencies(factor_id)
        return tuple(self._definitions[factor_id] for factor_id in self._topological_ids if factor_id in selected)

    @property
    def count(self) -> int:
        return len(self._definitions)

    @property
    def catalog_checksum(self) -> str:
        payload = "\n".join(
            f"{item.factor_id}:{item.version}:{item.checksum}" for item in self._definitions.values()
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


global_factor_registry = FactorRegistry()
