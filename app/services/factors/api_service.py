"""Authenticated application service for factor discovery and durable jobs."""

from __future__ import annotations

import math
import os
from datetime import date, datetime, timezone
from typing import Any
from uuid import uuid4

from pymongo import ASCENDING, DESCENDING

from app.models.domain_task import DomainTaskType
from app.models.factor import (
    FactorCategory,
    FactorComputeAccepted,
    FactorComputeApiRequest,
    FactorComputeRequest,
    FactorDefinition,
    FactorDefinitionListResponse,
    FactorJob,
    FactorSnapshot,
    FactorSnapshotListResponse,
    FactorSnapshotStatus,
    FactorStatus,
    FactorUniverseMember,
    FactorValidateRequest,
    FactorValidateResponse,
    FactorValidationIssue,
    FactorValueApiRow,
    FactorValuePage,
    FactorVersionRef,
)
from app.models.symbol import Market
from app.repositories.domain_task_repository import DomainTaskRepository
from app.repositories.factor_repository import FactorRepository
from app.services.factors.dag import FactorDAGPlanner
from app.services.factors.registry import FactorRegistry, global_factor_registry


class FactorApiNotFound(LookupError):
    pass


class FactorApiValidationError(ValueError):
    def __init__(self, response: FactorValidateResponse):
        super().__init__(response.issues[0].message if response.issues else "invalid factor request")
        self.response = response


