from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.models.strategy import (
    StrategySignal,
    UniverseMember,
    UniverseSnapshot,
)
from app.models.symbol import Market
from app.repositories.strategy_repository import (
    StrategyImmutableConflict,
    StrategyNotFound,
    StrategyRepository,
)
from tests.strategy_fakes import FakeDatabase


pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


AS_OF = datetime(2025, 6, 4, 7, 0, tzinfo=timezone.utc)


def snapshot(**updates) -> UniverseSnapshot:
    payload = {
        "universe_snapshot_id": "universe-20250603-cn",
        "user_id": "alice",
        "market": Market.CN,
        "trade_date": date(2025, 6, 3),
        "as_of": AS_OF,
        "members": (
            UniverseMember(market=Market.CN, symbol="600000"),
            UniverseMember(market=Market.CN, symbol="000001"),
        ),
        "source_versions": {"security_master": "2025-06-03"},
        "selection_definition": {"index": "CSI300", "as_of_policy": "published"},
        "created_at": AS_OF,
    }
    payload.update(updates)
    return UniverseSnapshot(**payload)


def signal(**updates) -> StrategySignal:
    payload = {
        "user_id": "alice",
        "strategy_version_id": "strategy-version-1",
        "universe_snapshot_id": "universe-20250603-cn",
        "factor_snapshot_id": "factor-snapshot-1",
        "market": Market.CN,
        "symbol": "600000",
        "signal_date": date(2025, 6, 3),
        "signal_type": "candidate",
        "score": 0.82,
        "rank": 1,
        "reason_codes": ("QUALITY_PASS", "TOP_RANK"),
        "input_contributions": {"quality": 0.52, "momentum": 0.30},
        "as_of": AS_OF,
        "created_at": AS_OF,
    }
    payload.update(updates)
    return StrategySignal(**payload)


async def test_indexes_owner_scoping_and_immutable_universe_snapshot_uniqueness():
    database = FakeDatabase()
    repository = StrategyRepository(database)
    await repository.ensure_indexes()

    index_names = {
        options["name"]
        for collection in database.collections.values()
        for _, options in collection.indexes
    }
    assert {
        "strategy_id_unique",
        "strategy_owner_updated",
        "strategy_version_number_unique",
        "strategy_version_id_unique",
        "strategy_version_owner_state",
        "universe_snapshot_id_unique",
        "universe_market_date",
        "strategy_signal_identity_unique",
        "strategy_signal_owner_version_date",
    }.issubset(index_names)

    original = snapshot()
    saved = await repository.save_universe_snapshot(original)
    retried = await repository.save_universe_snapshot(snapshot())
    assert saved == retried
    assert len(database[repository.UNIVERSES_COLLECTION].documents) == 1
    assert (
        await repository.get_universe_snapshot(
            original.universe_snapshot_id, user_id="bob"
        )
        is None
    )
    assert await repository.list_universe_snapshots(user_id="bob") == ()

    with pytest.raises(StrategyImmutableConflict, match="different immutable content"):
        await repository.save_universe_snapshot(
            snapshot(
                members=(UniverseMember(market=Market.CN, symbol="600000"),),
            )
        )
    with pytest.raises(StrategyImmutableConflict, match="different immutable content"):
        await repository.save_universe_snapshot(snapshot(user_id="bob"))


async def test_signal_identity_is_idempotent_immutable_and_owner_scoped():
    database = FakeDatabase()
    repository = StrategyRepository(database)
    await repository.ensure_indexes()
    database[repository.VERSIONS_COLLECTION].documents.append(
        {
            "strategy_version_id": "strategy-version-1",
            "user_id": "alice",
            "status": "published",
            "market": "CN",
        }
    )
    await repository.save_universe_snapshot(snapshot())
    database["factor_snapshots"].documents.append(
        {
            "snapshot_id": "factor-snapshot-1",
            "user_id": "alice",
            "status": "ready",
            "market": "CN",
        }
    )

    first = signal(signal_id="signal-attempt-1")
    stored = await repository.save_signal(first)
    retried = await repository.save_signal(signal(signal_id="signal-attempt-2"))
    assert retried.signal_id == stored.signal_id
    assert retried.checksum == stored.checksum
    assert len(database[repository.SIGNALS_COLLECTION].documents) == 1

    with pytest.raises(StrategyImmutableConflict, match="different immutable content"):
        await repository.save_signal(signal(score=0.91))
    with pytest.raises(StrategyNotFound, match="not owner-visible"):
        await repository.save_signal(signal(user_id="bob"))

    assert await repository.list_signals(
        user_id="bob", strategy_version_id=first.strategy_version_id
    ) == ()
    alice_signals = await repository.list_signals(
        user_id="alice", strategy_version_id=first.strategy_version_id
    )
    assert len(alice_signals) == 1
    assert alice_signals[0].score == pytest.approx(0.82)
