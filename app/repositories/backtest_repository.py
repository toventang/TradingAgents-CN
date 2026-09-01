"""Persistence boundary for point-in-time backtest reference inputs."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from typing import Any, Iterable, TypeVar

from pymongo import ASCENDING, DESCENDING, ReturnDocument

from app.core.database import get_mongo_db
from app.models.backtest import (
    BenchmarkBar,
    CorporateAction,
    MarketRuleVersion,
    UniverseMembership,
)
from app.models.symbol import Market
from app.services.backtest.ledger import (
    BacktestCheckpoint,
    BacktestRunRecord,
    BacktestRunStatus,
    DailyLedgerBatch,
    stable_checksum,
)


ModelT = TypeVar("ModelT", BenchmarkBar, CorporateAction, MarketRuleVersion, UniverseMembership)


class BacktestPersistenceConflict(RuntimeError):
    """A durable identity or state transition conflicts with stored data."""


class BacktestRepository:
    """Point-in-time inputs plus owner-scoped durable backtest ledgers."""

    UNIVERSE_COLLECTION = "historical_universe_memberships"
    CORPORATE_ACTION_COLLECTION = "corporate_actions"
    BENCHMARK_COLLECTION = "benchmark_daily_bars"
    MARKET_RULE_COLLECTION = "market_rule_versions"
    RUNS_COLLECTION = "backtest_runs"
    ORDERS_COLLECTION = "backtest_orders"
    TRADES_COLLECTION = "backtest_trades"
    POSITIONS_COLLECTION = "backtest_positions_daily"
    EQUITY_COLLECTION = "backtest_equity_daily"
    EVENTS_COLLECTION = "backtest_events"
    CHECKPOINTS_COLLECTION = "backtest_checkpoints"

    def __init__(self, db=None):
        self._db = db
        self._indexes_ready = False
        self._index_lock = asyncio.Lock()

    def get_db(self):
        return self._db if self._db is not None else get_mongo_db()

    async def ensure_indexes(self) -> None:
        if self._indexes_ready:
            return
        async with self._index_lock:
            if self._indexes_ready:
                return
            await self.get_db()[self.UNIVERSE_COLLECTION].create_index(
                [
                    ("universe_id", ASCENDING),
                    ("market", ASCENDING),
                    ("symbol", ASCENDING),
                    ("effective_from", ASCENDING),
                    ("source_version", ASCENDING),
                ],
                unique=True,
                name="historical_universe_identity",
            )
            await self.get_db()[self.UNIVERSE_COLLECTION].create_index(
                [
                    ("universe_id", ASCENDING),
                    ("market", ASCENDING),
                    ("effective_from", ASCENDING),
                    ("effective_to", ASCENDING),
                    ("known_at", ASCENDING),
                ],
                name="historical_universe_point_in_time",
            )
            await self.get_db()[self.CORPORATE_ACTION_COLLECTION].create_index(
                [("action_id", ASCENDING)], unique=True, name="corporate_action_id"
            )
            await self.get_db()[self.CORPORATE_ACTION_COLLECTION].create_index(
                [
                    ("market", ASCENDING),
                    ("symbol", ASCENDING),
                    ("ex_date", ASCENDING),
                    ("announced_at", ASCENDING),
                    ("ingested_at", ASCENDING),
                ],
                name="corporate_action_point_in_time",
            )
            await self.get_db()[self.BENCHMARK_COLLECTION].create_index(
                [
                    ("benchmark_id", ASCENDING),
                    ("trade_date", ASCENDING),
                    ("source_version", ASCENDING),
                ],
                unique=True,
                name="benchmark_trade_date_version",
            )
            await self.get_db()[self.MARKET_RULE_COLLECTION].create_index(
                [("rule_version_id", ASCENDING)], unique=True, name="market_rule_version_id"
            )
            await self.get_db()[self.MARKET_RULE_COLLECTION].create_index(
                [
                    ("market", ASCENDING),
                    ("effective_from", DESCENDING),
                    ("effective_to", ASCENDING),
                    ("published_at", DESCENDING),
                ],
                name="market_rule_effective_date",
            )
            await self.get_db()[self.RUNS_COLLECTION].create_index(
                [("run_id", ASCENDING)], unique=True, name="backtest_run_id"
            )
            await self.get_db()[self.RUNS_COLLECTION].create_index(
                [("user_id", ASCENDING), ("created_at", DESCENDING)],
                name="backtest_owner_created",
            )
            await self.get_db()[self.ORDERS_COLLECTION].create_index(
                [
                    ("user_id", ASCENDING),
                    ("run_id", ASCENDING),
                    ("order_id", ASCENDING),
                ],
                unique=True,
                name="backtest_order_identity",
            )
            await self.get_db()[self.ORDERS_COLLECTION].create_index(
                [
                    ("user_id", ASCENDING),
                    ("run_id", ASCENDING),
                    ("status", ASCENDING),
                ],
                name="backtest_order_state_scan",
            )
            await self.get_db()[self.TRADES_COLLECTION].create_index(
                [
                    ("user_id", ASCENDING),
                    ("run_id", ASCENDING),
                    ("trade_id", ASCENDING),
                ],
                unique=True,
                name="backtest_trade_id",
            )
            await self.get_db()[self.TRADES_COLLECTION].create_index(
                [
                    ("user_id", ASCENDING),
                    ("run_id", ASCENDING),
                    ("symbol", ASCENDING),
                    ("trade_date", ASCENDING),
                ],
                name="backtest_trade_symbol_date",
            )
            await self.get_db()[self.POSITIONS_COLLECTION].create_index(
                [
                    ("user_id", ASCENDING),
                    ("run_id", ASCENDING),
                    ("trade_date", ASCENDING),
                    ("symbol", ASCENDING),
                ],
                unique=True,
                name="backtest_position_day_symbol",
            )
            await self.get_db()[self.POSITIONS_COLLECTION].create_index(
                [
                    ("user_id", ASCENDING),
                    ("run_id", ASCENDING),
                    ("symbol", ASCENDING),
                    ("trade_date", ASCENDING),
                ],
                name="backtest_position_symbol_date",
            )
            await self.get_db()[self.EQUITY_COLLECTION].create_index(
                [
                    ("user_id", ASCENDING),
                    ("run_id", ASCENDING),
                    ("trade_date", ASCENDING),
                ],
                unique=True,
                name="backtest_equity_day",
            )
            await self.get_db()[self.EVENTS_COLLECTION].create_index(
                [
                    ("user_id", ASCENDING),
                    ("run_id", ASCENDING),
                    ("event_id", ASCENDING),
                ],
                unique=True,
                name="backtest_event_id",
            )
            await self.get_db()[self.EVENTS_COLLECTION].create_index(
                [
                    ("user_id", ASCENDING),
                    ("run_id", ASCENDING),
                    ("trade_date", ASCENDING),
                    ("sequence", ASCENDING),
                ],
                unique=True,
                name="backtest_event_day_sequence",
            )
            await self.get_db()[self.CHECKPOINTS_COLLECTION].create_index(
                [
                    ("user_id", ASCENDING),
                    ("run_id", ASCENDING),
                    ("trade_date", ASCENDING),
                ],
                unique=True,
                name="backtest_checkpoint_day",
            )
            self._indexes_ready = True

    async def create_run(self, record: BacktestRunRecord) -> BacktestRunRecord:
        await self.ensure_indexes()
        collection = self.get_db()[self.RUNS_COLLECTION]
        key = {"run_id": record.run_id, "user_id": record.user_id}
        payload = record.model_dump(mode="json")
        await collection.update_one(key, {"$setOnInsert": payload}, upsert=True)
        document = await collection.find_one(key)
        if document is None:
            raise RuntimeError("backtest run upsert did not persist a document")
        existing = self._parse_run(document)
        immutable = ("task_id", "strategy_version_id", "market", "request")
        for field in immutable:
            if getattr(existing, field) != getattr(record, field):
                raise BacktestPersistenceConflict(
                    f"run_id already exists with different {field}"
                )
        return existing

    async def get_run(self, run_id: str, *, user_id: str) -> BacktestRunRecord | None:
        document = await self.get_db()[self.RUNS_COLLECTION].find_one(
            {"run_id": run_id, "user_id": user_id}
        )
        return None if document is None else self._parse_run(document)

    async def mark_run_running(
        self, run_id: str, *, user_id: str, task_id: str
    ) -> BacktestRunRecord:
        current = await self.get_run(run_id, user_id=user_id)
        if current is None:
            raise KeyError(f"unknown owner-scoped backtest run: {run_id}")
        if current.task_id != task_id:
            raise BacktestPersistenceConflict("run task_id differs from durable task")
        if current.status == BacktestRunStatus.RUNNING:
            return current
        if current.status != BacktestRunStatus.QUEUED:
            raise BacktestPersistenceConflict(
                f"run in {current.status.value} cannot start"
            )
        now = datetime.now(timezone.utc)
        document = await self.get_db()[self.RUNS_COLLECTION].find_one_and_update(
            {
                "run_id": run_id,
                "user_id": user_id,
                "status": BacktestRunStatus.QUEUED.value,
            },
            {
                "$set": {
                    "status": BacktestRunStatus.RUNNING.value,
                    "started_at": now.isoformat(),
                    "updated_at": now.isoformat(),
                    "error": None,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if document is None:
            concurrent = await self.get_run(run_id, user_id=user_id)
            if concurrent is not None and concurrent.status == BacktestRunStatus.RUNNING:
                return concurrent
            raise BacktestPersistenceConflict("run changed while starting")
        return self._parse_run(document)

    async def commit_day(self, batch: DailyLedgerBatch) -> None:
        await self.ensure_indexes()
        run = await self.get_run(batch.run_id, user_id=batch.user_id)
        if run is None or run.status != BacktestRunStatus.RUNNING:
            raise BacktestPersistenceConflict("daily ledger requires a running owned run")
        for order in batch.orders:
            payload = order.model_dump(mode="json")
            await self.get_db()[self.ORDERS_COLLECTION].update_one(
                {
                    "run_id": order.run_id,
                    "user_id": order.user_id,
                    "order_id": order.order_id,
                },
                {"$set": payload},
                upsert=True,
            )
        for trade in batch.trades:
            await self._upsert_immutable(
                self.TRADES_COLLECTION,
                {
                    "run_id": trade.run_id,
                    "user_id": trade.user_id,
                    "trade_id": trade.trade_id,
                },
                trade.model_dump(mode="json"),
            )
        for position in batch.positions:
            await self._upsert_immutable(
                self.POSITIONS_COLLECTION,
                {
                    "run_id": position.run_id,
                    "user_id": position.user_id,
                    "trade_date": position.trade_date.isoformat(),
                    "symbol": position.symbol,
                },
                position.model_dump(mode="json"),
            )
        await self._upsert_immutable(
            self.EQUITY_COLLECTION,
            {
                "run_id": batch.run_id,
                "user_id": batch.user_id,
                "trade_date": batch.trade_date.isoformat(),
            },
            batch.equity.model_dump(mode="json"),
        )
        for event in batch.events:
            await self._upsert_immutable(
                self.EVENTS_COLLECTION,
                {
                    "run_id": event.run_id,
                    "user_id": event.user_id,
                    "event_id": event.event_id,
                },
                event.model_dump(mode="json"),
            )
        # The checkpoint is deliberately last: it is the logical day commit.
        await self._upsert_immutable(
            self.CHECKPOINTS_COLLECTION,
            {
                "run_id": batch.run_id,
                "user_id": batch.user_id,
                "trade_date": batch.trade_date.isoformat(),
            },
            batch.checkpoint.model_dump(mode="json"),
        )
        now = datetime.now(timezone.utc).isoformat()
        await self.get_db()[self.RUNS_COLLECTION].update_one(
            {"run_id": batch.run_id, "user_id": batch.user_id},
            {
                "$set": {
                    "last_completed_trade_date": batch.trade_date.isoformat(),
                    "updated_at": now,
                }
            },
        )

    async def latest_checkpoint(
        self, run_id: str, *, user_id: str
    ) -> BacktestCheckpoint | None:
        cursor = self.get_db()[self.CHECKPOINTS_COLLECTION].find(
            {"run_id": run_id, "user_id": user_id}
        ).sort([("trade_date", DESCENDING)])
        documents = await cursor.to_list(length=1)
        if not documents:
            return None
        payload = dict(documents[0])
        payload.pop("_id", None)
        payload.pop("record_checksum", None)
        return BacktestCheckpoint.model_validate(payload)

    async def mark_run_succeeded(
        self, run_id: str, *, user_id: str, summary: dict[str, Any]
    ) -> BacktestRunRecord:
        return await self._mark_terminal(
            run_id,
            user_id=user_id,
            status=BacktestRunStatus.SUCCEEDED,
            summary=summary,
        )

    async def mark_run_cancelled(
        self, run_id: str, *, user_id: str
    ) -> BacktestRunRecord:
        return await self._mark_terminal(
            run_id, user_id=user_id, status=BacktestRunStatus.CANCELLED
        )

    async def mark_run_failed(
        self, run_id: str, *, user_id: str, error: dict[str, Any]
    ) -> BacktestRunRecord:
        return await self._mark_terminal(
            run_id,
            user_id=user_id,
            status=BacktestRunStatus.FAILED,
            error=error,
        )

    async def _mark_terminal(
        self,
        run_id: str,
        *,
        user_id: str,
        status: BacktestRunStatus,
        summary: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> BacktestRunRecord:
        if status not in {
            BacktestRunStatus.SUCCEEDED,
            BacktestRunStatus.CANCELLED,
            BacktestRunStatus.FAILED,
        }:
            raise ValueError("terminal status required")
        current = await self.get_run(run_id, user_id=user_id)
        if current is None:
            raise KeyError(f"unknown owner-scoped backtest run: {run_id}")
        if current.status == status:
            return current
        allowed_source = (
            BacktestRunStatus.QUEUED
            if status == BacktestRunStatus.CANCELLED
            and current.status == BacktestRunStatus.QUEUED
            else BacktestRunStatus.RUNNING
        )
        if current.status != allowed_source:
            raise BacktestPersistenceConflict(
                f"run in {current.status.value} cannot become {status.value}"
            )
        now = datetime.now(timezone.utc).isoformat()
        values: dict[str, Any] = {
            "status": status.value,
            "finished_at": now,
            "updated_at": now,
        }
        if summary is not None:
            values["summary"] = summary
        if error is not None:
            values["error"] = error
        document = await self.get_db()[self.RUNS_COLLECTION].find_one_and_update(
            {
                "run_id": run_id,
                "user_id": user_id,
                "status": allowed_source.value,
            },
            {"$set": values},
            return_document=ReturnDocument.AFTER,
        )
        if document is None:
            current = await self.get_run(run_id, user_id=user_id)
            if current is not None and current.status == status:
                return current
            raise BacktestPersistenceConflict("run changed before terminal transition")
        return self._parse_run(document)

    async def _upsert_immutable(
        self,
        collection_name: str,
        key: dict[str, Any],
        payload: dict[str, Any],
    ) -> None:
        checksum = stable_checksum(payload)
        document = {**payload, "record_checksum": checksum}
        collection = self.get_db()[collection_name]
        await collection.update_one(key, {"$setOnInsert": document}, upsert=True)
        existing = await collection.find_one(key)
        if existing is None or existing.get("record_checksum") != checksum:
            raise BacktestPersistenceConflict(
                f"immutable {collection_name} identity contains different content"
            )

    @staticmethod
    def _parse_run(document: dict[str, Any]) -> BacktestRunRecord:
        payload = dict(document)
        payload.pop("_id", None)
        return BacktestRunRecord.model_validate(payload)

    async def list_universe_memberships(
        self,
        universe_id: str,
        market: Market | str,
        *,
        trade_date: date,
        as_of: datetime,
    ) -> tuple[UniverseMembership, ...]:
        documents = await self._find_all(
            self.UNIVERSE_COLLECTION,
            {"universe_id": universe_id, "market": Market(market).value},
        )
        memberships = self._parse_many(UniverseMembership, documents)
        applicable = [item for item in memberships if item.applies_on(trade_date, as_of)]
        # Corrected records may overlap an older version.  Select the latest
        # version known at the cutoff, never whichever document Mongo returns.
        selected: dict[str, UniverseMembership] = {}
        for item in applicable:
            current = selected.get(item.symbol)
            if current is None or (item.known_at, item.source_version) > (
                current.known_at,
                current.source_version,
            ):
                selected[item.symbol] = item
        return tuple(selected[symbol] for symbol in sorted(selected))

    async def list_corporate_actions(
        self,
        market: Market | str,
        *,
        symbols: Iterable[str],
        start_date: date,
        end_date: date,
        as_of: datetime,
    ) -> tuple[CorporateAction, ...]:
        symbol_set = set(symbols)
        documents = await self._find_all(
            self.CORPORATE_ACTION_COLLECTION, {"market": Market(market).value}
        )
        actions = self._parse_many(CorporateAction, documents)
        result = [
            item
            for item in actions
            if item.symbol in symbol_set
            and start_date <= item.ex_date <= end_date
            and item.visible_at <= as_of
        ]
        return tuple(sorted(result, key=lambda item: (item.ex_date, item.symbol, item.action_id)))

    async def get_benchmark_bar(
        self,
        benchmark_id: str,
        market: Market | str,
        *,
        trade_date: date,
        as_of: datetime,
    ) -> BenchmarkBar | None:
        documents = await self._find_all(
            self.BENCHMARK_COLLECTION,
            {"benchmark_id": benchmark_id, "market": Market(market).value},
        )
        candidates = [
            item
            for item in self._parse_many(BenchmarkBar, documents)
            if item.trade_date == trade_date and item.ingested_at <= as_of
        ]
        return max(candidates, key=lambda item: (item.ingested_at, item.source_version), default=None)

    async def get_market_rule(
        self,
        market: Market | str,
        *,
        trade_date: date,
        as_of: datetime,
    ) -> MarketRuleVersion | None:
        documents = await self._find_all(
            self.MARKET_RULE_COLLECTION, {"market": Market(market).value}
        )
        candidates = [
            item
            for item in self._parse_many(MarketRuleVersion, documents)
            if item.applies_on(trade_date, as_of)
        ]
        return max(
            candidates,
            key=lambda item: (item.effective_from, item.published_at, item.rule_version_id),
            default=None,
        )

    async def _find_all(self, collection_name: str, query: dict[str, Any]) -> list[dict[str, Any]]:
        cursor = self.get_db()[collection_name].find(query)
        if hasattr(cursor, "to_list"):
            return list(await cursor.to_list(length=None))
        if hasattr(cursor, "__aiter__"):
            return [item async for item in cursor]
        result = await cursor if hasattr(cursor, "__await__") else cursor
        return list(result)

    @staticmethod
    def _parse_many(model: type[ModelT], documents: Iterable[dict[str, Any]]) -> list[ModelT]:
        parsed: list[ModelT] = []
        for document in documents:
            payload = dict(document)
            payload.pop("_id", None)
            parsed.append(model.model_validate(payload))
        return parsed


# J30 callers may use the narrower name to make clear that this repository
# currently exposes reference inputs only.  Later backtest-run persistence can
# extend ``BacktestRepository`` without breaking those callers.
BacktestInputRepository = BacktestRepository
