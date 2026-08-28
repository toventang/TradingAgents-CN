"""Idempotent MongoDB mirror for static factor definitions."""

from __future__ import annotations

from typing import Any

from app.core.database import get_mongo_db
from app.models.factor import FactorStatus
from app.services.factors.registry import FactorRegistry, global_factor_registry


class FactorDefinitionMirrorConflict(RuntimeError):
    """The same published factor version has different static content."""


class FactorRepository:
    COLLECTION = "factor_definitions"

    def __init__(self, db=None, registry: FactorRegistry | None = None):
        self._db = db
        self._registry = registry or global_factor_registry

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


_UNKNOWN_RESULT = object()
