from __future__ import annotations

import asyncio
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
from app.repositories.factor_repository import FactorRepository
from app.services.domain_tasks import TaskCancellationRequested
from app.services.factors.dag import FactorDAGPlanner
from app.services.factors.engine import (
    FactorComputationInProgress,
    FactorEngine,
    InlineChunkExecutor,
)
from app.services.factors.snapshot_service import deterministic_snapshot_id
from tests.factor_fakes import FakeDatabase


def make_request(symbol_count=205, *, chunk_size=100, workers=3):
    return FactorComputeRequest(
        universe_snapshot_id="cn-all-2025-01-06",
        members=tuple(
            FactorUniverseMember(market=Market.CN, symbol=f"{index:06d}")
            for index in range(symbol_count)
        ),
        trade_date=date(2025, 1, 6),
        as_of=datetime(2025, 1, 6, 15, 30, tzinfo=timezone.utc),
        factors=(FactorVersionRef(factor_id="ret_1d", version=1),),
        source_versions={"daily_bars": "bars-v1"},
        chunk_size=chunk_size,
        workers=workers,
    )


async def load_members(request, members, plan):
    del request, plan
    return tuple(item.symbol for item in members)


def calculate_rows(data, plan, request, members, snapshot_id):
    del data, plan
    return [
        FactorValueRow(
            snapshot_id=snapshot_id,
            market=member.market,
            symbol=member.symbol,
            trade_date=request.trade_date,
            values={"ret_1d": int(member.symbol) / 10000},
            quality={"ret_1d": "ok"},
        )
        for member in members
    ]


def make_engine(repository, *, loader=load_members, calculator=calculate_rows):
    return FactorEngine(
        repository=repository,
        loader=loader,
        calculator=calculator,
        executor=InlineChunkExecutor(),
    )


def test_dag_layers_dependencies_and_shared_intermediates_are_deterministic():
    request = make_request(1).model_copy(
        update={"factors": (FactorVersionRef(factor_id="momentum_composite"),)}
    )
    plan = FactorDAGPlanner().plan(request)
    flattened = [factor_id for layer in plan.layers for factor_id in layer.factor_ids]
    assert flattened == list(plan.execution_order)
    assert flattened.index("ret_20d") < flattened.index("momentum_composite")
    assert "simple_returns" in plan.common_intermediates
    assert "rolling_window_20" in plan.common_intermediates
    assert plan.checksum == FactorDAGPlanner().plan(request).checksum


@pytest.mark.asyncio
async def test_engine_plans_once_chunks_at_default_and_reports_completed_symbols(monkeypatch):
    repository = FactorRepository(db=FakeDatabase())
    request = make_request()
    planner = FactorDAGPlanner()
    plan_calls = 0
    original_plan = planner.plan
    chunk_sizes = []
    progress = []

    def counted_plan(value):
        nonlocal plan_calls
        plan_calls += 1
        return original_plan(value)

    async def recording_loader(request, members, plan):
        chunk_sizes.append(len(members))
        return await load_members(request, members, plan)

    monkeypatch.setattr(planner, "plan", counted_plan)
    engine = FactorEngine(
        repository=repository,
        loader=recording_loader,
        calculator=calculate_rows,
        planner=planner,
        executor=InlineChunkExecutor(),
    )

    async def report(value, stage, message):
        progress.append((value, stage, message))

    result = await engine.compute(
        user_id="user-a",
        task_id="task-a",
        request=request,
        report_progress=report,
        is_cancelled=lambda: _false(),
    )

    assert result.snapshot.status == FactorSnapshotStatus.READY
    assert plan_calls == 1
    assert sorted(chunk_sizes) == [5, 100, 100]
    compute_progress = [value for value, stage, _ in progress if stage == "factor_compute"]
    assert compute_progress[-1] == 1.0
    completed = [round(value * 205) for value in compute_progress]
    increments = [completed[0], *(right - left for left, right in zip(completed, completed[1:]))]
    assert sorted(increments) == [5, 100, 100]


@pytest.mark.asyncio
async def test_chunk_failure_hides_partial_rows_and_retry_completes_same_snapshot():
    repository = FactorRepository(db=FakeDatabase())
    request = make_request(4, chunk_size=2, workers=1)
    attempts = {"fail": True}

    def flaky_calculator(data, plan, request, members, snapshot_id):
        if attempts["fail"] and members[0].symbol == "000002":
            raise RuntimeError("fixture chunk failure")
        return calculate_rows(data, plan, request, members, snapshot_id)

    engine = make_engine(repository, calculator=flaky_calculator)
    with pytest.raises(RuntimeError, match="fixture chunk failure"):
        await engine.compute(
            user_id="user-a",
            task_id="task-1",
            request=request,
            report_progress=_report,
            is_cancelled=_false,
        )
    job = (await repository.create_or_get_job(
        user_id="user-a", task_id="task-2", request=request
    ))[0]
    snapshot = await repository.get_snapshot(
        deterministic_snapshot_id("user-a", job.request_checksum),
        user_id="user-a",
    )
    assert snapshot is not None and snapshot.status == FactorSnapshotStatus.FAILED
    assert await repository.list_snapshot_values(snapshot.snapshot_id, user_id="user-a") == []

    attempts["fail"] = False
    retried = await engine.compute(
        user_id="user-a",
        task_id="task-2",
        request=request,
        report_progress=_report,
        is_cancelled=_false,
    )
    assert retried.snapshot.snapshot_id == snapshot.snapshot_id
    assert retried.snapshot.status == FactorSnapshotStatus.READY
    assert len(await repository.list_snapshot_values(
        snapshot.snapshot_id, user_id="user-a"
    )) == 4


@pytest.mark.asyncio
async def test_cancellation_marks_snapshot_failed_and_job_cancelled():
    repository = FactorRepository(db=FakeDatabase())
    request = make_request(2)
    checks = 0

    async def cancel_after_plan():
        nonlocal checks
        checks += 1
        return checks >= 2

    with pytest.raises(TaskCancellationRequested):
        await make_engine(repository).compute(
            user_id="user-a",
            task_id="task-cancel",
            request=request,
            report_progress=_report,
            is_cancelled=cancel_after_plan,
        )
    job, _ = await repository.create_or_get_job(
        user_id="user-a", task_id="task-cancel", request=request
    )
    assert job.status.value == "cancelled"
    assert job.snapshot_id is None


@pytest.mark.asyncio
async def test_concurrent_identical_request_has_one_owner():
    repository = FactorRepository(db=FakeDatabase())
    request = make_request(1, workers=1)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def slow_loader(request, members, plan):
        entered.set()
        await release.wait()
        return await load_members(request, members, plan)

    engine = make_engine(repository, loader=slow_loader)
    first = asyncio.create_task(
        engine.compute(
            user_id="user-a",
            task_id="task-owner",
            request=request,
            report_progress=_report,
            is_cancelled=_false,
        )
    )
    await entered.wait()
    with pytest.raises(FactorComputationInProgress, match="task-owner"):
        await engine.compute(
            user_id="user-a",
            task_id="task-duplicate",
            request=request,
            report_progress=_report,
            is_cancelled=_false,
        )
    release.set()
    assert (await first).snapshot.status == FactorSnapshotStatus.READY


async def _false():
    return False


async def _report(value, stage, message):
    del value, stage, message
