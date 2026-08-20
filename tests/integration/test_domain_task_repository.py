import pytest
import uuid
from datetime import timedelta
from typing import Optional, List, Dict, Any, Tuple
from app.utils.timezone import now_tz
from app.models.domain_task import (
    DomainTask,
    DomainTaskEvent,
    TaskStatus,
    TaskType,
    validate_task_transition,
    InvalidTaskTransitionError
)


class IdempotencyConflictError(Exception):
    """幂等键请求冲突"""
    pass


class TaskNotFoundError(Exception):
    """任务未找到"""
    pass


class TaskForbiddenError(Exception):
    """无权访问任务"""
    pass


class FakeCollection:
    """轻量级 In-Memory Async MongoDB 集合模拟器"""
    def __init__(self):
        self.docs = []

    async def create_index(self, keys, **kwargs):
        pass

    async def insert_one(self, doc):
        self.docs.append(dict(doc))
        return type("Res", (), {"inserted_id": doc.get("_id", "mock_id")})()

    async def delete_many(self, filter_dict):
        to_keep = [d for d in self.docs if not self._doc_matches(d, filter_dict)]
        deleted_count = len(self.docs) - len(to_keep)
        self.docs = to_keep
        return type("Res", (), {"deleted_count": deleted_count})()

    async def delete_one(self, filter_dict):
        target = await self.find_one(filter_dict)
        if target and target in self.docs:
            self.docs.remove(target)
            return type("Res", (), {"deleted_count": 1})()
        return type("Res", (), {"deleted_count": 0})()

    async def find_one(self, filter_dict, projection=None):
        for doc in self.docs:
            if self._doc_matches(doc, filter_dict):
                return dict(doc)
        return None

    def _doc_matches(self, doc, filter_dict):
        for k, v in filter_dict.items():
            if k == "$or" and isinstance(v, list):
                if not any(self._doc_matches(doc, sub) for sub in v):
                    return False
            elif k == "status" and isinstance(v, dict):
                if "$in" in v and doc.get(k) not in v["$in"]:
                    return False
            elif isinstance(v, dict):
                val = doc.get(k)
                if "$lt" in v and not (val and val < v["$lt"]):
                    return False
                if "$lte" in v and not (val and val <= v["$lte"]):
                    return False
                if "$gt" in v and not (val and val > v["$gt"]):
                    return False
                if "$gte" in v and not (val and val >= v["$gte"]):
                    return False
                if "$in" in v and val not in v["$in"]:
                    return False
            elif k != "$or" and doc.get(k) != v:
                return False
        return True

    async def find_one_and_update(self, filter, update, sort=None, return_document=True):
        matched = [d for d in self.docs if self._doc_matches(d, filter)]
        if sort:
            for field, direction in reversed(sort):
                reverse = direction == -1
                matched.sort(key=lambda x: x.get(field) or "", reverse=reverse)

        if not matched:
            return None

        target = matched[0]
        if "$set" in update:
            for k, v in update["$set"].items():
                target[k] = v
        if "$inc" in update:
            for k, v in update["$inc"].items():
                target[k] = target.get(k, 0) + v

        return dict(target)

    async def update_one(self, filter, update, upsert=False):
        target = await self.find_one(filter)
        if not target:
            if upsert:
                new_doc = dict(filter)
                if "$set" in update:
                    new_doc.update(update["$set"])
                self.docs.append(new_doc)
                return type("Res", (), {"modified_count": 1})()
            return type("Res", (), {"modified_count": 0})()

        for doc in self.docs:
            if self._doc_matches(doc, filter):
                if "$set" in update:
                    for k, v in update["$set"].items():
                        doc[k] = v
                if "$inc" in update:
                    for k, v in update["$inc"].items():
                        doc[k] = doc.get(k, 0) + v
                return type("Res", (), {"modified_count": 1})()
        return type("Res", (), {"modified_count": 0})()

    def find(self, filter_dict):
        matched = [d for d in self.docs if self._doc_matches(d, filter_dict)]

        class Cursor:
            def __init__(self, items):
                self.items = items
            def sort(self, field, direction):
                reverse = direction == -1
                self.items.sort(key=lambda x: x.get(field) or "", reverse=reverse)
                return self
            def skip(self, n):
                self.items = self.items[n:]
                return self
            def limit(self, n):
                if n is not None:
                    self.items = self.items[:n]
                return self
            async def to_list(self, length=None):
                if length is not None:
                    return self.items[:length]
                return self.items
            def __await__(self):
                async def _inner():
                    return self.items
                return _inner().__await__()

        return Cursor(matched)

    async def count_documents(self, filter_dict):
        return len([d for d in self.docs if self._doc_matches(d, filter_dict)])


