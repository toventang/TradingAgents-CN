"""J42: resumable migration from legacy favorite thresholds to alert rules."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.core.database import get_mongo_db
from app.repositories.alert_repository import AlertRepository
from app.services.favorites_service import (
    LEGACY_ALERT_SOURCE,
    FavoriteAlertRuleSynchronizer,
    FavoritesService,
    _rule_matches_threshold,
)


@dataclass(frozen=True)
class FavoriteAlertMigrationFailure:
    user_id: str
    stock_code: str | None
    error_code: str


@dataclass(frozen=True)
class FavoriteAlertMigrationResult:
    scanned_users: int
    scanned_favorites: int
    created_rules: int
    updated_rules: int
    soft_deleted_rules: int
    failures: tuple[FavoriteAlertMigrationFailure, ...]
    next_user_id: str | None
    has_more: bool


@dataclass(frozen=True)
class FavoriteAlertVerificationResult:
    checked_mappings: int
    errors: tuple[str, ...]
    next_migration_key: str | None
    has_more: bool

    @property
    def valid(self) -> bool:
        return not self.errors


async def run(
    db=None,
    *,
    batch_size: int = 500,
    after_user_id: str | None = None,
) -> FavoriteAlertMigrationResult:
    """Migrate one deterministic user batch; pass next_user_id to resume."""

    if batch_size < 1 or batch_size > 5000:
        raise ValueError("batch_size must be in 1..5000")
    database = db if db is not None else get_mongo_db()
    query = {"user_id": {"$gt": after_user_id}} if after_user_id else {}
    documents = await (
        database["user_favorites"]
        .find(query)
        .sort("user_id", 1)
        .limit(batch_size + 1)
        .to_list(length=batch_size + 1)
    )
    has_more = len(documents) > batch_size
    batch = documents[:batch_size]
    synchronizer = FavoriteAlertRuleSynchronizer(database)
    favorites_service = FavoritesService(
        database,
        alert_synchronizer=synchronizer,
    )
    scanned_favorites = created = updated = soft_deleted = 0
    failures: list[FavoriteAlertMigrationFailure] = []
    for document in batch:
        user_id = str(document.get("user_id") or "")
        for favorite in document.get("favorites") or []:
            scanned_favorites += 1
            try:
                result = await synchronizer.synchronize(user_id, favorite)
                await favorites_service._persist_rule_links(
                    user_id,
                    str(favorite.get("stock_code") or ""),
                    result.rule_ids,
                )
                created += result.created
                updated += result.updated
                soft_deleted += result.soft_deleted
            except (TypeError, ValueError) as exc:
                failures.append(
                    FavoriteAlertMigrationFailure(
                        user_id=user_id,
                        stock_code=(
                            str(favorite.get("stock_code"))
                            if favorite.get("stock_code") is not None
                            else None
                        ),
                        error_code=type(exc).__name__,
                    )
                )
    next_user_id = str(batch[-1]["user_id"]) if batch else after_user_id
    return FavoriteAlertMigrationResult(
        scanned_users=len(batch),
        scanned_favorites=scanned_favorites,
        created_rules=created,
        updated_rules=updated,
        soft_deleted_rules=soft_deleted,
        failures=tuple(failures),
        next_user_id=next_user_id,
        has_more=has_more,
    )


async def verify(
    db=None,
    *,
    batch_size: int = 1000,
    after_migration_key: str | None = None,
) -> FavoriteAlertVerificationResult:
    """Verify a resumable mapping batch against owner-scoped current rules."""

    if batch_size < 1 or batch_size > 5000:
        raise ValueError("batch_size must be in 1..5000")
    database = db if db is not None else get_mongo_db()
    query = (
        {"migration_key": {"$gt": after_migration_key}}
        if after_migration_key
        else {}
    )
    documents = await (
        database[FavoriteAlertRuleSynchronizer.MAPPINGS_COLLECTION]
        .find(query)
        .sort([("migration_key", 1)])
        .limit(batch_size + 1)
        .to_list(length=batch_size + 1)
    )
    has_more = len(documents) > batch_size
    batch = documents[:batch_size]
    alerts = AlertRepository(database)
    errors: list[str] = []
    for mapping in batch:
        key = str(mapping.get("migration_key") or "")
        user_id = str(mapping.get("user_id") or "")
        rule_id = str(mapping.get("rule_id") or "")
        field = str(mapping.get("legacy_field") or "")
        expected_key = f"{user_id}:{mapping.get('symbol')}:{field}"
        if key != expected_key:
            errors.append(f"{key}:MIGRATION_KEY_INVALID")
            continue
        if mapping.get("source") != LEGACY_ALERT_SOURCE:
            errors.append(f"{key}:SOURCE_INVALID")
            continue
        rule = await alerts.get_rule(rule_id, user_id=user_id)
        if rule is None:
            errors.append(f"{key}:RULE_MISSING")
            continue
        if mapping.get("status") == "soft_deleted":
            if mapping.get("threshold") is not None:
                errors.append(f"{key}:SOFT_DELETE_THRESHOLD_PRESENT")
            if rule.enabled:
                errors.append(f"{key}:RULE_NOT_SOFT_DELETED")
            continue
        try:
            threshold = Decimal(str(mapping.get("threshold")))
        except (InvalidOperation, ValueError):
            errors.append(f"{key}:THRESHOLD_INVALID")
            continue
        if not _rule_matches_threshold(rule, field, threshold):
            errors.append(f"{key}:RULE_MISMATCH")
    next_key = str(batch[-1]["migration_key"]) if batch else after_migration_key
    return FavoriteAlertVerificationResult(
        checked_mappings=len(batch),
        errors=tuple(errors),
        next_migration_key=next_key,
        has_more=has_more,
    )
