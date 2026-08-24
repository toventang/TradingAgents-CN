import pytest
from app.models.analysis import AnalysisProfileVersion
from app.models.skill import SkillType
from app.services.skills.registry import SkillRegistry
from app.services.skills.orchestrator import SkillOrchestrator
from app.services.skills.profile_integration import SkillProfileIntegrationService


class FakeCollection:
    def __init__(self):
        self.docs = []

    async def insert_one(self, doc):
        self.docs.append(dict(doc))
        return True

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
async def test_profile_skill_integration_with_evidence_injection():
    db = FakeDB()
    registry = SkillRegistry(db=db)

    code = "def run(inputs):\n    return {'market_status': 'BULL'}"
    skill, _ = await registry.create_skill("u1", "Market Skill", code, skill_type=SkillType.MARKET)

    orchestrator = SkillOrchestrator(registry=registry)
    service = SkillProfileIntegrationService(orchestrator=orchestrator)

    profile_ver = AnalysisProfileVersion(
        version_id="v_prof_1",
        profile_id="p_1",
        future_skill_refs=[skill.skill_id]
    )

    res = await service.resolve_and_execute_profile_skills(profile_ver)

    assert res["has_skills"] is True
    assert "BULL" in res["evidence_summary"]
    assert len(res["warnings"]) == 0


@pytest.mark.asyncio
async def test_profile_skill_integration_legacy_fallback_warning():
    service = SkillProfileIntegrationService()

    profile_ver_no_skills = AnalysisProfileVersion(
        version_id="v_prof_2",
        profile_id="p_2",
        future_skill_refs=[]
    )

    res = await service.resolve_and_execute_profile_skills(profile_ver_no_skills)

    assert res["has_skills"] is False
    assert len(res["warnings"]) > 0
    assert "legacy mode" in res["warnings"][0]
