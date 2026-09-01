from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.models.backtest import (
    BacktestInputBundle,
    BenchmarkBar,
    DailyBacktestInput,
    MarketRuleVersion,
    OrderSide,
    SecurityRuleContext,
    UniverseMembership,
)
from app.models.market_data import DailyBar
from app.models.symbol import Market
from app.repositories.backtest_repository import BacktestRepository
from app.services.backtest.engine import (
    BacktestEngine,
    BacktestRunPlan,
    OrderIntent,
    StrategyDecision,
)
from app.services.backtest.ledger import BacktestRunRecord, BacktestRunStatus
from app.services.calendars.market_calendar import MarketCalendarService
from app.services.domain_tasks import TaskCancellationRequested
from tests.strategy_fakes import FakeDatabase


DAYS = (date(2024, 1, 8), date(2024, 1, 9), date(2024, 1, 10))


class BuyThenExitPolicy:
    async def evaluate(self, day, portfolio):
        del portfolio
        if day.trade_date == DAYS[0]:
            return StrategyDecision(
                entry_orders=(
                    OrderIntent(
                        signal_id="entry-day-1",
                        symbol="600000",
                        side=OrderSide.BUY,
                        quantity=100,
                    ),
                )
            )
        if day.trade_date == DAYS[1]:
            return StrategyDecision(
                exit_orders=(
                    OrderIntent(
                        signal_id="exit-day-2",
                        symbol="600000",
                        side=OrderSide.SELL,
                        cooldown_sessions=1,
                    ),
                ),
                entry_orders=(
                    OrderIntent(
                        signal_id="conflicting-entry",
                        symbol="600000",
                        side=OrderSide.BUY,
                        quantity=100,
                    ),
                ),
            )
        return StrategyDecision()


def make_bundle() -> BacktestInputBundle:
    membership = UniverseMembership(
        universe_id="fixture",
        market=Market.CN,
        symbol="600000",
        effective_from=date(2020, 1, 1),
        known_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        listing_date=date(2000, 1, 1),
        source="fixture",
        source_version="universe-v1",
    )
    market_rule = MarketRuleVersion(
        rule_version_id="cn-2024",
        market=Market.CN,
        effective_from=date(2024, 1, 1),
        published_at=datetime(2023, 12, 1, tzinfo=timezone.utc),
        rules={
            "lot_size": 100,
            "t_plus": 1,
            "price_limit_pct": "0.10",
            "fees": {
                "commission_rate": "0.0003",
                "minimum_commission": "5",
                "stamp_duty_rate": "0.001",
            },
        },
    )
    closes = (Decimal("10"), Decimal("10"), Decimal("11"))
    opens = (Decimal("10"), Decimal("10"), Decimal("11"))
    items = []
    for index, trade_date in enumerate(DAYS):
        signal_as_of = MarketCalendarService.daily_as_of(Market.CN, trade_date)
        items.append(
            DailyBacktestInput(
                market=Market.CN,
                trade_date=trade_date,
                signal_as_of=signal_as_of,
                universe_id="fixture",
                universe=(membership,),
                bars=(
                    DailyBar(
                        market=Market.CN,
                        symbol="600000",
                        trade_date=trade_date,
                        open=float(opens[index]),
                        high=float(max(opens[index], closes[index]) + 1),
                        low=float(min(opens[index], closes[index]) - 1),
                        close=float(closes[index]),
                        pre_close=float(closes[max(0, index - 1)]),
                        volume=10000,
                        amount=float(closes[index] * 10000),
                        source="fixture",
                        source_version="bars-v1",
                    ),
                ),
                benchmark=BenchmarkBar(
                    benchmark_id="csi300",
                    market=Market.CN,
                    symbol="000300",
                    trade_date=trade_date,
                    close=Decimal(100 + index),
                    source="fixture",
                    source_version="benchmark-v1",
                    ingested_at=signal_as_of,
                ),
                market_rule=market_rule,
                source_versions={"bars": ("bars-v1",)},
            )
        )
    return BacktestInputBundle(
        market=Market.CN,
        start_date=DAYS[0],
        end_date=DAYS[-1],
        days=tuple(items),
    )


