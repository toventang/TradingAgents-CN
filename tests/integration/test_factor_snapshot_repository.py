from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.models.factor import (
    FactorComputeRequest,
    FactorSnapshotStatus,
    FactorUniverseMember,
    FactorValueRow,
    FactorVersionRef,
)
from app.models.symbol import Market
from app.repositories.factor_repository import FactorRepository, FactorSnapshotConflict
from app.services.factors.snapshot_service import (
    FactorSnapshotService,
    deterministic_values_checksum,
)
from tests.factor_fakes import FakeDatabase


def request_for(symbols=("000001", "000002")):
    return FactorComputeRequest(
        universe_snapshot_id="fixed-cn-universe-v1",
        members=tuple(
            FactorUniverseMember(market=Market.CN, symbol=symbol) for symbol in symbols
        ),
        trade_date=date(2025, 1, 6),
        as_of=datetime(2025, 1, 6, 15, 30, tzinfo=timezone.utc),
        factors=(FactorVersionRef(factor_id="ret_1d"),),
        source_versions={"daily_bars": "v1"},
    )


def rows_for(snapshot_id, request, *, reverse=False):
    rows = [
        FactorValueRow(
            snapshot_id=snapshot_id,
            market=member.market,
            symbol=member.symbol,
            trade_date=request.trade_date,
            values={"ret_1d": index / 100},
            quality={"ret_1d": "ok"},
        )
        for index, member in enumerate(request.members, 1)
    ]
    return tuple(reversed(rows)) if reverse else tuple(rows)


async def begin(repository, request, *, user_id="user-a", task_id="task-a"):
    job, _ = await repository.create_or_get_job(
        user_id=user_id, task_id=task_id, request=request
    )
    job = await repository.mark_job_running(job.job_id, task_id, user_id=user_id)
    return await FactorSnapshotService(repository).begin(
        user_id=user_id, task_id=task_id, job=job, request=request
    )


@pytest.mark.asyncio
async def test_compute_indexes_cover_ownership_state_and_value_queries_without_ttl():
    db = FakeDatabase()
    repository = FactorRepository(db=db)
    await repository.ensure_compute_indexes()
    all_indexes = [item for collection in db.collections.values() for item in collection.indexes]
    names = {options["name"] for _, options in all_indexes}
    assert "factor_job_owner_request_unique" in names
    assert "factor_snapshot_owner_state_date" in names
    assert "factor_value_snapshot_symbol_date_unique" in names
    assert "factor_value_market_date_snapshot" in names
    assert "factor_value_symbol_date" in names
    assert all("expireAfterSeconds" not in options for _, options in all_indexes)


@pytest.mark.asyncio
async def test_partial_snapshot_is_not_published_and_failed_values_stay_hidden():
    repository = FactorRepository(db=FakeDatabase())
    request = request_for()
    service = FactorSnapshotService(repository)
    snapshot = await begin(repository, request)
    await service.write_chunk(
        user_id="user-a",
        snapshot=snapshot,
        request=request,
        members=request.members[:1],
        chunk_id="00000000",
        rows=rows_for(snapshot.snapshot_id, request)[:1],
    )
    assert await repository.list_snapshot_values(snapshot.snapshot_id, user_id="user-a") == []
    with pytest.raises(FactorSnapshotConflict, match="row completeness"):
        await service.publish(user_id="user-a", snapshot=snapshot, request=request)
    failed = await service.fail(
        user_id="user-a",
        snapshot_id=snapshot.snapshot_id,
        code="TEST_FAILURE",
        message="fixture",
    )
    assert failed is not None and failed.status == FactorSnapshotStatus.FAILED
    assert await repository.list_snapshot_values(snapshot.snapshot_id, user_id="user-a") == []


@pytest.mark.asyncio
async def test_atomic_ready_snapshot_is_immutable_user_scoped_and_deterministic():
    repository = FactorRepository(db=FakeDatabase())
    request = request_for()
    service = FactorSnapshotService(repository)
    snapshot = await begin(repository, request)
    await service.write_chunk(
        user_id="user-a",
        snapshot=snapshot,
        request=request,
        members=request.members,
        chunk_id="00000000",
        rows=rows_for(snapshot.snapshot_id, request, reverse=True),
    )
    ready = await service.publish(user_id="user-a", snapshot=snapshot, request=request)
    assert ready.status == FactorSnapshotStatus.READY
    assert ready.row_count == 2 and ready.factor_count == 1
    assert len(await repository.list_snapshot_values(
        ready.snapshot_id, user_id="user-a"
    )) == 2
    assert await repository.list_snapshot_values(
        ready.snapshot_id, user_id="user-b"
    ) == []
    persisted = await repository.list_snapshot_values(
        ready.snapshot_id, user_id="user-a"
    )
    assert deterministic_values_checksum(
        persisted,
        factor_set_checksum=request.factor_set_checksum,
        source_versions=request.source_versions,
    ) == deterministic_values_checksum(
        reversed(persisted),
        factor_set_checksum=request.factor_set_checksum,
        source_versions=request.source_versions,
    ) == ready.values_checksum
    with pytest.raises(FactorSnapshotConflict, match="building snapshot"):
        await service.write_chunk(
            user_id="user-a",
            snapshot=snapshot,
            request=request,
            members=request.members,
            chunk_id="00000001",
            rows=rows_for(snapshot.snapshot_id, request),
        )

    duplicate_job, created = await repository.create_or_get_job(
        user_id="user-a", task_id="task-b", request=request
    )
    assert created is False
    assert duplicate_job.request_checksum == request.request_checksum
    reread = await service.begin(
        user_id="user-a", task_id="task-b", job=duplicate_job, request=request
    )
    assert reread.values_checksum == ready.values_checksum

    superseded = await repository.mark_snapshot_superseded(
        ready.snapshot_id, user_id="user-a"
    )
    assert superseded is not None and superseded.status == FactorSnapshotStatus.SUPERSEDED
    assert await repository.list_snapshot_values(ready.snapshot_id, user_id="user-a") == []


@pytest.mark.asyncio
async def test_job_mutations_are_owner_scoped():
    repository = FactorRepository(db=FakeDatabase())
    request = request_for(("000001",))
    job, _ = await repository.create_or_get_job(
        user_id="user-a", task_id="task-a", request=request
    )
    with pytest.raises(KeyError, match="unknown factor job"):
        await repository.mark_job_running(
            job.job_id, "task-b", user_id="user-b"
        )
    unchanged = await repository.get_job(job.job_id, "user-a")
    assert unchanged is not None and unchanged.task_id == "task-a"
