import pytest
from app.models.strategy import Strategy, StrategyVersion, StrategyStatus, UniverseSnapshot
from app.repositories.strategy_repository import StrategyRepository, StrategyNotFoundError, StrategyForbiddenError
from app.services.strategies.version_service import VersionService
from app.utils.timezone import now_tz


class FakeCollection:
    def __init__(self):
        self.docs = []

    async def insert_one(self, doc):
        self.docs.append(dict(doc))
        return True

    async def find_one(self, query):
        for d in self.docs:
            match = True
            for k, v in query.items():
                if d.get(k) != v:
                    match = False
                    break
            if match:
                return dict(d)
        return None

    def find(self, query):
        filtered = []
        for d in self.docs:
            match = True
            for k, v in query.items():
                if k == "$or":
                    or_match = False
                    for cond in v:
                        cond_ok = True
                        for ck, cv in cond.items():
                            if d.get(ck) != cv:
                                cond_ok = False
                                break
                        if cond_ok:
                            or_match = True
                            break
                    if not or_match:
                        match = False
                        break
                elif k == "status" and isinstance(v, dict) and "$ne" in v:
                    if d.get("status") == v["$ne"]:
                        match = False
                        break
                elif d.get(k) != v:
                    match = False
                    break
            if match:
                filtered.append(dict(d))

        class AsyncCursor:
            def __init__(self, data):
                self.data = data
                self.index = 0

            def sort(self, key, direction=1):
                reverse = direction == -1
                self.data.sort(key=lambda x: x.get(key, ""), reverse=reverse)
                return self

            def skip(self, n):
                self.data = self.data[n:]
                return self

            def limit(self, n):
                self.data = self.data[:n]
                return self

            def __aiter__(self):
                return self

            async def __anext__(self):
                if self.index >= len(self.data):
                    raise StopAsyncIteration
                item = self.data[self.index]
                self.index += 1
                return item

        return AsyncCursor(filtered)

    async def find_one_and_update(self, query, update, return_document=True):
        doc = await self.find_one(query)
        if not doc:
            return None
        if "$set" in update:
            for k, v in update["$set"].items():
                doc[k] = v
        for i, d in enumerate(self.docs):
            if d.get("strategy_id") == query.get("strategy_id") or d.get("version_id") == query.get("version_id"):
                self.docs[i] = dict(doc)
                break
        return doc

    async def update_one(self, query, update, upsert=False):
        doc = await self.find_one(query)
        if not doc:
            if upsert:
                new_doc = {}
                if "$set" in update:
                    new_doc.update(update["$set"])
                self.docs.append(new_doc)
                return True
            return False
        if "$set" in update:
            for k, v in update["$set"].items():
                doc[k] = v
        for i, d in enumerate(self.docs):
            match = True
            for k, v in query.items():
                if d.get(k) != v:
                    match = False
                    break
            if match:
                self.docs[i] = dict(doc)
                break
        return True


class FakeDB(dict):
    def __getitem__(self, item):
        if item not in self:
            self[item] = FakeCollection()
        return super().__getitem__(item)


@pytest.mark.asyncio
async def test_version_service_lifecycle():
    fake_db = FakeDB()
    repo = StrategyRepository(db=fake_db)
    service = VersionService(repo=repo)

    # 1. Create strategy draft
    strat, ver = await service.create_strategy(
        user_id="user_a",
        name="Momentum Alpha",
        description="Top momentum stocks",
        parameters={"top_k": 10}
    )
    assert strat.strategy_id.startswith("strat_")
    assert strat.status == StrategyStatus.DRAFT
    assert ver.version_num == 1
    assert ver.is_published is False

    # 2. Update draft
    updated_ver = await service.update_draft(
        strategy_id=strat.strategy_id,
        user_id="user_a",
        parameters={"top_k": 20},
        commit_message="Increase top_k"
    )
    assert updated_ver.version_num == 1
    assert updated_ver.parameters["top_k"] == 20

    # 3. Publish v1
    pub_ver = await service.publish_version(
        strategy_id=strat.strategy_id,
        user_id="user_a",
        commit_message="Initial v1 publish"
    )
    assert pub_ver.is_published is True
    assert pub_ver.published_at is not None

    strat_after_pub = await repo.get_strategy(strat.strategy_id)
    assert strat_after_pub.status == StrategyStatus.PUBLISHED
    assert strat_after_pub.published_version_num == 1

    # 4. Update draft after publishing -> automatically increments to v2 draft
    v2_draft = await service.update_draft(
        strategy_id=strat.strategy_id,
        user_id="user_a",
        parameters={"top_k": 15},
        commit_message="v2 draft"
    )
    assert v2_draft.version_num == 2
    assert v2_draft.is_published is False

    strat_v2 = await repo.get_strategy(strat.strategy_id)
    assert strat_v2.latest_version_num == 2
    assert strat_v2.status == StrategyStatus.DRAFT

    # 5. Clone strategy
    cloned_strat, cloned_ver = await service.clone_strategy(
        strategy_id=strat.strategy_id,
        user_id="user_b",
        new_name="User B Copy"
    )
    assert cloned_strat.user_id == "user_b"
    assert cloned_strat.name == "User B Copy"
    assert cloned_ver.parent_strategy_id == strat.strategy_id
    assert cloned_ver.parent_version_num == 2


@pytest.mark.asyncio
async def test_system_template_readonly_rules():
    fake_db = FakeDB()
    repo = StrategyRepository(db=fake_db)
    service = VersionService(repo=repo)

    sys_strat, sys_ver = await service.create_strategy(
        user_id="system",
        name="System Multi-Factor",
        is_system_template=True
    )

    # Attempt edit directly
    with pytest.raises(StrategyForbiddenError):
        await service.update_draft(sys_strat.strategy_id, user_id="user_a", parameters={"k": 1})

    # Attempt archive directly
    with pytest.raises(StrategyForbiddenError):
        await repo.archive_strategy(sys_strat.strategy_id, user_id="user_a")

    # Clone system template should succeed for user
    cloned_strat, cloned_ver = await service.clone_strategy(sys_strat.strategy_id, user_id="user_a")
    assert cloned_strat.user_id == "user_a"
    assert cloned_strat.is_system_template is False
    assert cloned_ver.parent_strategy_id == sys_strat.strategy_id
