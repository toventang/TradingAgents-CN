import pytest
from app.models.attribution import AITradeReview, EvidenceGrounding, ReviewConfidence, ProposalStatus
from app.models.strategy import Strategy, StrategyVersion, StrategyStatus
from app.repositories.strategy_repository import StrategyRepository
from app.services.learning.proposals import LearningProposalService


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

    async def find_one_and_update(self, query, update, return_document=True):
        doc = await self.find_one(query)
        if not doc:
            return None
        if "$set" in update:
            for k, v in update["$set"].items():
                doc[k] = v
        return doc


class FakeDB(dict):
    def __getitem__(self, item):
        if item not in self:
            self[item] = FakeCollection()
        return super().__getitem__(item)


@pytest.mark.asyncio
async def test_learning_proposal_sample_gate_and_draft_creation():
    db = FakeDB()
    s_repo = StrategyRepository(db=db)
    service = LearningProposalService(strategy_repo=s_repo)

    # 1. Prepare base strategy
    strat = Strategy(strategy_id="strat_learn", user_id="u_learn", name="Base Strategy", status=StrategyStatus.PUBLISHED)
    ver = StrategyVersion(version_id="v_learn_1", strategy_id="strat_learn", version_num=1, is_published=True, rules={"top_k": 10})
    await s_repo.create_strategy(strat)
    await s_repo.save_version(ver)

    # Fake reviews list
    reviews = [
        AITradeReview(
            review_id=f"r_{i}",
            trade_id=f"t_{i}",
            symbol="600000.SH",
            summary="test",
            diagnosis="test",
            grounding=EvidenceGrounding(),
            confidence=ReviewConfidence.HIGH,
            controllability_score=0.8
        ) for i in range(5)
    ]

    # 2. Sample gate check: < 5 reviews -> REJECTED
    prop_insufficient = service.generate_proposal_from_reviews("c1", "strat_learn", reviews[:3], ver, min_sample_gate=5)
    assert prop_insufficient.status == ProposalStatus.REJECTED

    # 3. Sample gate check: >= 5 reviews -> PROPOSED with diff items
    prop_valid = service.generate_proposal_from_reviews("c1", "strat_learn", reviews, ver, min_sample_gate=5)
    assert prop_valid.status == ProposalStatus.PROPOSED
    assert len(prop_valid.diff_items) >= 1
    assert prop_valid.diff_items[0].proposed_value == 8

    # 4. Apply proposal -> creates new DRAFT version v2 without mutating v1
    new_draft = await service.apply_proposal_to_new_draft(prop_valid, "u_learn")
    assert new_draft.version_num == 2
    assert new_draft.is_published is False
    assert new_draft.rules["top_k"] == 8
