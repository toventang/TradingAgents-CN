"""Factor definitions, durable jobs, immutable snapshots, and value rows."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Iterable

from pymongo import ASCENDING, DESCENDING, ReturnDocument, UpdateOne
from pymongo.errors import DuplicateKeyError

from app.core.database import get_mongo_db
from app.models.factor import (
    FactorComputeRequest,
    FactorJob,
    FactorJobStatus,
    FactorSnapshot,
    FactorSnapshotStatus,
    FactorStatus,
    FactorValueRow,
)
from app.services.factors.registry import FactorRegistry, global_factor_registry


class FactorDefinitionMirrorConflict(RuntimeError):
    """The same published factor version has different static content."""


class FactorSnapshotConflict(RuntimeError):
    """An immutable value row or snapshot disagrees with persisted content."""


class FactorRepository:
    COLLECTION = "factor_definitions"
    JOBS_COLLECTION = "factor_jobs"
    SNAPSHOTS_COLLECTION = "factor_snapshots"
    VALUES_COLLECTION = "factor_values"

    def __init__(self, db=None, registry: FactorRegistry | None = None):
        self._db = db
        self._registry = registry or global_factor_registry
        self._compute_indexes_ready = False
        self._compute_index_lock = asyncio.Lock()

    def get_db(self):
        return self._db if self._db is not None else get_mongo_db()

    async def ensure_indexes(self) -> None:
        collection = self.get_db()[self.COLLECTION]
        await collection.create_index(
            [("factor_id", 1), ("version", 1)],
            unique=True,
            name="factor_id_version_unique",
        )
        await collection.create_index(
            [("status", 1), ("category", 1), ("factor_id", 1)],
            name="factor_status_category",
        )

    async def ensure_compute_indexes(self) -> None:
        if self._compute_indexes_ready:
            return
        async with self._compute_index_lock:
            if self._compute_indexes_ready:
                return
            jobs = self.get_db()[self.JOBS_COLLECTION]
            snapshots = self.get_db()[self.SNAPSHOTS_COLLECTION]
            values = self.get_db()[self.VALUES_COLLECTION]
            await jobs.create_index(
                [("user_id", ASCENDING), ("request_checksum", ASCENDING)],
                unique=True,
                name="factor_job_owner_request_unique",
            )
            await jobs.create_index(
                [("status", ASCENDING), ("updated_at", ASCENDING)],
                name="factor_job_state_scan",
            )
            await snapshots.create_index(
                [("snapshot_id", ASCENDING)],
                unique=True,
                name="factor_snapshot_id_unique",
            )
            await snapshots.create_index(
                [
                    ("user_id", ASCENDING),
                    ("status", ASCENDING),
                    ("trade_date", DESCENDING),
                ],
                name="factor_snapshot_owner_state_date",
            )
            await snapshots.create_index(
                [
                    ("market", ASCENDING),
                    ("trade_date", DESCENDING),
                    ("snapshot_id", ASCENDING),
                ],
                name="factor_snapshot_market_date",
            )
            await values.create_index(
                [
                    ("snapshot_id", ASCENDING),
                    ("market", ASCENDING),
                    ("symbol", ASCENDING),
                    ("trade_date", ASCENDING),
                ],
                unique=True,
                name="factor_value_snapshot_symbol_date_unique",
            )
            await values.create_index(
                [
                    ("market", ASCENDING),
                    ("trade_date", ASCENDING),
                    ("snapshot_id", ASCENDING),
                ],
                name="factor_value_market_date_snapshot",
            )
            await values.create_index(
                [("symbol", ASCENDING), ("trade_date", DESCENDING)],
                name="factor_value_symbol_date",
            )
            self._compute_indexes_ready = True

    async def sync_definitions(self) -> int:
        """Insert missing active metadata and reject in-place version changes."""
        await self.ensure_indexes()
        collection = self.get_db()[self.COLLECTION]
        inserted = 0
        for definition in self._registry.get_by_status(FactorStatus.ACTIVE):
            key = {"factor_id": definition.factor_id, "version": definition.version}
            existing = await collection.find_one(key)
            if existing is not None:
                if existing.get("checksum") != definition.checksum:
                    raise FactorDefinitionMirrorConflict(
                        f"{definition.factor_id} v{definition.version} is immutable; "
                        "static metadata changed without a version bump"
                    )
                continue
            document = definition.model_dump(mode="json")
            document["mirror_schema_version"] = 1
            result = await collection.update_one(key, {"$setOnInsert": document}, upsert=True)
            marker = getattr(result, "upserted_id", _UNKNOWN_RESULT)
            if marker is _UNKNOWN_RESULT or marker is not None:
                inserted += 1
            else:
                # Another process won the upsert race.  It is acceptable only
                # when it inserted the identical immutable definition.
                concurrent = await collection.find_one(key)
                if concurrent is None or concurrent.get("checksum") != definition.checksum:
                    raise FactorDefinitionMirrorConflict(
                        f"concurrent mirror conflict for {definition.factor_id} v{definition.version}"
                    )
        return inserted

    sync_active_definitions = sync_definitions

    async def get_definition(self, factor_id: str, version: int | None = None) -> dict[str, Any] | None:
        query: dict[str, Any] = {"factor_id": factor_id}
        if version is not None:
            query["version"] = version
            document = await self.get_db()[self.COLLECTION].find_one(query)
        else:
            document = await self.get_db()[self.COLLECTION].find_one(
                query, sort=[("version", -1)]
            )
        if document is None:
            return None
        document.pop("_id", None)
        return document

    async def create_or_get_job(
        self,
        *,
        user_id: str,
        task_id: str,
        request: FactorComputeRequest,
    ) -> tuple[FactorJob, bool]:
        collection = self.get_db()[self.JOBS_COLLECTION]
        key = {"user_id": user_id, "request_checksum": request.request_checksum}
        now = datetime.now(timezone.utc)
        job = FactorJob(
            user_id=user_id,
            task_id=task_id,
            request_checksum=request.request_checksum,
            request=request,
            total_symbols=len(request.members),
            created_at=now,
            updated_at=now,
        )
        try:
            result = await collection.update_one(
                key, {"$setOnInsert": job.model_dump(mode="json")}, upsert=True
            )
            created = getattr(result, "upserted_id", None) is not None
        except DuplicateKeyError:
            # An identical request won the unique-index race.  Read and reuse it.
            created = False
        document = await collection.find_one(key)
        if document is None:
            raise RuntimeError("factor job upsert did not persist a document")
        return _parse_model(FactorJob, document), created

    async def mark_job_running(
        self, job_id: str, task_id: str, *, user_id: str
    ) -> FactorJob:
        return await self._update_job(
            job_id,
            {
                "status": FactorJobStatus.RUNNING.value,
                "task_id": task_id,
                "completed_symbols": 0,
                "error": None,
                "updated_at": datetime.now(timezone.utc),
            },
            user_id=user_id,
        )

    async def update_job_progress(
        self, job_id: str, *, user_id: str, completed_symbols: int
    ) -> FactorJob:
        return await self._update_job(
            job_id,
            {
                "completed_symbols": completed_symbols,
                "updated_at": datetime.now(timezone.utc),
            },
            user_id=user_id,
        )

    async def mark_job_succeeded(
        self,
        job_id: str,
        snapshot_id: str,
        *,
        user_id: str,
        completed_symbols: int,
    ) -> FactorJob:
        document = await self.get_db()[self.JOBS_COLLECTION].find_one_and_update(
            {"job_id": job_id, "user_id": user_id},
            {
                "$set": {
                    "status": FactorJobStatus.SUCCEEDED.value,
                    "snapshot_id": snapshot_id,
                    "completed_symbols": completed_symbols,
                    "error": None,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if document is None:
            raise KeyError(f"unknown factor job: {job_id}")
        return _parse_model(FactorJob, document)

    async def mark_job_failed(
        self,
        job_id: str,
        *,
        user_id: str,
        error: dict[str, Any],
        cancelled: bool = False,
    ) -> FactorJob:
        return await self._update_job(
            job_id,
            {
                "status": (
                    FactorJobStatus.CANCELLED.value
                    if cancelled else FactorJobStatus.FAILED.value
                ),
                "error": error,
                "updated_at": datetime.now(timezone.utc),
            },
            user_id=user_id,
        )

    async def get_job(self, job_id: str, user_id: str) -> FactorJob | None:
        document = await self.get_db()[self.JOBS_COLLECTION].find_one(
            {"job_id": job_id, "user_id": user_id}
        )
        return None if document is None else _parse_model(FactorJob, document)

    async def begin_snapshot(self, snapshot: FactorSnapshot) -> FactorSnapshot:
        collection = self.get_db()[self.SNAPSHOTS_COLLECTION]
        key = {"snapshot_id": snapshot.snapshot_id, "user_id": snapshot.user_id}
        existing = await collection.find_one(key)
        if existing is not None:
            parsed = _parse_model(FactorSnapshot, existing)
            if parsed.request_checksum != snapshot.request_checksum:
                raise FactorSnapshotConflict("snapshot ID has a different request checksum")
            if parsed.status == FactorSnapshotStatus.FAILED:
                document = await collection.find_one_and_update(
                    {**key, "status": FactorSnapshotStatus.FAILED.value},
                    {
                        "$set": {
                            "status": FactorSnapshotStatus.BUILDING.value,
                            "task_id": snapshot.task_id,
                            "job_id": snapshot.job_id,
                            "error": None,
                            "updated_at": datetime.now(timezone.utc),
                        }
                    },
                    return_document=ReturnDocument.AFTER,
                )
                if document is not None:
                    return _parse_model(FactorSnapshot, document)
            return parsed
        try:
            await collection.update_one(
                key,
                {"$setOnInsert": snapshot.model_dump(mode="json")},
                upsert=True,
            )
        except DuplicateKeyError:
            # Snapshot IDs are deterministic, so the winner is validated below.
            pass
        document = await collection.find_one(key)
        if document is None:
            raise RuntimeError("factor snapshot upsert did not persist a document")
        parsed = _parse_model(FactorSnapshot, document)
        if parsed.request_checksum != snapshot.request_checksum:
            raise FactorSnapshotConflict("snapshot ID has a different request checksum")
        return parsed

    async def write_value_rows(
        self,
        *,
        user_id: str,
        rows: Iterable[FactorValueRow],
        chunk_id: str,
    ) -> int:
        normalized = tuple(rows)
        if not normalized:
            return 0
        snapshot_ids = {row.snapshot_id for row in normalized}
        if len(snapshot_ids) != 1:
            raise ValueError("one value batch must belong to exactly one snapshot")
        snapshot_id = next(iter(snapshot_ids))
        snapshot = await self.get_db()[self.SNAPSHOTS_COLLECTION].find_one(
            {
                "snapshot_id": snapshot_id,
                "user_id": user_id,
                "status": FactorSnapshotStatus.BUILDING.value,
            }
        )
        if snapshot is None:
            raise FactorSnapshotConflict("factor values can only be written to a building snapshot")
        now = datetime.now(timezone.utc)
        operations = []
        for row in normalized:
            document = row.model_dump(mode="json")
            document.update(
                {
                    "user_id": user_id,
                    "chunk_id": chunk_id,
                    "row_checksum": _row_checksum(document),
                    "created_at": now,
                }
            )
            key = {
                "snapshot_id": row.snapshot_id,
                "market": row.market.value,
                "symbol": row.symbol,
                "trade_date": row.trade_date.isoformat(),
            }
            operations.append(UpdateOne(key, {"$setOnInsert": document}, upsert=True))
        await self.get_db()[self.VALUES_COLLECTION].bulk_write(
            operations, ordered=False
        )
        persisted = await self._find_value_rows(snapshot_id)
        persisted_by_key = {
            (item["market"], item["symbol"], str(item["trade_date"])): item
            for item in persisted
        }
        for row in normalized:
            key = (row.market.value, row.symbol, row.trade_date.isoformat())
            document = persisted_by_key.get(key)
            expected = _row_checksum(row.model_dump(mode="json"))
            if document is None or document.get("row_checksum") != expected:
                raise FactorSnapshotConflict(
                    f"immutable factor value conflict for {row.market.value}.{row.symbol}"
                )
        return len(normalized)

    async def list_snapshot_values(
        self, snapshot_id: str, *, user_id: str, ready_only: bool = True
    ) -> list[dict[str, Any]]:
        snapshot_query: dict[str, Any] = {"snapshot_id": snapshot_id, "user_id": user_id}
        if ready_only:
            snapshot_query["status"] = FactorSnapshotStatus.READY.value
        if await self.get_db()[self.SNAPSHOTS_COLLECTION].find_one(snapshot_query) is None:
            return []
        return await self._find_value_rows(snapshot_id)

    async def list_building_values(
        self, snapshot_id: str, *, user_id: str
    ) -> list[dict[str, Any]]:
        snapshot = await self.get_db()[self.SNAPSHOTS_COLLECTION].find_one(
            {
                "snapshot_id": snapshot_id,
                "user_id": user_id,
                "status": FactorSnapshotStatus.BUILDING.value,
            }
        )
        return [] if snapshot is None else await self._find_value_rows(snapshot_id)

    async def mark_snapshot_ready(
        self,
        snapshot_id: str,
        *,
        user_id: str,
        row_count: int,
        factor_count: int,
        values_checksum: str,
    ) -> FactorSnapshot:
        now = datetime.now(timezone.utc)
        document = await self.get_db()[self.SNAPSHOTS_COLLECTION].find_one_and_update(
            {
                "snapshot_id": snapshot_id,
                "user_id": user_id,
                "status": FactorSnapshotStatus.BUILDING.value,
                "expected_row_count": row_count,
                "expected_factor_count": factor_count,
            },
            {
                "$set": {
                    "status": FactorSnapshotStatus.READY.value,
                    "row_count": row_count,
                    "factor_count": factor_count,
                    "values_checksum": values_checksum,
                    "published_at": now,
                    "updated_at": now,
                    "error": None,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if document is None:
            raise FactorSnapshotConflict("snapshot completeness changed before publication")
        return _parse_model(FactorSnapshot, document)

    async def mark_snapshot_failed(
        self,
        snapshot_id: str,
        *,
        user_id: str,
        error: dict[str, Any],
    ) -> FactorSnapshot | None:
        document = await self.get_db()[self.SNAPSHOTS_COLLECTION].find_one_and_update(
            {
                "snapshot_id": snapshot_id,
                "user_id": user_id,
                "status": FactorSnapshotStatus.BUILDING.value,
            },
            {
                "$set": {
                    "status": FactorSnapshotStatus.FAILED.value,
                    "error": error,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        return None if document is None else _parse_model(FactorSnapshot, document)

    async def mark_snapshot_superseded(
        self, snapshot_id: str, *, user_id: str
    ) -> FactorSnapshot | None:
        document = await self.get_db()[self.SNAPSHOTS_COLLECTION].find_one_and_update(
            {
                "snapshot_id": snapshot_id,
                "user_id": user_id,
                "status": FactorSnapshotStatus.READY.value,
            },
            {
                "$set": {
                    "status": FactorSnapshotStatus.SUPERSEDED.value,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        return None if document is None else _parse_model(FactorSnapshot, document)

    async def get_snapshot(
        self, snapshot_id: str, *, user_id: str
    ) -> FactorSnapshot | None:
        document = await self.get_db()[self.SNAPSHOTS_COLLECTION].find_one(
            {"snapshot_id": snapshot_id, "user_id": user_id}
        )
        return None if document is None else _parse_model(FactorSnapshot, document)

    async def _update_job(
        self, job_id: str, values: dict[str, Any], *, user_id: str
    ) -> FactorJob:
        document = await self.get_db()[self.JOBS_COLLECTION].find_one_and_update(
            {"job_id": job_id, "user_id": user_id},
            {"$set": values},
            return_document=ReturnDocument.AFTER,
        )
        if document is None:
            raise KeyError(f"unknown factor job: {job_id}")
        return _parse_model(FactorJob, document)

    async def _find_value_rows(self, snapshot_id: str) -> list[dict[str, Any]]:
        cursor = self.get_db()[self.VALUES_COLLECTION].find(
            {"snapshot_id": snapshot_id}
        ).sort([("market", ASCENDING), ("symbol", ASCENDING), ("trade_date", ASCENDING)])
        documents = await cursor.to_list(length=None)
        for document in documents:
            document.pop("_id", None)
        return documents


_UNKNOWN_RESULT = object()


def _parse_model(model, document: dict[str, Any]):
    payload = dict(document)
    payload.pop("_id", None)
    payload.pop("row_checksum", None)
    payload.pop("chunk_id", None)
    payload.pop("dedupe_key", None)
    return model.model_validate(payload)


def _row_checksum(document: dict[str, Any]) -> str:
    import hashlib
    import json

    payload = {
        key: document[key]
        for key in ("snapshot_id", "market", "symbol", "trade_date", "values", "quality")
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
