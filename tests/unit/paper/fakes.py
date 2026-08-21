"""Minimal deterministic async Mongo fake for paper-domain characterization."""

from copy import deepcopy
from typing import Any, Optional


def _get(document: dict[str, Any], path: str) -> Any:
    value: Any = document
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _set(document: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    target = document
    for part in parts[:-1]:
        target = target.setdefault(part, {})
    target[parts[-1]] = deepcopy(value)


def _matches(document: dict[str, Any], query: dict[str, Any]) -> bool:
    for field, expected in query.items():
        if field == "$or":
            if not any(_matches(document, candidate) for candidate in expected):
                return False
            continue
        actual = _get(document, field)
        if isinstance(expected, dict):
            for operator, operand in expected.items():
                if operator == "$gte" and not actual >= operand:
                    return False
                if operator == "$in" and actual not in operand:
                    return False
            continue
        if actual != expected:
            return False
    return True


class FakeCursor:
    def __init__(self, documents: list[dict[str, Any]]):
        self.documents = documents
        self.maximum: Optional[int] = None

    def sort(self, field, direction=None):
        specification = field if isinstance(field, list) else [(field, direction)]
        for key, order in reversed(specification):
            self.documents.sort(
                key=lambda item: _get(item, key),
                reverse=order < 0,
            )
        return self

    def limit(self, count: int):
        self.maximum = count
        return self

    async def to_list(self, length):
        maximum = self.maximum if self.maximum is not None else length
        selected = self.documents
        if maximum is not None:
            selected = selected[:maximum]
        return deepcopy(selected)


class FakeAggregateCursor:
    def __init__(self, documents, pipeline):
        self.documents = documents
        self.pipeline = pipeline

    async def to_list(self, length):
        matched = self.documents
        for stage in self.pipeline:
            if "$match" in stage:
                matched = [
                    document
                    for document in matched
                    if _matches(document, stage["$match"])
                ]
            elif "$group" in stage:
                field = stage["$group"]["total"]["$sum"][1:]
                total = sum(_get(document, field) or 0 for document in matched)
                matched = [{"_id": None, "total": total}] if matched else []
        return deepcopy(matched[:length] if length is not None else matched)


class FakeCollection:
    def __init__(self, name: str):
        self.name = name
        self.documents: list[dict[str, Any]] = []
        self.fail_next: dict[str, Exception] = {}
        self._next_id = 1

    def _maybe_fail(self, operation: str) -> None:
        failure = self.fail_next.pop(operation, None)
        if failure is not None:
            raise failure

    async def insert_one(self, document):
        self._maybe_fail("insert_one")
        document.setdefault("_id", f"{self.name}-{self._next_id}")
        self._next_id += 1
        self.documents.append(deepcopy(document))
        return type("InsertResult", (), {"inserted_id": document["_id"]})()

    async def find_one(self, query, projection=None):
        self._maybe_fail("find_one")
        for document in self.documents:
            if _matches(document, query):
                result = deepcopy(document)
                if projection:
                    included = {
                        field
                        for field, enabled in projection.items()
                        if enabled and field != "_id"
                    }
                    result = {
                        field: _get(result, field)
                        for field in included
                        if _get(result, field) is not None
                    }
                return result
        return None

    def find(self, query):
        self._maybe_fail("find")
        return FakeCursor(
            [
                deepcopy(document)
                for document in self.documents
                if _matches(document, query)
            ]
        )

    async def update_one(self, query, update):
        self._maybe_fail("update_one")
        for document in self.documents:
            if not _matches(document, query):
                continue
            for field, value in update.get("$set", {}).items():
                _set(document, field, value)
            for field, value in update.get("$inc", {}).items():
                _set(document, field, (_get(document, field) or 0) + value)
            return type("UpdateResult", (), {"matched_count": 1})()
        return type("UpdateResult", (), {"matched_count": 0})()

    async def delete_one(self, query):
        self._maybe_fail("delete_one")
        for index, document in enumerate(self.documents):
            if _matches(document, query):
                self.documents.pop(index)
                return type("DeleteResult", (), {"deleted_count": 1})()
        return type("DeleteResult", (), {"deleted_count": 0})()

    async def delete_many(self, query):
        self._maybe_fail("delete_many")
        kept = [
            document for document in self.documents if not _matches(document, query)
        ]
        count = len(self.documents) - len(kept)
        self.documents = kept
        return type("DeleteResult", (), {"deleted_count": count})()

    def aggregate(self, pipeline):
        self._maybe_fail("aggregate")
        return FakeAggregateCursor(deepcopy(self.documents), pipeline)


class FakeDatabase:
    def __init__(self):
        self.collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        self.collections.setdefault(name, FakeCollection(name))
        return self.collections[name]