def make_run(run_id="run-engine", task_id="task-engine") -> BacktestRunRecord:
    return BacktestRunRecord(
        run_id=run_id,
        task_id=task_id,
        user_id="owner",
        strategy_version_id="strategy-v1",
        market=Market.CN,
        request={"initial_cash": "10000", "benchmark": "csi300"},
        input_versions={"bars": ("bars-v1",)},
    )


async def no_cancel():
    return False


async def no_progress(progress, stage, message=None):
    del progress, stage, message


def make_engine(repository, policy=None):
    plan = BacktestRunPlan(
        bundle=make_bundle(),
        initial_cash=Decimal("10000"),
        policy=policy or BuyThenExitPolicy(),
        security_contexts={
            "600000": SecurityRuleContext(
                market=Market.CN, symbol="600000"
            )
        },
    )

    async def load_plan(run):
        assert run.strategy_version_id == "strategy-v1"
        return plan

    return BacktestEngine(repository, plan_loader=load_plan)


@pytest.mark.asyncio
async def test_engine_executes_twelve_steps_and_reconciles_every_day_by_hand():
    database = FakeDatabase()
    repository = BacktestRepository(database)
    await repository.create_run(make_run())
    progress = []

    async def report(value, stage, message=None):
        progress.append((value, stage, message))

    result = await make_engine(repository).run(
        run_id="run-engine",
        user_id="owner",
        task_id="task-engine",
        report_progress=report,
        is_cancelled=no_cancel,
    )

    assert result.status == BacktestRunStatus.SUCCEEDED
    assert result.summary["completed_days"] == 3
    assert result.summary["order_count"] == 2
    assert result.summary["trade_count"] == 2
    assert result.summary["final_cash"] == "10088.90"
    assert result.summary["final_equity"] == "10088.90"
    assert progress[-1][0] == 1

    equity_rows = database[repository.EQUITY_COLLECTION].documents
    assert len(equity_rows) == 3
    for row in equity_rows:
        assert Decimal(row["cash"]) + Decimal(row["market_value"]) == Decimal(
            row["equity"]
        )
    assert Decimal(equity_rows[1]["cash"]) == Decimal("8995.00")
    assert Decimal(equity_rows[1]["market_value"]) == Decimal("1000.00")
    assert Decimal(equity_rows[1]["equity"]) == Decimal("9995.00")
    assert Decimal(equity_rows[2]["cash"]) == Decimal("10088.90")
    assert Decimal(equity_rows[2]["market_value"]) == Decimal("0")

    positions = database[repository.POSITIONS_COLLECTION].documents
    assert len(positions) == 1
    assert positions[0]["trade_date"] == DAYS[1].isoformat()
    assert positions[0]["quantity"] == 100
    assert positions[0]["available_qty"] == 0

    trades = database[repository.TRADES_COLLECTION].documents
    assert len(trades) == 2
    assert Decimal(trades[0]["fees"]["total"]) == Decimal("5.00")
    assert Decimal(trades[1]["fees"]["total"]) == Decimal("6.10")
    orders = database[repository.ORDERS_COLLECTION].documents
    assert {item["status"] for item in orders} == {"filled"}

    events = database[repository.EVENTS_COLLECTION].documents
    for trade_date in DAYS:
        daily = sorted(
            (item for item in events if item["trade_date"] == trade_date.isoformat()),
            key=lambda item: item["sequence"],
        )
        assert {item["step"] for item in daily} == set(range(1, 13))
        assert [item["step"] for item in daily] == sorted(item["step"] for item in daily)
    assert any(
        item["event_type"] == "ORDER_INTENT_BLOCKED"
        and item["data"]["reason"] == "EXIT_PRIORITY"
        for item in events
    )
    checkpoint = await repository.latest_checkpoint("run-engine", user_id="owner")
    assert checkpoint is not None
    assert checkpoint.pending_orders == ()
    assert checkpoint.portfolio_state["cash"] == "10088.90"


class InterruptOnceRepository(BacktestRepository):
    def __init__(self, database):
        super().__init__(database)
        self.interrupted = False

    async def commit_day(self, batch):
        await super().commit_day(batch)
        if not self.interrupted:
            self.interrupted = True
            raise RuntimeError("simulated worker loss after durable checkpoint")


