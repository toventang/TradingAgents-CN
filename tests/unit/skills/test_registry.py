import pytest
from app.models.skill import SkillStatus, SkillType
from app.services.skills.registry import SkillRegistry


class FakeCollection:
    def __init__(self):
        self.docs = []

    async def insert_one(self, doc):
        self.docs.append(dict(doc))
        return True

    async def find_one(self, query):
        for d in self.docs:
            if all(d.get(k) == v for k, v in query.items()):
                return dict(d)
        return None

    def find(self, query):
        filtered = [dict(d) for d in self.docs if all(d.get(k) == v for k, v in query.items())]

        class Cursor:
            def __init__(self, items):
                self.items = items

            def sort(self, k, d=1):
                self.items.sort(key=lambda x: x.get(k, 0), reverse=(d == -1))
                return self

            def limit(self, n):
                self.items = self.items[:n]
                return self

            def __aiter__(self):
                return self._gen()

            async def _gen(self):
                for item in self.items:
                    yield item

        return Cursor(filtered)


class FakeDB(dict):
    def __getitem__(self, item):
        if item not in self:
            self[item] = FakeCollection()
        return super().__getitem__(item)


@pytest.mark.asyncio
async def test_skill_registry_creation():
    db = FakeDB()
    registry = SkillRegistry(db=db)

    code = "def run(inputs):\n    return {'status': 'ok'}"
    skill, ver = await registry.create_skill(
        user_id="user_skill_1",
        name="Market Regime Detector",
        code=code,
        skill_type=SkillType.MARKET
    )

    assert skill.skill_id.startswith("skill_")
    assert skill.status == SkillStatus.DRAFT
    assert ver.version_num == 1
    assert ver.checksum != ""

    s_get = await registry.get_skill(skill.skill_id)
    assert s_get.name == "Market Regime Detector"
