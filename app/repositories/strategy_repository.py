"""MongoDB persistence for immutable strategy versions and derived records."""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from typing import Iterable

from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.core.database import get_mongo_db
from app.models.analysis import (
    AnalysisProfile,
    AnalysisProfileVersion,
    AnalysisProfileVersionStatus,
)
from app.models.strategy import (
    SYSTEM_USER_ID,
    Strategy,
    StrategySignal,
    StrategyVersion,
    StrategyVersionStatus,
    StrategyVisibility,
    UniverseSnapshot,
)


class StrategyConflict(RuntimeError):
    """A strategy identity, version, or optimistic update conflicts."""


class StrategyNotFound(LookupError):
    """An owner-scoped strategy resource does not exist."""


class StrategyImmutableConflict(StrategyConflict):
    """An immutable resource already exists with different content."""


class StrategyRepository:
    STRATEGIES_COLLECTION = "strategies"
    VERSIONS_COLLECTION = "strategy_versions"
    UNIVERSES_COLLECTION = "universe_snapshots"
    SIGNALS_COLLECTION = "strategy_signals"
    ANALYSIS_PROFILES_COLLECTION = "analysis_profiles"
    ANALYSIS_PROFILE_VERSIONS_COLLECTION = "analysis_profile_versions"

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
            strategies = self.get_db()[self.STRATEGIES_COLLECTION]
            versions = self.get_db()[self.VERSIONS_COLLECTION]
            universes = self.get_db()[self.UNIVERSES_COLLECTION]
            signals = self.get_db()[self.SIGNALS_COLLECTION]
            analysis_profiles = self.get_db()[self.ANALYSIS_PROFILES_COLLECTION]
            analysis_profile_versions = self.get_db()[
                self.ANALYSIS_PROFILE_VERSIONS_COLLECTION
            ]

            await strategies.create_index(
                [("strategy_id", ASCENDING)],
                unique=True,
                name="strategy_id_unique",
            )
            await strategies.create_index(
                [("user_id", ASCENDING), ("updated_at", DESCENDING)],
                name="strategy_owner_updated",
            )
            await strategies.create_index(
                [
                    ("user_id", ASCENDING),
                    ("archived_at", ASCENDING),
                    ("updated_at", DESCENDING),
                ],
                name="strategy_owner_archive_updated",
            )

            await versions.create_index(
                [("strategy_id", ASCENDING), ("version", ASCENDING)],
                unique=True,
                name="strategy_version_number_unique",
            )
            await versions.create_index(
                [("strategy_version_id", ASCENDING)],
                unique=True,
                name="strategy_version_id_unique",
            )
            await versions.create_index(
                [("user_id", ASCENDING), ("status", ASCENDING)],
                name="strategy_version_owner_state",
            )

            await universes.create_index(
                [("universe_snapshot_id", ASCENDING)],
                unique=True,
                name="universe_snapshot_id_unique",
            )
            await universes.create_index(
                [
                    ("user_id", ASCENDING),
                    ("market", ASCENDING),
                    ("trade_date", DESCENDING),
                ],
                name="universe_owner_market_date",
            )
            await universes.create_index(
                [("market", ASCENDING), ("trade_date", DESCENDING)],
                name="universe_market_date",
            )

            await signals.create_index(
                [
                    ("strategy_version_id", ASCENDING),
                    ("market", ASCENDING),
                    ("symbol", ASCENDING),
                    ("signal_date", ASCENDING),
                    ("signal_type", ASCENDING),
                ],
                unique=True,
                name="strategy_signal_identity_unique",
            )
            await signals.create_index(
                [
                    ("user_id", ASCENDING),
                    ("strategy_version_id", ASCENDING),
                    ("signal_date", DESCENDING),
                ],
                name="strategy_signal_owner_version_date",
            )
            await signals.create_index(
                [
                    ("market", ASCENDING),
                    ("symbol", ASCENDING),
                    ("signal_date", DESCENDING),
                ],
                name="strategy_signal_symbol_date",
            )
            await analysis_profiles.create_index(
                [("profile_id", ASCENDING)],
                unique=True,
                name="analysis_profile_id_unique",
            )
            await analysis_profiles.create_index(
                [("user_id", ASCENDING), ("updated_at", DESCENDING)],
                name="analysis_profile_owner_updated",
            )
            await analysis_profile_versions.create_index(
                [("profile_id", ASCENDING), ("version", ASCENDING)],
                unique=True,
                name="analysis_profile_version_number_unique",
            )
            await analysis_profile_versions.create_index(
                [("profile_version_id", ASCENDING)],
                unique=True,
                name="analysis_profile_version_id_unique",
            )
            await analysis_profile_versions.create_index(
                [("user_id", ASCENDING), ("status", ASCENDING)],
                name="analysis_profile_version_owner_state",
            )
            self._indexes_ready = True

    async def create_strategy(
        self, strategy: Strategy, initial_version: StrategyVersion
    ) -> tuple[Strategy, StrategyVersion]:
        """Create a strategy and its first draft without exposing an empty header."""

        await self.ensure_indexes()
        self._validate_initial_pair(strategy, initial_version)
        strategies = self.get_db()[self.STRATEGIES_COLLECTION]
        versions = self.get_db()[self.VERSIONS_COLLECTION]
        try:
            await strategies.insert_one(strategy.model_dump(mode="json"))
        except DuplicateKeyError as exc:
            raise StrategyConflict("strategy_id already exists") from exc
        try:
            await versions.insert_one(initial_version.model_dump(mode="json"))
        except Exception as exc:
            await strategies.delete_one(
                {"strategy_id": strategy.strategy_id, "user_id": strategy.user_id}
            )
            if not isinstance(exc, DuplicateKeyError):
                raise
            raise StrategyConflict("initial strategy version already exists") from exc
        return strategy, initial_version

    async def get_strategy(
        self,
        strategy_id: str,
        *,
        user_id: str,
        include_archived: bool = False,
        include_readonly: bool = True,
    ) -> Strategy | None:
        query = {"strategy_id": strategy_id, "user_id": user_id}
        if not include_archived:
            query["archived_at"] = None
        collection = self.get_db()[self.STRATEGIES_COLLECTION]
        document = await collection.find_one(query)
        if document is None and include_readonly:
            for visibility in (
                StrategyVisibility.SYSTEM.value,
                StrategyVisibility.SHARED_READONLY.value,
            ):
                readonly_query = {
                    "strategy_id": strategy_id,
                    "visibility": visibility,
                }
                if not include_archived:
                    readonly_query["archived_at"] = None
                document = await collection.find_one(readonly_query)
                if document is not None:
                    break
        return None if document is None else _parse_model(Strategy, document)

    async def list_strategies(
        self,
        *,
        user_id: str,
        include_archived: bool = False,
        limit: int = 100,
    ) -> tuple[Strategy, ...]:
        query: dict[str, object] = {"user_id": user_id}
        if not include_archived:
            query["archived_at"] = None
        cursor = self.get_db()[self.STRATEGIES_COLLECTION].find(query).sort(
            [("updated_at", DESCENDING), ("strategy_id", ASCENDING)]
        )
        documents = await cursor.to_list(length=limit)
        return tuple(_parse_model(Strategy, item) for item in documents)

    async def get_version(
        self,
        strategy_version_id: str,
        *,
        user_id: str,
        include_system: bool = True,
    ) -> StrategyVersion | None:
        collection = self.get_db()[self.VERSIONS_COLLECTION]
        document = await collection.find_one(
            {"strategy_version_id": strategy_version_id, "user_id": user_id}
        )
        if document is None and include_system:
            document = await collection.find_one(
                {"strategy_version_id": strategy_version_id, "user_id": SYSTEM_USER_ID}
            )
        return None if document is None else _parse_model(StrategyVersion, document)

    async def get_owned_version(
        self, strategy_version_id: str, *, user_id: str
    ) -> StrategyVersion | None:
        return await self.get_version(
            strategy_version_id, user_id=user_id, include_system=False
        )

    async def get_version_number(
        self, strategy_id: str, version: int, *, user_id: str
    ) -> StrategyVersion | None:
        document = await self.get_db()[self.VERSIONS_COLLECTION].find_one(
            {"strategy_id": strategy_id, "version": version, "user_id": user_id}
        )
        return None if document is None else _parse_model(StrategyVersion, document)

    async def list_versions(
        self, strategy_id: str, *, user_id: str
    ) -> tuple[StrategyVersion, ...]:
        cursor = self.get_db()[self.VERSIONS_COLLECTION].find(
            {"strategy_id": strategy_id, "user_id": user_id}
        ).sort([("version", ASCENDING)])
        documents = await cursor.to_list(length=None)
        return tuple(_parse_model(StrategyVersion, item) for item in documents)

    async def reserve_next_draft(
        self,
        *,
        strategy_id: str,
        user_id: str,
        expected_version_sequence: int,
        strategy_version_id: str,
        updated_at: datetime,
    ) -> int:
        """Atomically reserve the sole draft slot and next version number."""

        document = await self.get_db()[self.STRATEGIES_COLLECTION].find_one_and_update(
            {
                "strategy_id": strategy_id,
                "user_id": user_id,
                "archived_at": None,
                "current_draft_version_id": None,
                "version_sequence": expected_version_sequence,
            },
            {
                "$inc": {"version_sequence": 1},
                "$set": {
                    "current_draft_version_id": strategy_version_id,
                    "updated_at": updated_at,
                },
            },
            return_document=ReturnDocument.AFTER,
        )
        if document is None:
            raise StrategyConflict("strategy changed or already has a current draft")
        return int(document["version_sequence"])

    async def insert_reserved_version(self, version: StrategyVersion) -> StrategyVersion:
        if version.status != StrategyVersionStatus.DRAFT:
            raise ValueError("only draft versions can be inserted into a reservation")
        try:
            await self.get_db()[self.VERSIONS_COLLECTION].insert_one(
                version.model_dump(mode="json")
            )
        except DuplicateKeyError as exc:
            raise StrategyConflict("strategy version already exists") from exc
        return version

    async def release_draft_reservation(
        self,
        *,
        strategy_id: str,
        user_id: str,
        strategy_version_id: str,
        reserved_version: int,
    ) -> None:
        await self.get_db()[self.STRATEGIES_COLLECTION].find_one_and_update(
            {
                "strategy_id": strategy_id,
                "user_id": user_id,
                "current_draft_version_id": strategy_version_id,
                "version_sequence": reserved_version,
            },
            {
                "$inc": {"version_sequence": -1},
                "$set": {"current_draft_version_id": None},
            },
            return_document=ReturnDocument.AFTER,
        )

    async def replace_draft(
        self,
        replacement: StrategyVersion,
        *,
        expected_checksum: str,
    ) -> StrategyVersion:
        if replacement.status != StrategyVersionStatus.DRAFT:
            raise ValueError("replacement must remain a draft")
        document = await self.get_db()[self.VERSIONS_COLLECTION].find_one_and_update(
            {
                "strategy_version_id": replacement.strategy_version_id,
                "strategy_id": replacement.strategy_id,
                "user_id": replacement.user_id,
                "status": StrategyVersionStatus.DRAFT.value,
                "checksum": expected_checksum,
            },
            {"$set": replacement.model_dump(mode="json")},
            return_document=ReturnDocument.AFTER,
        )
        if document is None:
            raise StrategyConflict("draft changed, was published, or is not owner-visible")
        return _parse_model(StrategyVersion, document)

    async def transition_validation_state(
        self,
        replacement: StrategyVersion,
        *,
        expected_status: StrategyVersionStatus,
        expected_checksum: str,
    ) -> StrategyVersion:
        if replacement.status not in {
            StrategyVersionStatus.DRAFT,
            StrategyVersionStatus.VALIDATING,
        }:
            raise ValueError("validation transitions are limited to draft and validating")
        document = await self.get_db()[self.VERSIONS_COLLECTION].find_one_and_update(
            {
                "strategy_version_id": replacement.strategy_version_id,
                "strategy_id": replacement.strategy_id,
                "user_id": replacement.user_id,
                "status": expected_status.value,
                "checksum": expected_checksum,
            },
            {"$set": replacement.model_dump(mode="json")},
            return_document=ReturnDocument.AFTER,
        )
        if document is None:
            raise StrategyConflict("strategy version validation state changed concurrently")
        return _parse_model(StrategyVersion, document)

    async def publish_version(
        self,
        published: StrategyVersion,
        *,
        expected_draft_checksum: str,
        updated_at: datetime,
    ) -> StrategyVersion:
        if published.status != StrategyVersionStatus.PUBLISHED:
            raise ValueError("published replacement must use published status")
        versions = self.get_db()[self.VERSIONS_COLLECTION]
        document = await versions.find_one_and_update(
            {
                "strategy_version_id": published.strategy_version_id,
                "strategy_id": published.strategy_id,
                "user_id": published.user_id,
                "status": StrategyVersionStatus.DRAFT.value,
                "checksum": expected_draft_checksum,
            },
            {"$set": published.model_dump(mode="json")},
            return_document=ReturnDocument.AFTER,
        )
        if document is None:
            existing = await versions.find_one(
                {
                    "strategy_version_id": published.strategy_version_id,
                    "user_id": published.user_id,
                }
            )
            if existing is not None:
                parsed = _parse_model(StrategyVersion, existing)
                if (
                    parsed.status == StrategyVersionStatus.PUBLISHED
                    and parsed.checksum == published.checksum
                ):
                    return parsed
            raise StrategyConflict("draft changed, was already published, or is not owner-visible")
        header = await self.get_db()[self.STRATEGIES_COLLECTION].find_one_and_update(
            {
                "strategy_id": published.strategy_id,
                "user_id": published.user_id,
                "current_draft_version_id": published.strategy_version_id,
                "archived_at": None,
            },
            {
                "$set": {
                    "current_draft_version_id": None,
                    "latest_published_version_id": published.strategy_version_id,
                    "updated_at": updated_at,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if header is None:
            raise StrategyConflict("strategy header changed during publication")
        return _parse_model(StrategyVersion, document)

    async def archive_strategy(
        self, strategy_id: str, *, user_id: str, archived_at: datetime
    ) -> Strategy:
        if user_id == SYSTEM_USER_ID:
            raise StrategyConflict("system templates are read-only")
        document = await self.get_db()[self.STRATEGIES_COLLECTION].find_one_and_update(
            {
                "strategy_id": strategy_id,
                "user_id": user_id,
                "archived_at": None,
                "current_draft_version_id": None,
            },
            {"$set": {"archived_at": archived_at, "updated_at": archived_at}},
            return_document=ReturnDocument.AFTER,
        )
        if document is None:
            raise StrategyConflict("strategy is missing, archived, or still has a draft")
        return _parse_model(Strategy, document)

    async def deprecate_version(
        self, strategy_version_id: str, *, user_id: str
    ) -> StrategyVersion:
        if user_id == SYSTEM_USER_ID:
            raise StrategyConflict("system templates are read-only")
        document = await self.get_db()[self.VERSIONS_COLLECTION].find_one_and_update(
            {
                "strategy_version_id": strategy_version_id,
                "user_id": user_id,
                "status": StrategyVersionStatus.PUBLISHED.value,
            },
            {"$set": {"status": StrategyVersionStatus.DEPRECATED.value}},
            return_document=ReturnDocument.AFTER,
        )
        if document is None:
            raise StrategyConflict("only an owner-visible published version can be deprecated")
        return _parse_model(StrategyVersion, document)

    async def create_analysis_profile(
        self, profile: AnalysisProfile, initial_version: AnalysisProfileVersion
    ) -> tuple[AnalysisProfile, AnalysisProfileVersion]:
        """Create an owner-scoped profile and its first draft."""

        await self.ensure_indexes()
        if (
            initial_version.profile_id != profile.profile_id
            or initial_version.user_id != profile.user_id
            or initial_version.version != 1
            or initial_version.status != AnalysisProfileVersionStatus.DRAFT
            or profile.current_draft_version_id
            != initial_version.profile_version_id
            or profile.latest_published_version_id is not None
            or profile.version_sequence != 1
        ):
            raise ValueError("invalid initial AnalysisProfile/version pair")
        profiles = self.get_db()[self.ANALYSIS_PROFILES_COLLECTION]
        versions = self.get_db()[self.ANALYSIS_PROFILE_VERSIONS_COLLECTION]
        try:
            await profiles.insert_one(profile.model_dump(mode="json"))
        except DuplicateKeyError as exc:
            raise StrategyConflict("analysis profile ID already exists") from exc
        try:
            await versions.insert_one(initial_version.model_dump(mode="json"))
        except Exception as exc:
            await profiles.delete_one(
                {"profile_id": profile.profile_id, "user_id": profile.user_id}
            )
            if not isinstance(exc, DuplicateKeyError):
                raise
            raise StrategyConflict("initial analysis profile version already exists") from exc
        return profile, initial_version

    async def get_analysis_profile(
        self,
        profile_id: str,
        *,
        user_id: str,
        include_archived: bool = False,
    ) -> AnalysisProfile | None:
        query: dict[str, object] = {"profile_id": profile_id, "user_id": user_id}
        if not include_archived:
            query["archived_at"] = None
        document = await self.get_db()[self.ANALYSIS_PROFILES_COLLECTION].find_one(query)
        return None if document is None else _parse_model(AnalysisProfile, document)

    async def get_analysis_profile_version(
        self, profile_version_id: str, *, user_id: str
    ) -> AnalysisProfileVersion | None:
        document = await self.get_db()[
            self.ANALYSIS_PROFILE_VERSIONS_COLLECTION
        ].find_one({"profile_version_id": profile_version_id, "user_id": user_id})
        return None if document is None else _parse_model(AnalysisProfileVersion, document)

    async def list_analysis_profile_versions(
        self, profile_id: str, *, user_id: str
    ) -> tuple[AnalysisProfileVersion, ...]:
        cursor = self.get_db()[self.ANALYSIS_PROFILE_VERSIONS_COLLECTION].find(
            {"profile_id": profile_id, "user_id": user_id}
        ).sort([("version", ASCENDING)])
        documents = await cursor.to_list(length=None)
        return tuple(_parse_model(AnalysisProfileVersion, item) for item in documents)

    async def replace_analysis_profile_draft(
        self,
        replacement: AnalysisProfileVersion,
        *,
        expected_checksum: str,
    ) -> AnalysisProfileVersion:
        if replacement.status != AnalysisProfileVersionStatus.DRAFT:
            raise ValueError("replacement profile version must remain a draft")
        document = await self.get_db()[
            self.ANALYSIS_PROFILE_VERSIONS_COLLECTION
        ].find_one_and_update(
            {
                "profile_version_id": replacement.profile_version_id,
                "profile_id": replacement.profile_id,
                "user_id": replacement.user_id,
                "status": AnalysisProfileVersionStatus.DRAFT.value,
                "checksum": expected_checksum,
            },
            {"$set": replacement.model_dump(mode="json")},
            return_document=ReturnDocument.AFTER,
        )
        if document is None:
            raise StrategyConflict(
                "analysis profile draft changed, was published, or is not owner-visible"
            )
        return _parse_model(AnalysisProfileVersion, document)

    async def publish_analysis_profile_version(
        self,
        published: AnalysisProfileVersion,
        *,
        expected_draft_checksum: str,
        updated_at: datetime,
    ) -> AnalysisProfileVersion:
        if published.status != AnalysisProfileVersionStatus.PUBLISHED:
            raise ValueError("published profile replacement must use published status")
        versions = self.get_db()[self.ANALYSIS_PROFILE_VERSIONS_COLLECTION]
        document = await versions.find_one_and_update(
            {
                "profile_version_id": published.profile_version_id,
                "profile_id": published.profile_id,
                "user_id": published.user_id,
                "status": AnalysisProfileVersionStatus.DRAFT.value,
                "checksum": expected_draft_checksum,
            },
            {"$set": published.model_dump(mode="json")},
            return_document=ReturnDocument.AFTER,
        )
        if document is None:
            existing = await versions.find_one(
                {
                    "profile_version_id": published.profile_version_id,
                    "user_id": published.user_id,
                }
            )
            if existing is not None:
                parsed = _parse_model(AnalysisProfileVersion, existing)
                if (
                    parsed.status == AnalysisProfileVersionStatus.PUBLISHED
                    and parsed.checksum == published.checksum
                ):
                    return parsed
            raise StrategyConflict("analysis profile draft changed or was already published")
        header = await self.get_db()[
            self.ANALYSIS_PROFILES_COLLECTION
        ].find_one_and_update(
            {
                "profile_id": published.profile_id,
                "user_id": published.user_id,
                "current_draft_version_id": published.profile_version_id,
                "archived_at": None,
            },
            {
                "$set": {
                    "current_draft_version_id": None,
                    "latest_published_version_id": published.profile_version_id,
                    "updated_at": updated_at,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if header is None:
            raise StrategyConflict("analysis profile header changed during publication")
        return _parse_model(AnalysisProfileVersion, document)

    async def reserve_next_analysis_profile_draft(
        self,
        *,
        profile_id: str,
        user_id: str,
        expected_version_sequence: int,
        profile_version_id: str,
        updated_at: datetime,
    ) -> int:
        document = await self.get_db()[
            self.ANALYSIS_PROFILES_COLLECTION
        ].find_one_and_update(
            {
                "profile_id": profile_id,
                "user_id": user_id,
                "archived_at": None,
                "current_draft_version_id": None,
                "version_sequence": expected_version_sequence,
            },
            {
                "$inc": {"version_sequence": 1},
                "$set": {
                    "current_draft_version_id": profile_version_id,
                    "updated_at": updated_at,
                },
            },
            return_document=ReturnDocument.AFTER,
        )
        if document is None:
            raise StrategyConflict("analysis profile changed or already has a draft")
        return int(document["version_sequence"])

    async def insert_reserved_analysis_profile_version(
        self, version: AnalysisProfileVersion
    ) -> AnalysisProfileVersion:
        if version.status != AnalysisProfileVersionStatus.DRAFT:
            raise ValueError("only draft profile versions can fill a reservation")
        try:
            await self.get_db()[self.ANALYSIS_PROFILE_VERSIONS_COLLECTION].insert_one(
                version.model_dump(mode="json")
            )
        except DuplicateKeyError as exc:
            raise StrategyConflict("analysis profile version already exists") from exc
        return version

    async def release_analysis_profile_draft_reservation(
        self,
        *,
        profile_id: str,
        user_id: str,
        profile_version_id: str,
        reserved_version: int,
    ) -> None:
        await self.get_db()[self.ANALYSIS_PROFILES_COLLECTION].find_one_and_update(
            {
                "profile_id": profile_id,
                "user_id": user_id,
                "current_draft_version_id": profile_version_id,
                "version_sequence": reserved_version,
            },
            {
                "$inc": {"version_sequence": -1},
                "$set": {"current_draft_version_id": None},
            },
            return_document=ReturnDocument.AFTER,
        )

    async def save_universe_snapshot(self, snapshot: UniverseSnapshot) -> UniverseSnapshot:
        await self.ensure_indexes()
        collection = self.get_db()[self.UNIVERSES_COLLECTION]
        key = {"universe_snapshot_id": snapshot.universe_snapshot_id}
        existing = await collection.find_one(key)
        if existing is not None:
            return self._require_same_snapshot(existing, snapshot)
        try:
            await collection.update_one(
                key,
                {"$setOnInsert": snapshot.model_dump(mode="json")},
                upsert=True,
            )
        except DuplicateKeyError:
            pass
        document = await collection.find_one(key)
        if document is None:
            raise RuntimeError("universe snapshot upsert did not persist a document")
        return self._require_same_snapshot(document, snapshot)

    async def get_universe_snapshot(
        self, universe_snapshot_id: str, *, user_id: str
    ) -> UniverseSnapshot | None:
        document = await self.get_db()[self.UNIVERSES_COLLECTION].find_one(
            {"universe_snapshot_id": universe_snapshot_id, "user_id": user_id}
        )
        return None if document is None else _parse_model(UniverseSnapshot, document)

    async def list_universe_snapshots(
        self,
        *,
        user_id: str,
        market: str | None = None,
        trade_date: date | None = None,
        limit: int = 100,
    ) -> tuple[UniverseSnapshot, ...]:
        query: dict[str, object] = {"user_id": user_id}
        if market is not None:
            query["market"] = market
        if trade_date is not None:
            query["trade_date"] = trade_date.isoformat()
        cursor = self.get_db()[self.UNIVERSES_COLLECTION].find(query).sort(
            [("trade_date", DESCENDING), ("universe_snapshot_id", ASCENDING)]
        )
        documents = await cursor.to_list(length=limit)
        return tuple(_parse_model(UniverseSnapshot, item) for item in documents)

    async def save_signal(self, signal: StrategySignal) -> StrategySignal:
        await self.ensure_indexes()
        await self._validate_signal_references(signal)
        collection = self.get_db()[self.SIGNALS_COLLECTION]
        key = {
            "strategy_version_id": signal.strategy_version_id,
            "market": signal.market.value,
            "symbol": signal.symbol,
            "signal_date": signal.signal_date.isoformat(),
            "signal_type": signal.signal_type,
        }
        existing = await collection.find_one(key)
        if existing is not None:
            return self._require_same_signal(existing, signal)
        try:
            await collection.update_one(
                key,
                {"$setOnInsert": signal.model_dump(mode="json")},
                upsert=True,
            )
        except DuplicateKeyError:
            pass
        document = await collection.find_one(key)
        if document is None:
            raise RuntimeError("strategy signal upsert did not persist a document")
        return self._require_same_signal(document, signal)

    async def save_signals(
        self, signals: Iterable[StrategySignal]
    ) -> tuple[StrategySignal, ...]:
        return tuple([await self.save_signal(signal) for signal in signals])

    async def list_signals(
        self,
        *,
        user_id: str,
        strategy_version_id: str,
        limit: int = 1000,
    ) -> tuple[StrategySignal, ...]:
        cursor = self.get_db()[self.SIGNALS_COLLECTION].find(
            {"user_id": user_id, "strategy_version_id": strategy_version_id}
        ).sort(
            [
                ("signal_date", DESCENDING),
                ("market", ASCENDING),
                ("symbol", ASCENDING),
                ("signal_type", ASCENDING),
            ]
        )
        documents = await cursor.to_list(length=limit)
        return tuple(_parse_model(StrategySignal, item) for item in documents)

    async def _validate_signal_references(self, signal: StrategySignal) -> None:
        versions = self.get_db()[self.VERSIONS_COLLECTION]
        version = None
        for status in (
            StrategyVersionStatus.PUBLISHED.value,
            StrategyVersionStatus.DEPRECATED.value,
        ):
            version = await versions.find_one(
                {
                    "strategy_version_id": signal.strategy_version_id,
                    "user_id": signal.user_id,
                    "status": status,
                }
            )
            if version is None:
                version = await versions.find_one(
                    {
                        "strategy_version_id": signal.strategy_version_id,
                        "user_id": SYSTEM_USER_ID,
                        "status": status,
                    }
                )
            if version is not None:
                break
        if version is None:
            raise StrategyNotFound("published strategy version is not owner-visible")
        if version.get("market") != signal.market.value:
            raise StrategyConflict("signal market does not match strategy version")

        universe = await self.get_db()[self.UNIVERSES_COLLECTION].find_one(
            {
                "universe_snapshot_id": signal.universe_snapshot_id,
                "user_id": signal.user_id,
            }
        )
        if universe is None:
            raise StrategyNotFound("universe snapshot is not owner-visible")
        if universe.get("market") != signal.market.value:
            raise StrategyConflict("signal market does not match universe snapshot")

        if signal.factor_snapshot_id is not None:
            factor_snapshot = await self.get_db()["factor_snapshots"].find_one(
                {
                    "snapshot_id": signal.factor_snapshot_id,
                    "user_id": signal.user_id,
                    "status": "ready",
                }
            )
            if factor_snapshot is None:
                raise StrategyNotFound("ready factor snapshot is not owner-visible")
            if factor_snapshot.get("market") != signal.market.value:
                raise StrategyConflict("signal market does not match factor snapshot")

    @staticmethod
    def _validate_initial_pair(strategy: Strategy, version: StrategyVersion) -> None:
        if version.strategy_id != strategy.strategy_id or version.user_id != strategy.user_id:
            raise ValueError("initial version owner and strategy must match the strategy header")
        if version.version != 1 or version.status != StrategyVersionStatus.DRAFT:
            raise ValueError("a strategy must start with draft version 1")
        if strategy.current_draft_version_id != version.strategy_version_id:
            raise ValueError("strategy current draft must reference its initial version")
        if strategy.latest_published_version_id is not None or strategy.version_sequence != 1:
            raise ValueError("a new strategy cannot already have a published or later version")

    @staticmethod
    def _require_same_snapshot(
        document: dict, snapshot: UniverseSnapshot
    ) -> UniverseSnapshot:
        parsed = _parse_model(UniverseSnapshot, document)
        if parsed.user_id != snapshot.user_id or parsed.checksum != snapshot.checksum:
            raise StrategyImmutableConflict(
                "universe snapshot ID already contains different immutable content"
            )
        return parsed

    @staticmethod
    def _require_same_signal(document: dict, signal: StrategySignal) -> StrategySignal:
        parsed = _parse_model(StrategySignal, document)
        if parsed.user_id != signal.user_id or parsed.checksum != signal.checksum:
            raise StrategyImmutableConflict(
                "strategy signal identity already contains different immutable content"
            )
        return parsed


def _parse_model(model, document: dict):
    payload = dict(document)
    payload.pop("_id", None)
    return model.model_validate(payload)
