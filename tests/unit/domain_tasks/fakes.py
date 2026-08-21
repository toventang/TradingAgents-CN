"""Small deterministic async MongoDB fake for repository contract tests."""

import asyncio
from copy import deepcopy
from typing import Any, Optional

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError


def _expression_value(document: dict[str, Any], value: Any) -> Any:
    if isinstance(value, str) and value.startswith("$"):
        return document.get(value[1:])
    return value


def _matches(document: dict[str, Any], query: dict[str, Any]) -> bool:
    for key, expected in query.items():
        if key == "$expr":
            if "$lt" in expected:
                left, right = expected["$lt"]
                if not (
                    _expression_value(document, left)
                    < _expression_value(document, right)
                ):
                    return False
                continue
            raise AssertionError(f"unsupported expression: {expected}")
        if key == "$or":
            if not any(_matches(document, item) for item in expected):
                return False
            continue

        actual = document.get(key)
        if isinstance(expected, dict):
            for operator, operand in expected.items():
                if operator == "$in" and actual not in operand:
                    return False
                if operator == "$lt" and not actual < operand:
                    return False
                if operator == "$lte" and not actual <= operand:
                    return False
                if operator == "$gt" and not actual > operand:
                    return False
                if operator == "$gte" and not actual >= operand:
                    return False
                if operator == "$ne" and actual == operand:
                    return False
            continue
        if actual != expected:
            return False
    return True


def _sort_documents(
    documents: list[dict[str, Any]],
    sort: Optional[list[tuple[str, int]]],
) -> list[dict[str, Any]]:
    result = list(documents)
    for field, direction in reversed(sort or []):
        result.sort(key=lambda item: item.get(field), reverse=direction < 0)
    return result


def _apply_update(document: dict[str, Any], update: dict[str, Any]) -> None:
    for field, value in update.get("$set", {}).items():
        document[field] = deepcopy(value)
    for field, value in update.get("$inc", {}).items():
        document[field] = document.get(field, 0) + value
    for field in update.get("$unset", {}):
        document.pop(field, None)
    for field, value in update.get("$min", {}).items():
        if document.get(field) is None or value < document[field]:
            document[field] = deepcopy(value)


class FakeCursor:
    def __init__(self, documents: list[dict[str, Any]]):
        self.documents = documents
        self.offset = 0
        self.maximum: Optional[int] = None

    def sort(self, spec: list[tuple[str, int]]) -> "FakeCursor":
        self.documents = _sort_documents(self.documents, spec)
        return self

    def skip(self, count: int) -> "FakeCursor":
        self.offset = count
        return self

    def limit(self, count: int) -> "FakeCursor":
        self.maximum = count
        return self

    async def to_list(self, length: Optional[int]) -> list[dict[str, Any]]:
        maximum = self.maximum if self.maximum is not None else length
        selected = self.documents[self.offset :]
        if maximum is not None:
            selected = selected[:maximum]
        return deepcopy(selected)


class FakeCollection:
    def __init__(self, name: str):
        self.name = name
        self.documents: list[dict[str, Any]] = []
        self.indexes: list[tuple[list[tuple[str, int]], dict[str, Any]]] = []
        self.lock = asyncio.Lock()

    async def create_index(self, keys, **options):
        self.indexes.append((list(keys), dict(options)))
        return options.get("name", "index")

    def _check_unique(self, candidate: dict[str, Any]) -> None:
        for document in self.documents:
            if (
                self.name == "domain_tasks"
                and candidate.get("task_id") is not None
                and candidate.get("task_id") == document.get("task_id")
            ):
                raise DuplicateKeyError("duplicate task_id")
            if (
                self.name == "domain_task_events"
                and candidate.get("event_id") is not None
                and candidate.get("event_id") == document.get("event_id")
            ):
                raise DuplicateKeyError("duplicate event_id")
            key = candidate.get("idempotency_key")
            if (
                self.name == "domain_tasks"
                and isinstance(key, str)
                and key == document.get("idempotency_key")
                and candidate.get("user_id") == document.get("user_id")
                and candidate.get("task_type") == document.get("task_type")
            ):
                raise DuplicateKeyError("duplicate idempotency key")

    async def insert_one(self, document):
        async with self.lock:
            candidate = deepcopy(document)
            self._check_unique(candidate)
            self.documents.append(candidate)
        return type("InsertOneResult", (), {"inserted_id": len(self.documents)})()

    async def find_one(self, query, projection=None, sort=None):
        async with self.lock:
            matches = [
                document
                for document in self.documents
                if _matches(document, query)
            ]
            matches = _sort_documents(matches, sort)
            return deepcopy(matches[0]) if matches else None

    def find(self, query):
        matches = [
            deepcopy(document)
            for document in self.documents
            if _matches(document, query)
        ]
        return FakeCursor(matches)

    async def find_one_and_update(
        self,
        query,
        update,
        sort=None,
        return_document=ReturnDocument.BEFORE,
    ):
        async with self.lock:
            matches = [
                document
                for document in self.documents
                if _matches(document, query)
            ]
            matches = _sort_documents(matches, sort)
            if not matches:
                return None
            selected = matches[0]
            before = deepcopy(selected)
            _apply_update(selected, update)
            return deepcopy(
                selected
                if return_document == ReturnDocument.AFTER
                else before
            )


class FakeDatabase:
    def __init__(self):
        self.collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        self.collections.setdefault(name, FakeCollection(name))
        return self.collections[name]
