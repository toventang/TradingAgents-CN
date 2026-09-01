"""Persistence boundary for point-in-time backtest reference inputs."""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from typing import Any, Iterable, TypeVar

from pymongo import ASCENDING, DESCENDING

from app.core.database import get_mongo_db
from app.models.backtest import (
    BenchmarkBar,
    CorporateAction,
    MarketRuleVersion,
    UniverseMembership,
)
from app.models.symbol import Market


ModelT = TypeVar("ModelT", BenchmarkBar, CorporateAction, MarketRuleVersion, UniverseMembership)


class BacktestRepository:
    """Read historical reference inputs without applying current-state filters."""

    UNIVERSE_COLLECTION = "historical_universe_memberships"
    CORPORATE_ACTION_COLLECTION = "corporate_actions"
    BENCHMARK_COLLECTION = "benchmark_daily_bars"
    MARKET_RULE_COLLECTION = "market_rule_versions"

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
            self._indexes_ready = True

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