@pytest.mark.asyncio
async def test_retry_resumes_after_checkpoint_without_duplicate_orders_or_events():
    database = FakeDatabase()
    repository = InterruptOnceRepository(database)
    await repository.create_run(make_run(run_id="run-resume", task_id="task-resume"))
    engine = make_engine(repository)

    with pytest.raises(RuntimeError, match="worker loss"):
        await engine.run(
            run_id="run-resume",
            user_id="owner",
            task_id="task-resume",
            report_progress=no_progress,
            is_cancelled=no_cancel,
        )
    first_checkpoint = await repository.latest_checkpoint(
        "run-resume", user_id="owner"
    )
    assert first_checkpoint is not None and first_checkpoint.trade_date == DAYS[0]

    result = await engine.run(
        run_id="run-resume",
        user_id="owner",
        task_id="task-resume",
        report_progress=no_progress,
        is_cancelled=no_cancel,
    )

    assert result.status == BacktestRunStatus.SUCCEEDED
    assert len(database[repository.TRADES_COLLECTION].documents) == 2
    assert len(database[repository.ORDERS_COLLECTION].documents) == 2
    event_ids = [item["event_id"] for item in database[repository.EVENTS_COLLECTION].documents]
    assert len(event_ids) == len(set(event_ids))
    checkpoints = database[repository.CHECKPOINTS_COLLECTION].documents
    assert len(checkpoints) == 3


@pytest.mark.asyncio
async def test_cancellation_before_next_day_produces_no_later_trades():
    database = FakeDatabase()
    repository = BacktestRepository(database)
    await repository.create_run(make_run(run_id="run-cancel", task_id="task-cancel"))
    calls = 0

    async def cancel_before_second_day():
        nonlocal calls
        calls += 1
        # initial check, day-1 precheck, day-1 step 12, then day-2 precheck
        return calls >= 4

    with pytest.raises(TaskCancellationRequested):
        await make_engine(repository).run(
            run_id="run-cancel",
            user_id="owner",
            task_id="task-cancel",
            report_progress=no_progress,
            is_cancelled=cancel_before_second_day,
        )

    run = await repository.get_run("run-cancel", user_id="owner")
    assert run is not None and run.status == BacktestRunStatus.CANCELLED
    assert database[repository.TRADES_COLLECTION].documents == []
    checkpoints = database[repository.CHECKPOINTS_COLLECTION].documents
    assert len(checkpoints) == 1


@pytest.mark.asyncio
async def test_missing_current_close_uses_last_price_and_records_data_quality_event():
    original = make_bundle()
    stale_day = DailyBacktestInput.model_validate(
        {
            **original.days[-1].model_dump(
                mode="python", exclude={"input_checksum"}
            ),
            "bars": (),
        }
    )
    bundle = BacktestInputBundle.model_validate(
        {
            **original.model_dump(mode="python", exclude={"bundle_checksum"}),
            "days": (*original.days[:-1], stale_day),
        }
    )

    class BuyOnlyPolicy:
        async def evaluate(self, day, portfolio):
            del portfolio
            if day.trade_date == DAYS[0]:
                return StrategyDecision(
                    entry_orders=(
                        OrderIntent(
                            signal_id="stale-price-entry",
                            symbol="600000",
                            side=OrderSide.BUY,
                            quantity=100,
                        ),
                    )
                )
            return StrategyDecision()

    async def load_plan(run):
        del run
        return BacktestRunPlan(
            bundle=bundle,
            initial_cash=Decimal("10000"),
            policy=BuyOnlyPolicy(),
        )

    database = FakeDatabase()
    repository = BacktestRepository(database)
    await repository.create_run(make_run(run_id="run-stale", task_id="task-stale"))
    result = await BacktestEngine(repository, plan_loader=load_plan).run(
        run_id="run-stale",
        user_id="owner",
        task_id="task-stale",
        report_progress=no_progress,
        is_cancelled=no_cancel,
    )

    assert result.status == BacktestRunStatus.SUCCEEDED
    last_equity = database[repository.EQUITY_COLLECTION].documents[-1]
    assert Decimal(last_equity["cash"]) == Decimal("8995.00")
    assert Decimal(last_equity["market_value"]) == Decimal("1000.00")
    assert Decimal(last_equity["equity"]) == Decimal("9995.00")
    assert any(
        item["trade_date"] == DAYS[-1].isoformat()
        and item["event_type"] == "VALUATION_STALE"
        and item["symbol"] == "600000"
        for item in database[repository.EVENTS_COLLECTION].documents
    )
