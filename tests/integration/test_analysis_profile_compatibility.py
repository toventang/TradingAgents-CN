import pytest
from app.models.analysis import AnalysisProfile, AnalysisProfileVersion, AnalysisDepth, RiskPreference, InvestmentHorizon
from app.repositories.analysis_profile_repository import AnalysisProfileRepository, AnalysisProfileNotFoundError
from app.services.analysis_profiles.resolver import AnalysisProfileResolver, AnalysisProfileConflictError


@pytest.mark.asyncio
async def test_full_analysis_profile_compatibility_flow():
    fake_docs = []

    class MockCollection:
        async def insert_one(self, doc):
            fake_docs.append(dict(doc))
            return True

        def find(self, query):
            results = [dict(d) for d in fake_docs if all(d.get(k) == v for k, v in query.items())]

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

            return Cursor(results)

    class MockDB(dict):
        def __getitem__(self, item):
            if item not in self:
                self[item] = MockCollection()
            return super().__getitem__(item)

    db = MockDB()
    repo = AnalysisProfileRepository(db=db)
    resolver = AnalysisProfileResolver(repo=repo)

    p = AnalysisProfile(profile_id="p_integration", user_id="u_dev", name="Integration Profile")
    v = AnalysisProfileVersion(
        version_id="v_integration_1",
        profile_id="p_integration",
        version_num=1,
        depth=AnalysisDepth.DEEP,
        risk_preference=RiskPreference.BALANCED,
        horizon=InvestmentHorizon.MEDIUM_TERM
    )

    await repo.create_profile(p, v)

    # 1. Resolve created profile
    res1 = await resolver.resolve_profile(profile_id="p_integration")
    assert res1.profile_id == "p_integration"
    assert res1.depth == AnalysisDepth.DEEP

    # 2. Reject non-existent profile_id
    with pytest.raises(AnalysisProfileNotFoundError):
        await resolver.resolve_profile(profile_id="non_existent")

    # 3. Reject conflicting inline params
    with pytest.raises(AnalysisProfileConflictError):
        await resolver.resolve_profile(profile_id="p_integration", legacy_params={"risk_preference": "aggressive"})
