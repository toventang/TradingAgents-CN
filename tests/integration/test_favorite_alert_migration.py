from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.migrations.migrate_favorite_alerts import run, verify
from app.repositories.alert_repository import AlertRepository
from app.services.favorites_service import (
    FavoriteAlertRuleSynchronizer,
    FavoritesService,
)
from tests.unit.alerts.test_rule_validator import (
    AlertFakeCollection,
    AlertFakeDatabase,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]
NOW = datetime(2026, 8, 17, tzinfo=timezone.utc)


class FavoriteCursor:
    def __init__(self, documents):
        self.documents = [deepcopy(item) for item in documents]
        self.maximum = None

    def sort(self, field, direction):
        self.documents.sort(key=lambda item: item.get(field), reverse=direction < 0)
        return self

    def limit(self, count):
        self.maximum = count
        return self

    async def to_list(self, length):
        maximum = self.maximum if self.maximum is not None else length
        return deepcopy(self.documents[:maximum])


class FavoriteCollection(AlertFakeCollection):
    def find(self, query, projection=None):
        documents = self.documents
        if "user_id" in query and isinstance(query["user_id"], dict):
            after = query["user_id"].get("$gt")
            documents = [item for item in documents if item.get("user_id") > after]
        elif query.get("user_id") is not None:
            documents = [
                item for item in documents if item.get("user_id") == query["user_id"]
            ]
        return FavoriteCursor(documents)

    async def find_one(self, query, projection=None, sort=None):
        for document in self.documents:
            if query.get("user_id") != document.get("user_id"):
                continue
            symbol = query.get("favorites.stock_code")
            if symbol is not None and not any(
                item.get("stock_code") == symbol
                for item in document.get("favorites", [])
            ):
                continue
            return deepcopy(document)
        return None

    async def update_one(self, query, update, upsert=False):
        for document in self.documents:
            if document.get("user_id") != query.get("user_id"):
                continue
            symbol = query.get("favorites.stock_code")
            favorite = next(
                (
                    item
                    for item in document.get("favorites", [])
                    if symbol is None or item.get("stock_code") == symbol
                ),
                None,
            )
            if symbol is not None and favorite is None:
                continue
            modified = False
            for key, value in update.get("$set", {}).items():
                if key.startswith("favorites.$."):
                    assert favorite is not None
                    favorite[key.removeprefix("favorites.$.")] = deepcopy(value)
                else:
                    document[key] = deepcopy(value)
                modified = True
            if "$pull" in update:
                target = update["$pull"].get("favorites", {})
                before = len(document.get("favorites", []))
                document["favorites"] = [
                    item
                    for item in document.get("favorites", [])
                    if item.get("stock_code") != target.get("stock_code")
                ]
                modified = modified or len(document["favorites"]) != before
            return SimpleNamespace(
                matched_count=1,
                modified_count=int(modified),
                upserted_id=None,
            )
        if upsert:
            document = deepcopy(update.get("$setOnInsert", {}))
            document.update(deepcopy(update.get("$set", {})))
            document.setdefault("user_id", query.get("user_id"))
            self.documents.append(document)
            return SimpleNamespace(
                matched_count=0,
                modified_count=0,
                upserted_id=len(self.documents),
            )
        return SimpleNamespace(matched_count=0, modified_count=0, upserted_id=None)


class MigrationDatabase(AlertFakeDatabase):
    def __init__(self, favorites):
        super().__init__()
        collection = FavoriteCollection("user_favorites")
        collection.documents = deepcopy(favorites)
        self.collections["user_favorites"] = collection


def favorite(symbol, *, high=None, low=None, market="A股"):
    return {
        "stock_code": symbol,
        "stock_name": symbol,
        "market": market,
        "added_at": NOW,
        "alert_price_high": high,
        "alert_price_low": low,
    }


async def test_migration_is_batchable_resumable_and_idempotent():
    database = MigrationDatabase(
        [
            {
                "user_id": "user-a",
                "favorites": [favorite("600000", high=12, low=8)],
            },
            {
                "user_id": "user-b",
                "favorites": [favorite("000001", high=15)],
            },
        ]
    )

    first = await run(database, batch_size=1)
    assert first.scanned_users == 1
    assert first.created_rules == 2
    assert first.next_user_id == "user-a"
    assert first.has_more is True
    assert first.failures == ()

    favorite_a = database["user_favorites"].documents[0]["favorites"][0]
    assert set(favorite_a["alert_rule_ids"]) == {
        "alert_price_high",
        "alert_price_low",
    }
    rules = database["alert_rules"].documents
    assert len(rules) == 2
    assert {item["user_id"] for item in rules} == {"user-a"}
    mappings = database["favorite_alert_migrations"].documents
    assert len(mappings) == 2
    assert all(item["source"] == "legacy_favorite" for item in mappings)

    replay = await run(database, batch_size=1)
    assert replay.created_rules == 0
    assert replay.updated_rules == 0
    assert len(database["alert_rules"].documents) == 2
    assert len(database["alert_rule_versions"].documents) == 2

    second = await run(database, batch_size=1, after_user_id=first.next_user_id)
    assert second.created_rules == 1
    assert second.next_user_id == "user-b"
    assert second.has_more is False
    assert len(database["alert_rules"].documents) == 3
    assert {item["user_id"] for item in database["alert_rules"].documents} == {
        "user-a",
        "user-b",
    }
    verification = await verify(database)
    assert verification.checked_mappings == 3
    assert verification.valid is True


async def test_threshold_updates_version_rule_and_null_soft_deletes_it():
    database = MigrationDatabase(
        [{"user_id": "user-a", "favorites": [favorite("600000", high=12)]}]
    )
    synchronizer = FavoriteAlertRuleSynchronizer(database)
    service = FavoritesService(database, alert_synchronizer=synchronizer)
    await run(database)
    rule_id = database["user_favorites"].documents[0]["favorites"][0][
        "alert_price_high_rule_id"
    ]

    # The existing router passes None for omitted threshold fields. A tag-only
    # update must preserve the migrated threshold and rule.
    assert await service.update_favorite(
        "user-a",
        "600000",
        tags=["bank"],
        alert_price_high=None,
        alert_price_low=None,
    )
    unchanged = await AlertRepository(database).get_rule(rule_id, user_id="user-a")
    assert unchanged is not None
    assert unchanged.enabled is True
    assert unchanged.version == 1

    assert await service.update_favorite(
        "user-a",
        "600000",
        alert_price_high=13,
    )
    updated = await AlertRepository(database).get_rule(rule_id, user_id="user-a")
    assert updated is not None
    assert updated.version == 2
    assert updated.trigger.condition.right.value == Decimal("13")

    assert await service.update_favorite(
        "user-a",
        "600000",
        alert_price_high=None,
    )
    disabled = await AlertRepository(database).get_rule(rule_id, user_id="user-a")
    assert disabled is not None
    assert disabled.enabled is False
    assert disabled.version == 3
    mapping = await database["favorite_alert_migrations"].find_one(
        {"user_id": "user-a"}
    )
    assert mapping["status"] == "soft_deleted"
    assert mapping["threshold"] is None


async def test_invalid_threshold_does_not_partially_create_rules():
    database = MigrationDatabase([])
    synchronizer = FavoriteAlertRuleSynchronizer(database)

    with pytest.raises(ValueError, match="positive finite"):
        await synchronizer.synchronize(
            "user-a",
            favorite("600000", high=12, low="NaN"),
        )

    assert database["alert_rules"].documents == []
    assert database["favorite_alert_migrations"].documents == []
