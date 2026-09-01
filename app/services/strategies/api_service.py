"""Application service for authenticated strategy HTTP operations."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.models.domain_task import DomainTask, DomainTaskType
from app.models.strategy import (
    SYSTEM_USER_ID,
    Strategy,
    StrategySignal,
    StrategyVersion,
    StrategyVersionStatus,
)
from app.models.symbol import Market
from app.repositories.domain_task_repository import DomainTaskRepository
from app.repositories.strategy_repository import StrategyRepository
from app.services.strategies.templates import SYSTEM_STRATEGY_TEMPLATES
from app.services.strategies.validator import DSLValidationReport, StrategyDSLValidator
from app.services.strategies.version_service import StrategyVersionService


class StrategyApiNotFound(LookupError):
    pass


class StrategyApiValidationError(ValueError):
    def __init__(self, report: DSLValidationReport):
        self.report = report
        super().__init__("strategy validation failed")


class StrategyApiService:
    def __init__(
        self,
        *,
        repository: StrategyRepository,
        task_repository: DomainTaskRepository,
        version_service: StrategyVersionService | None = None,
        validator: StrategyDSLValidator | None = None,
    ):
        self.repository = repository
        self.task_repository = task_repository
        self.versions = version_service or StrategyVersionService(repository)
        self.validator = validator or StrategyDSLValidator()

    def list_templates(self):
        return SYSTEM_STRATEGY_TEMPLATES

    async def create(self, *, user_id: str, request) -> tuple[Strategy, StrategyVersion]:
        return await self.versions.create_strategy(
            user_id=user_id,
            name=request.name,
            description=request.description,
            tags=request.tags,
            kind=request.kind,
            market=request.market,
            definition=request.definition,
            analysis_profile_version_id=request.analysis_profile_version_id,
            change_summary=request.change_summary,
        )

    async def list(self, *, user_id: str) -> tuple[Strategy, ...]:
        owned = await self.repository.list_strategies(user_id=user_id, limit=500)
        system = await self.repository.list_strategies(
            user_id=SYSTEM_USER_ID, limit=500
        )
        return tuple(
            sorted(
                (*owned, *system),
                key=lambda item: (
                    item.user_id != user_id,
                    item.name,
                    item.strategy_id,
                ),
            )
        )

    async def detail(
        self, *, user_id: str, strategy_id: str
    ) -> tuple[Strategy, tuple[StrategyVersion, ...]]:
        strategy = await self.repository.get_strategy(strategy_id, user_id=user_id)
        if strategy is None:
            raise StrategyApiNotFound("strategy not found")
        versions = await self.repository.list_versions(
            strategy.strategy_id, user_id=strategy.user_id
        )
        return strategy, versions

    async def create_version(
        self, *, user_id: str, strategy_id: str, parent_version_id: str | None, change_summary: str
    ) -> StrategyVersion:
        return await self.versions.create_next_draft(
            strategy_id=strategy_id,
            user_id=user_id,
            parent_version_id=parent_version_id,
            change_summary=change_summary,
        )

    async def update_version(
        self, *, user_id: str, strategy_id: str, version_id: str, request
    ) -> StrategyVersion:
        strategy = await self.repository.get_strategy(
            strategy_id, user_id=user_id, include_readonly=False
        )
        if strategy is None or strategy.current_draft_version_id != version_id:
            raise StrategyApiNotFound("current strategy draft not found")
        return await self.versions.update_draft(
            strategy_id=strategy_id,
            user_id=user_id,
            definition=request.definition,
            expected_checksum=request.expected_checksum,
            analysis_profile_version_id=request.analysis_profile_version_id,
            change_summary=request.change_summary,
        )

    async def validate(
        self,
        *,
        user_id: str,
        market: Market | None,
        definition: dict[str, Any] | None,
        strategy_version_id: str | None,
    ) -> DSLValidationReport:
        if (definition is None) == (strategy_version_id is None):
            raise ValueError("provide exactly one of definition or strategy_version_id")
        if strategy_version_id is not None:
            version = await self.repository.get_version(
                strategy_version_id, user_id=user_id, include_system=True
            )
            if version is None:
                raise StrategyApiNotFound("strategy version not found")
            definition = version.definition
            market = version.market
        if market is None:
            raise ValueError("market is required for inline validation")
        assert definition is not None
        return self.validator.validate(definition, market=market, user_id=user_id)

    async def publish(
        self, *, user_id: str, strategy_id: str, version_id: str
    ) -> StrategyVersion:
        strategy = await self.repository.get_strategy(
            strategy_id, user_id=user_id, include_readonly=False
        )
        if strategy is None or strategy.current_draft_version_id != version_id:
            raise StrategyApiNotFound("current strategy draft not found")
        version = await self.repository.get_owned_version(version_id, user_id=user_id)
        if version is None:
            raise StrategyApiNotFound("strategy version not found")
        report = self.validator.validate(
            version.definition, market=version.market, user_id=user_id
        )
        if not report.valid:
            raise StrategyApiValidationError(report)
        return await self.versions.publish_draft(
            strategy_id=strategy_id,
            user_id=user_id,
            validation_result=report.as_lifecycle_result(),
            factor_dependencies=report.factor_dependencies,
            skill_dependencies=report.skill_dependencies,
        )

    async def clone(
        self, *, user_id: str, strategy_id: str, request
    ) -> tuple[Strategy, StrategyVersion]:
        return await self.versions.clone_strategy(
            source_strategy_id=strategy_id,
            source_strategy_version_id=request.source_version_id,
            user_id=user_id,
            name=request.name,
            description=request.description,
            tags=request.tags,
        )

    async def archive(self, *, user_id: str, strategy_id: str) -> Strategy:
        return await self.versions.archive_strategy(strategy_id, user_id=user_id)

    async def create_signal_task(
        self, *, user_id: str, strategy_version_id: str, request
    ) -> DomainTask:
        version = await self.repository.get_version(
            strategy_version_id, user_id=user_id, include_system=True
        )
        if version is None or version.status not in {
            StrategyVersionStatus.PUBLISHED,
            StrategyVersionStatus.DEPRECATED,
        }:
            raise StrategyApiNotFound("published strategy version not found")
        payload = {
            "strategy_version_id": version.strategy_version_id,
            "universe_snapshot_id": request.universe_snapshot_id,
            "factor_snapshot_ids": list(request.factor_snapshot_ids),
            "as_of": request.as_of.isoformat(),
        }
        return await self.task_repository.create_task(
            user_id=user_id,
            task_type=DomainTaskType.STRATEGY_RUN,
            payload=payload,
            priority=10,
            max_attempts=3,
            idempotency_key=request.idempotency_key,
            stage="strategy_signal_queued",
            message="Strategy signal calculation queued",
        )

    async def list_signals(
        self,
        *,
        user_id: str,
        strategy_version_id: str | None,
        signal_date: date | None,
        symbol: str | None,
        page: int,
        page_size: int,
    ) -> tuple[tuple[StrategySignal, ...], int]:
        query: dict[str, Any] = {"user_id": user_id}
        if strategy_version_id is not None:
            query["strategy_version_id"] = strategy_version_id
        if signal_date is not None:
            query["signal_date"] = signal_date.isoformat()
        if symbol is not None:
            query["symbol"] = symbol
        cursor = self.repository.get_db()[self.repository.SIGNALS_COLLECTION].find(query)
        documents = await cursor.to_list(length=None)
        documents.sort(
            key=lambda item: (
                item.get("signal_date", ""),
                item.get("symbol", ""),
                item.get("signal_type", ""),
            ),
            reverse=True,
        )
        total = len(documents)
        start = (page - 1) * page_size
        items = []
        for document in documents[start : start + page_size]:
            payload = dict(document)
            payload.pop("_id", None)
            items.append(StrategySignal.model_validate(payload))
        return tuple(items), total
