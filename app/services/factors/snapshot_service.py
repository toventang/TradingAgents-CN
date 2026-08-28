"""Atomic publication service for complete immutable factor snapshots."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Any, Iterable

from app.models.factor import (
    FactorComputeRequest,
    FactorJob,
    FactorSnapshot,
    FactorSnapshotStatus,
    FactorUniverseMember,
    FactorValueRow,
)
from app.repositories.factor_repository import FactorRepository, FactorSnapshotConflict


class FactorSnapshotService:
    def __init__(self, repository: FactorRepository):
        self.repository = repository

    async def begin(
        self,
        *,
        user_id: str,
        task_id: str,
        job: FactorJob,
        request: FactorComputeRequest,
    ) -> FactorSnapshot:
        snapshot_id = deterministic_snapshot_id(user_id, request.request_checksum)
        snapshot = FactorSnapshot(
            snapshot_id=snapshot_id,
            user_id=user_id,
            job_id=job.job_id,
            task_id=task_id,
            market=request.market,
            trade_date=request.trade_date,
            as_of=request.as_of,
            universe_snapshot_id=request.universe_snapshot_id,
            factor_set_checksum=request.factor_set_checksum,
            request_checksum=request.request_checksum,
            expected_row_count=len(request.members),
            expected_factor_count=len(request.factors),
            source_versions=request.source_versions,
        )
        return await self.repository.begin_snapshot(snapshot)

    async def write_chunk(
        self,
        *,
        user_id: str,
        snapshot: FactorSnapshot,
        request: FactorComputeRequest,
        members: Sequence[FactorUniverseMember],
        chunk_id: str,
        rows: Iterable[FactorValueRow | dict[str, Any]],
    ) -> int:
        if snapshot.status != FactorSnapshotStatus.BUILDING:
            raise FactorSnapshotConflict("only building snapshots accept chunks")
        requested = {item.factor_id for item in request.factors}
        normalized = tuple(
            row if isinstance(row, FactorValueRow) else FactorValueRow.model_validate(row)
            for row in rows
        )
        request_member_keys = {(item.market, item.symbol) for item in request.members}
        chunk_member_keys = {(item.market, item.symbol) for item in members}
        if not chunk_member_keys or not chunk_member_keys.issubset(request_member_keys):
            raise ValueError("chunk members must be a non-empty subset of the fixed universe")
        seen: set[tuple[Any, str, Any]] = set()
        for row in normalized:
            if row.snapshot_id != snapshot.snapshot_id:
                raise ValueError("chunk row snapshot_id does not match building snapshot")
            if (row.market, row.symbol) not in chunk_member_keys:
                raise ValueError("chunk row is outside the fixed universe")
            if row.trade_date != request.trade_date:
                raise ValueError("chunk row trade_date does not match request")
            if set(row.values) != requested or set(row.quality) != requested:
                raise ValueError("chunk row must contain every requested factor and quality key")
            key = (row.market, row.symbol, row.trade_date)
            if key in seen:
                raise ValueError("chunk contains duplicate factor value rows")
            seen.add(key)
        actual_chunk_members = {(row.market, row.symbol) for row in normalized}
        if actual_chunk_members != chunk_member_keys:
            raise ValueError("chunk must contain exactly one row for every assigned symbol")
        return await self.repository.write_value_rows(
            user_id=user_id, rows=normalized, chunk_id=chunk_id
        )

    async def publish(
        self,
        *,
        user_id: str,
        snapshot: FactorSnapshot,
        request: FactorComputeRequest,
    ) -> FactorSnapshot:
        rows = await self.repository.list_building_values(
            snapshot.snapshot_id, user_id=user_id
        )
        expected_members = {
            (item.market.value, item.symbol, request.trade_date.isoformat())
            for item in request.members
        }
        actual_members = {
            (str(row["market"]), str(row["symbol"]), str(row["trade_date"]))
            for row in rows
        }
        requested = {item.factor_id for item in request.factors}
        if actual_members != expected_members or len(rows) != len(expected_members):
            raise FactorSnapshotConflict("snapshot row completeness validation failed")
        for row in rows:
            if set(row.get("values", {})) != requested:
                raise FactorSnapshotConflict("snapshot factor value completeness validation failed")
            if set(row.get("quality", {})) != requested:
                raise FactorSnapshotConflict("snapshot quality completeness validation failed")
        checksum = deterministic_values_checksum(
            rows,
            factor_set_checksum=request.factor_set_checksum,
            source_versions=request.source_versions,
        )
        return await self.repository.mark_snapshot_ready(
            snapshot.snapshot_id,
            user_id=user_id,
            row_count=len(rows),
            factor_count=len(request.factors),
            values_checksum=checksum,
        )

    async def fail(
        self,
        *,
        user_id: str,
        snapshot_id: str,
        code: str,
        message: str,
    ) -> FactorSnapshot | None:
        return await self.repository.mark_snapshot_failed(
            snapshot_id,
            user_id=user_id,
            error={"code": code, "message": message},
        )


def deterministic_snapshot_id(user_id: str, request_checksum: str) -> str:
    return hashlib.sha256(f"{user_id}:{request_checksum}".encode("utf-8")).hexdigest()


def deterministic_values_checksum(
    rows: Iterable[dict[str, Any]],
    *,
    factor_set_checksum: str,
    source_versions: dict[str, str],
) -> str:
    canonical_rows = []
    for row in rows:
        canonical_rows.append(
            {
                "market": str(row["market"]),
                "symbol": str(row["symbol"]),
                "trade_date": str(row["trade_date"]),
                "values": dict(sorted(row["values"].items())),
                "quality": dict(sorted(row["quality"].items())),
            }
        )
    canonical_rows.sort(
        key=lambda item: (item["market"], item["symbol"], item["trade_date"])
    )
    payload = {
        "factor_set_checksum": factor_set_checksum,
        "source_versions": dict(sorted(source_versions.items())),
        "rows": canonical_rows,
    }
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()