def factor_feature_enabled() -> bool:
    """The rollout flag is deliberately off unless explicitly enabled."""
    return os.getenv("FACTOR_FEATURE_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


class FactorApiService:
    def __init__(
        self,
        *,
        factor_repository: FactorRepository,
        task_repository: DomainTaskRepository,
        registry: FactorRegistry | None = None,
    ) -> None:
        self.factor_repository = factor_repository
        self.task_repository = task_repository
        self.registry = registry or global_factor_registry
        self.planner = FactorDAGPlanner(self.registry)

    def list_definitions(
        self,
        *,
        category: FactorCategory | None,
        market: Market | None,
        status: FactorStatus | None,
        search: str | None,
        page: int,
        page_size: int,
    ) -> FactorDefinitionListResponse:
        items = list(self.registry.get_all())
        if category is not None:
            items = [item for item in items if item.category == category]
        if market is not None:
            items = [item for item in items if market in item.supported_markets]
        if status is not None:
            items = [item for item in items if item.status == status]
        if search and search.strip():
            needle = search.strip().casefold()
            items = [
                item
                for item in items
                if needle in item.factor_id.casefold()
                or needle in item.name.casefold()
                or needle in (item.display_name or "").casefold()
            ]
        items.sort(key=lambda item: (item.category.value, item.factor_id, item.version))
        total = len(items)
        offset = (page - 1) * page_size
        return FactorDefinitionListResponse(
            items=items[offset:offset + page_size],
            page=page,
            page_size=page_size,
            total=total,
        )

    def get_definition(self, factor_id: str) -> FactorDefinition:
        definition = self.registry.get_by_id(factor_id)
        if definition is None:
            raise FactorApiNotFound(f"unknown factor definition: {factor_id}")
        return definition

    def validate(self, request: FactorValidateRequest) -> FactorValidateResponse:
        try:
            internal = _validation_compute_request(request.market, request.factor_specs)
            plan = self.planner.plan(internal)
            unsupported = [
                definition.factor_id
                for definition in plan.definitions
                if request.market not in definition.supported_markets
            ]
            if unsupported:
                return FactorValidateResponse(
                    valid=False,
                    issues=[
                        FactorValidationIssue(
                            code="FACTOR_MARKET_UNSUPPORTED",
                            message=f"factor does not support market {request.market.value}",
                            factor_id=factor_id,
                        )
                        for factor_id in unsupported
                    ],
                )
            return FactorValidateResponse(
                valid=True,
                execution_order=plan.execution_order,
                required_columns=plan.required_columns,
                common_intermediates=plan.common_intermediates,
                plan_checksum=plan.checksum,
            )
        except KeyError as exc:
            return FactorValidateResponse(
                valid=False,
                issues=[FactorValidationIssue(code="FACTOR_NOT_FOUND", message=str(exc))],
            )
        except ValueError as exc:
            return FactorValidateResponse(
                valid=False,
                issues=[FactorValidationIssue(code="FACTOR_SPEC_INVALID", message=str(exc))],
            )

    async def create_compute(
        self, *, user_id: str, request: FactorComputeApiRequest
    ) -> FactorComputeAccepted:
        validation = self.validate(
            FactorValidateRequest(market=request.market, factor_specs=request.factor_specs)
        )
        if not validation.valid:
            raise FactorApiValidationError(validation)
        task_id = str(uuid4())
        internal = FactorComputeRequest(
            universe_snapshot_id=request.universe.snapshot_id,
            members=tuple(
                FactorUniverseMember(market=request.market, symbol=symbol)
                for symbol in request.universe.symbols
            ),
            start_date=request.start_date,
            trade_date=request.end_date,
            as_of=request.as_of,
            factors=request.factor_specs,
            source_versions=request.source_versions,
            adjustment=request.adj,
            chunk_size=request.chunk_size,
            workers=request.workers,
            request_nonce=task_id if request.force_recompute else None,
        )
        task = await self.task_repository.create_task(
            user_id=user_id,
            task_type=DomainTaskType.FACTOR_COMPUTE,
            payload=internal.model_dump(mode="json"),
            idempotency_key=f"factor:{internal.request_checksum}",
            task_id=task_id,
            stage="factor_queued",
            message="Factor computation queued",
        )
        job, created = await self.factor_repository.create_or_get_job(
            user_id=user_id,
            task_id=task.task_id,
            request=internal,
        )
        return FactorComputeAccepted(
            job_id=job.job_id,
            task_id=task.task_id,
            request_checksum=internal.request_checksum,
            deduplicated=not created,
        )

    async def get_job(self, *, user_id: str, job_id: str) -> FactorJob:
        job = await self.factor_repository.get_job(job_id, user_id)
        if job is None:
            raise FactorApiNotFound(f"unknown factor job: {job_id}")
        return job

    async def list_snapshots(
        self,
        *,
        user_id: str,
        market: Market | None,
        trade_date: date | None,
        snapshot_status: FactorSnapshotStatus,
        page: int,
        page_size: int,
    ) -> FactorSnapshotListResponse:
        collection = self.factor_repository.get_db()[
            self.factor_repository.SNAPSHOTS_COLLECTION
        ]
        query: dict[str, Any] = {
            "user_id": user_id,
            "status": snapshot_status.value,
        }
        if market is not None:
            query["market"] = market.value
        if trade_date is not None:
            query["trade_date"] = trade_date.isoformat()
        total = await collection.count_documents(query)
        cursor = (
            collection.find(query)
            .sort([("trade_date", DESCENDING), ("snapshot_id", ASCENDING)])
            .skip((page - 1) * page_size)
            .limit(page_size)
        )
        documents = await cursor.to_list(length=page_size)
        return FactorSnapshotListResponse(
            items=[_snapshot(document) for document in documents],
            page=page,
            page_size=page_size,
            total=total,
        )

    async def list_values(
        self,
        *,
        user_id: str,
        snapshot_id: str,
        symbol: str | None,
        factors: tuple[str, ...],
        page: int,
        page_size: int,
    ) -> FactorValuePage:
        snapshot_document = await self.factor_repository.get_db()[
            self.factor_repository.SNAPSHOTS_COLLECTION
        ].find_one(
            {
                "snapshot_id": snapshot_id,
                "user_id": user_id,
                "status": FactorSnapshotStatus.READY.value,
            }
        )
        if snapshot_document is None:
            raise FactorApiNotFound(f"unknown ready factor snapshot: {snapshot_id}")
        snapshot = _snapshot(snapshot_document)
        query: dict[str, Any] = {"snapshot_id": snapshot_id, "user_id": user_id}
        if symbol is not None:
            query["symbol"] = symbol
        collection = self.factor_repository.get_db()[
            self.factor_repository.VALUES_COLLECTION
        ]
        total = await collection.count_documents(query)
        cursor = (
            collection.find(query)
            .sort([("symbol", ASCENDING), ("trade_date", ASCENDING)])
            .skip((page - 1) * page_size)
            .limit(page_size)
        )
        documents = await cursor.to_list(length=page_size)
        return FactorValuePage(
            snapshot=snapshot,
            items=[_value_row(document, factors=factors) for document in documents],
            page=page,
            page_size=page_size,
            total=total,
        )


def _validation_compute_request(
    market: Market, factors: tuple[FactorVersionRef, ...]
) -> FactorComputeRequest:
    boundary = datetime(2000, 1, 1, tzinfo=timezone.utc)
    return FactorComputeRequest(
        universe_snapshot_id="factor-validation",
        members=(FactorUniverseMember(market=market, symbol="VALIDATION"),),
        start_date=boundary.date(),
        trade_date=boundary.date(),
        as_of=boundary,
        factors=factors,
        source_versions={"validation": "static"},
        workers=1,
    )


def _snapshot(document: dict[str, Any]) -> FactorSnapshot:
    payload = dict(document)
    payload.pop("_id", None)
    return FactorSnapshot.model_validate(payload)


def _value_row(document: dict[str, Any], *, factors: tuple[str, ...]) -> FactorValueApiRow:
    available_values = document.get("values") or {}
    available_quality = document.get("quality") or {}
    selected = tuple(dict.fromkeys(factors)) or tuple(sorted(available_values))
    values: dict[str, float | None] = {}
    quality: dict[str, str | None] = {}
    for factor_id in selected:
        if factor_id not in available_values:
            values[factor_id] = None
            quality[factor_id] = "factor_not_in_snapshot"
            continue
        raw = available_values[factor_id]
        if raw is None:
            values[factor_id] = None
            quality[factor_id] = available_quality.get(factor_id)
        elif isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw):
            values[factor_id] = None
            quality[factor_id] = "non_finite_persisted_value"
        else:
            values[factor_id] = float(raw)
            quality[factor_id] = available_quality.get(factor_id)
    created_at = document.get("created_at")
    if isinstance(created_at, datetime) and created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return FactorValueApiRow(
        snapshot_id=str(document["snapshot_id"]),
        market=Market(document["market"]),
        symbol=str(document["symbol"]),
        trade_date=document["trade_date"],
        values=values,
        quality=quality,
        created_at=created_at,
    )
