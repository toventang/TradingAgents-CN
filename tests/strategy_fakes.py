"""Deterministic Motor-compatible fakes for strategy persistence tests."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from pymongo.errors import DuplicateKeyError


@dataclass
class FakeInsertResult:
    inserted_id: str


@dataclass
class FakeUpdateResult:
    upserted_id: str | None = None
    matched_count: int = 0


@dataclass
class FakeDeleteResult:
    deleted_count: int


def _matches(document: dict[str, Any], query: dict[str, Any]) -> bool:
    return all(document.get(key) == value for key, value in query.items())


class FakeCursor:
    def __init__(self, documents: list[dict[str, Any]]):
        self._documents = deepcopy(documents)

    def sort(self, keys):
        for key, direction in reversed(keys):
            self._documents.sort(key=lambda item: item.get(key), reverse=direction < 0)
        return self

    async def to_list(self, length=None):
        result = self._documents if length is None else self._documents[:length]
        return deepcopy(result)


class FakeCollection:
    def __init__(self):
        self.documents: list[dict[str, Any]] = []
        self.indexes: list[tuple[tuple[tuple[str, int], ...], dict[str, Any]]] = []
        self._sequence = 0

    async def create_index(self, keys, **options):
        normalized = (tuple(keys), deepcopy(options))
        if normalized not in self.indexes:
            self.indexes.append(normalized)
        return options.get("name")

    async def insert_one(self, document):
        await asyncio.sleep(0)
        candidate = deepcopy(document)
        self._check_unique(candidate)
        self._sequence += 1
        candidate.setdefault("_id", f"fake-{self._sequence}")
        self.documents.append(candidate)
        return FakeInsertResult(candidate["_id"])

    async def delete_one(self, query):
        await asyncio.sleep(0)
        for index, document in enumerate(self.documents):
            if _matches(document, query):
                self.documents.pop(index)
                return FakeDeleteResult(1)
        return FakeDeleteResult(0)

    async def find_one(self, query, sort=None):
        await asyncio.sleep(0)
        matches = [document for document in self.documents if _matches(document, query)]
        if sort:
            for key, direction in reversed(sort):
                matches.sort(key=lambda item: item.get(key), reverse=direction < 0)
        return deepcopy(matches[0]) if matches else None

    def find(self, query):
        return FakeCursor(
            [document for document in self.documents if _matches(document, query)]
        )

    async def update_one(self, query, update, upsert=False):
        await asyncio.sleep(0)
        for document in self.documents:
            if _matches(document, query):
                candidate = deepcopy(document)
                self._apply_update(candidate, update)
                self._check_unique(candidate, ignore=document)
                document.clear()
                document.update(candidate)
                return FakeUpdateResult(matched_count=1)
        if not upsert:
            return FakeUpdateResult()
        candidate = deepcopy(query)
        self._apply_update(candidate, update, inserting=True)
        result = await self.insert_one(candidate)
        return FakeUpdateResult(upserted_id=result.inserted_id)

    async def find_one_and_update(self, query, update, return_document=None):
        del return_document
        await asyncio.sleep(0)
        for document in self.documents:
            if _matches(document, query):
                candidate = deepcopy(document)
                self._apply_update(candidate, update)
                self._check_unique(candidate, ignore=document)
                document.clear()
                document.update(candidate)
                return deepcopy(document)
        return None

    def _check_unique(self, candidate, *, ignore=None):
        for keys, options in self.indexes:
            if not options.get("unique"):
                continue
            identity = tuple(candidate.get(key) for key, _ in keys)
            for document in self.documents:
                if document is ignore:
                    continue
                if tuple(document.get(key) for key, _ in keys) == identity:
                    raise DuplicateKeyError(options.get("name", "duplicate key"))

    @staticmethod
    def _apply_update(candidate, update, *, inserting=False):
        if inserting:
            candidate.update(deepcopy(update.get("$setOnInsert", {})))
        candidate.update(deepcopy(update.get("$set", {})))
        for key, increment in update.get("$inc", {}).items():
            candidate[key] = candidate.get(key, 0) + increment


class FakeDatabase:
    def __init__(self):
        self.collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name):
        return self.collections.setdefault(name, FakeCollection())
