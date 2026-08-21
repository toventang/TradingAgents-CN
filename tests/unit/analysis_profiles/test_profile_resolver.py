import pytest
from app.models.analysis import AnalysisProfile, AnalysisProfileVersion, AnalysisDepth, RiskPreference, InvestmentHorizon
from app.repositories.analysis_profile_repository import AnalysisProfileRepository, AnalysisProfileNotFoundError
from app.services.analysis_profiles.resolver import AnalysisProfileResolver, AnalysisProfileConflictError


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
async def test_resolver_with_valid_profile_id():
    fake_db = FakeDB()
    repo = AnalysisProfileRepository(db=fake_db)
    resolver = AnalysisProfileResolver(repo=repo)

    profile = AnalysisProfile(profile_id="p_growth", user_id="u1", name="Growth Profile")
    version = AnalysisProfileVersion(
        version_id="v_growth_1",
        profile_id="p_growth",
        version_num=1,
        depth=AnalysisDepth.DEEP,
        risk_preference=RiskPreference.AGGRESSIVE,
        horizon=InvestmentHorizon.LONG_TERM
    )

    await repo.create_profile(profile, version)

    resolved = await resolver.resolve_profile(profile_id="p_growth")
    assert resolved.profile_id == "p_growth"
    assert resolved.depth == AnalysisDepth.DEEP
    assert resolved.risk_preference == RiskPreference.AGGRESSIVE


@pytest.mark.asyncio
async def test_resolver_conflict_detection():
    fake_db = FakeDB()
    repo = AnalysisProfileRepository(db=fake_db)
    resolver = AnalysisProfileResolver(repo=repo)

    profile = AnalysisProfile(profile_id="p_std", user_id="u1", name="Std Profile")
    version = AnalysisProfileVersion(
        version_id="v_std_1",
        profile_id="p_std",
        version_num=1,
        depth=AnalysisDepth.STANDARD
    )

    await repo.create_profile(profile, version)

    # Inline parameter says depth="quick", profile says depth="standard" -> conflict
    with pytest.raises(AnalysisProfileConflictError) as exc:
        await resolver.resolve_profile(profile_id="p_std", legacy_params={"depth": "quick"})

    assert "Conflicting depth" in str(exc.value)


@pytest.mark.asyncio
async def test_resolver_fallback_legacy_params():
    resolver = AnalysisProfileResolver()
    resolved = await resolver.resolve_profile(legacy_params={"depth": "deep", "risk_preference": "conservative"})
    assert resolved.depth == AnalysisDepth.DEEP
    assert resolved.risk_preference == RiskPreference.CONSERVATIVE
