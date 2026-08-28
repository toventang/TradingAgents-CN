"""Small deterministic Motor-compatible fakes for factor persistence tests."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any


@dataclass
class FakeUpdateResult:
    upserted_id: str | None = None


def _matches(document: dict[str, Any], query: dict[str, Any]) -> bool:
    return all(document.get(key) == value for key, value in query.items())


class FakeCursor:
    def __init__(self, documents: list[dict[str, Any]]):
        self._documents = deepcopy(documents)

    def sort(self, keys):
        for key, direction in reversed(keys):
            self._documents.sort(
                key=lambda item: item.get(key), reverse=direction < 0
            )
        return self

    async def to_list(self, length=None):
        documents = self._documents if length is None else self._documents[:length]
        return deepcopy(documents)


class FakeCollection:
    def __init__(self):
        self.documents: list[dict[str, Any]] = []
        self.indexes: list[tuple[tuple[tuple[str, int], ...], dict[str, Any]]] = []
        self._sequence = 0

    async def create_index(self, keys, **options):
        self.indexes.append((tuple(keys), deepcopy(options)))
        return options.get("name")

    async def find_one(self, query, sort=None):
        matches = [item for item in self.documents if _matches(item, query)]
        if sort:
            for key, direction in reversed(sort):
                matches.sort(key=lambda item: item.get(key), reverse=direction < 0)
        return deepcopy(matches[0]) if matches else None

    async def update_one(self, query, update, upsert=False):
        for document in self.documents:
            if _matches(document, query):
                document.update(deepcopy(update.get("$set", {})))
                return FakeUpdateResult()
        if not upsert:
            return FakeUpdateResult()
        self._sequence += 1
        document = deepcopy(query)
        document.update(deepcopy(update.get("$setOnInsert", {})))
        document.update(deepcopy(update.get("$set", {})))
        document.setdefault("_id", f"fake-{self._sequence}")
        self.documents.append(document)
        return FakeUpdateResult(upserted_id=document["_id"])

    async def find_one_and_update(self, query, update, return_document=None):
        del return_document
        for document in self.documents:
            if _matches(document, query):
                document.update(deepcopy(update.get("$set", {})))
                return deepcopy(document)
        return None

    async def bulk_write(self, operations, ordered=False):
        del ordered
        for operation in operations:
            await self.update_one(
                operation._filter,
                operation._doc,
                upsert=operation._upsert,
            )
        return FakeUpdateResult()

    def find(self, query):
        return FakeCursor(
            [item for item in self.documents if _matches(item, query)]
        )


class FakeDatabase:
    def __init__(self):
        self.collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name):
        return self.collections.setdefault(name, FakeCollection())
