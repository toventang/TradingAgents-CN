import pytest
from app.models.strategy import Strategy, StrategyVersion, StrategyStatus, StrategyType, UniverseSnapshot
from app.repositories.strategy_repository import StrategyRepository, StrategyForbiddenError, StrategyNotFoundError
from app.services.strategies.version_service import VersionService


@pytest.mark.asyncio
async def test_full_strategy_versioning_and_cloning_flow():
    # Test fake in-memory repository behavior end to end
    fake_db = {}

    class SimpleCol:
        def __init__(self):
            self.docs = []

        async def insert_one(self, doc):
            self.docs.append(dict(doc))

        async def find_one(self, query):
            for d in self.docs:
                if all(d.get(k) == v for k, v in query.items()):
                    return dict(d)
            return None

        def find(self, query):
            results = [dict(d) for d in self.docs if all(d.get(k) == v for k, v in query.items())]
            class Cursor:
                def __init__(self, items):
                    self.items = items
                def sort(self, k, d=1):
                    self.items.sort(key=lambda x: x.get(k, 0), reverse=(d == -1))
                    return self
                def limit(self, n):
                    self.items = self.items[:n]
                    return self
                def skip(self, n):
                    self.items = self.items[n:]
                    return self
                def __aiter__(self):
                    return self._gen()
                async def _gen(self):
                    for item in self.items:
                        yield item
            return Cursor(results)

        async def find_one_and_update(self, query, update, return_document=True):
            doc = await self.find_one(query)
            if not doc:
                return None
            if "$set" in update:
                for k, v in update["$set"].items():
                    doc[k] = v
            for i, d in enumerate(self.docs):
                if all(d.get(k) == query.get(k) for k in query):
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
                if all(d.get(k) == query.get(k) for k in query):
                    self.docs[i] = dict(doc)
                    break
            return True

    class SimpleDB(dict):
        def __getitem__(self, item):
            if item not in self:
                self[item] = SimpleCol()
            return super().__getitem__(item)

    db = SimpleDB()
    repo = StrategyRepository(db=db)
    service = VersionService(repo=repo)

    # 1. Create a strategy
    strat, ver = await service.create_strategy(
        user_id="user_123",
        name="Value Factor Strategy",
        description="Select low PB stocks",
        strategy_type=StrategyType.FACTOR_MODEL,
        parameters={"weights": {"pb_ratio": -1.0}},
        rules={"top_percent": 0.1},
        universe=UniverseSnapshot(universe_id="univ_hs300", user_id="user_123", symbols=["600000.SH", "000001.SZ"])
    )

    assert strat.strategy_id.startswith("strat_")
    assert ver.version_num == 1
    assert ver.checksum != ""
    assert ver.universe.symbols == ["600000.SH", "000001.SZ"]

    # 2. Publish v1
    pub_ver = await service.publish_version(strat.strategy_id, user_id="user_123", commit_message="Release v1")
    assert pub_ver.is_published is True
    assert pub_ver.published_at is not None

    # 3. Create v2 draft automatically by editing after publication
    v2_draft = await service.update_draft(
        strategy_id=strat.strategy_id,
        user_id="user_123",
        parameters={"weights": {"pb_ratio": -0.8, "pe_ratio": -0.2}},
        commit_message="Add PE ratio"
    )

    assert v2_draft.version_num == 2
    assert v2_draft.is_published is False
    assert v2_draft.parameters["weights"]["pe_ratio"] == -0.2

    # 4. Clone strategy by another user
    cloned_strat, cloned_ver = await service.clone_strategy(
        strategy_id=strat.strategy_id,
        user_id="user_456",
        new_name="Cloned Value Strategy"
    )

    assert cloned_strat.user_id == "user_456"
    assert cloned_strat.name == "Cloned Value Strategy"
    assert cloned_ver.parent_strategy_id == strat.strategy_id
    assert cloned_ver.parent_version_num == 2
    assert cloned_ver.version_num == 1