class FakeDatabase:
    def __init__(self):
        self.cols = {}

    def __getitem__(self, name):
        if name not in self.cols:
            self.cols[name] = FakeCollection()
        return self.cols[name]


@pytest.fixture
def repo():
    db = FakeDatabase()
    return DomainTaskRepository(db)


@pytest.mark.asyncio
async def test_create_task_and_idempotency(repo):
    task1 = await repo.create_task(
        user_id="user_a",
        task_type=TaskType.FACTOR_COMPUTE,
        payload={"symbols": ["000001"]},
        idempotency_key="key_100",
        request_hash="hash_abc"
    )
    assert task1.status == TaskStatus.QUEUED

    task2 = await repo.create_task(
        user_id="user_a",
        task_type=TaskType.FACTOR_COMPUTE,
        payload={"symbols": ["000001"]},
        idempotency_key="key_100",
        request_hash="hash_abc"
    )
    assert task2.task_id == task1.task_id

    with pytest.raises(IdempotencyConflictError):
        await repo.create_task(
            user_id="user_a",
            task_type=TaskType.FACTOR_COMPUTE,
            payload={"symbols": ["000002"]},
            idempotency_key="key_100",
            request_hash="hash_diff"
        )


@pytest.mark.asyncio
async def test_claim_and_compete_tasks(repo):
    task = await repo.create_task(
        user_id="user_a",
        task_type=TaskType.BACKTEST,
        payload={"strategy": "demo"}
    )

    claimed = await repo.claim_task(worker_id="worker_1", lease_seconds=60)
    assert claimed is not None
    assert claimed.task_id == task.task_id
    assert claimed.status == TaskStatus.RUNNING
    assert claimed.worker_id == "worker_1"
    assert claimed.attempt == 1

    claimed_again = await repo.claim_task(worker_id="worker_2")
    assert claimed_again is None


@pytest.mark.asyncio
async def test_heartbeat_and_progress_update(repo):
    task = await repo.create_task(
        user_id="user_a",
        task_type=TaskType.ALERT_EVAL,
        payload={}
    )
    await repo.claim_task(worker_id="worker_1")

    hb_res = await repo.heartbeat(task_id=task.task_id, worker_id="worker_1", lease_seconds=120)
    assert hb_res["success"] is True
    assert hb_res["cancel_requested"] is False

    progress_ok = await repo.update_progress(
        task_id=task.task_id,
        worker_id="worker_1",
        progress=0.5,
        stage="evaluating",
        message="Halfway done"
    )
    assert progress_ok is True

    fetched = await repo.get_task(task.task_id, user_id="user_a")
    assert fetched.progress == 0.5
    assert fetched.stage == "evaluating"


@pytest.mark.asyncio
async def test_cross_user_isolation(repo):
    task = await repo.create_task(
        user_id="user_a",
        task_type=TaskType.CAMPAIGN_EVAL,
        payload={}
    )

    with pytest.raises(TaskForbiddenError):
        await repo.get_task(task.task_id, user_id="user_b")

    with pytest.raises(TaskForbiddenError):
        await repo.request_cancel(task.task_id, user_id="user_b")


@pytest.mark.asyncio
async def test_lease_expiration_and_zombie_recovery(repo):
    task = await repo.create_task(
        user_id="user_a",
        task_type=TaskType.FACTOR_COMPUTE,
        payload={},
        max_attempts=2
    )

    claimed = await repo.claim_task(worker_id="worker_1", lease_seconds=1)

    past_time = now_tz() - timedelta(seconds=10)
    await repo.tasks_col.update_one(
        {"task_id": task.task_id},
        {"$set": {"lease_expires_at": past_time}}
    )

    recovered = await repo.recover_expired_leases()
    assert recovered == 1

    recovered_task = await repo.get_task(task.task_id, user_id="user_a")
    assert recovered_task.status == TaskStatus.RETRY_WAIT
