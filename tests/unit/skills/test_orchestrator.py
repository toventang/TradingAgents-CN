import pytest
from app.models.skill import SkillStatus, SkillType
from app.models.skill_orchestration import SkillOrchestrationPlan, SkillDAGStep, SkillBudgetConfig
from app.services.skills.registry import SkillRegistry
from app.services.skills.orchestrator import SkillOrchestrator


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
async def test_orchestrator_dag_execution_and_fallback():
    db = FakeDB()
    registry = SkillRegistry(db=db)

    # 注册两个技能
    code1 = "def run(inputs):\n    return {'regime': 'BULL'}"
    sk1, _ = await registry.create_skill("u1", "Market Skill", code1, skill_type=SkillType.MARKET)

    code2 = "def run(inputs):\n    r = inputs.get('regime')\n    return {'action': 'BUY' if r == 'BULL' else 'HOLD'}"
    sk2, _ = await registry.create_skill("u1", "Action Skill", code2, skill_type=SkillType.COMPOSITE)

    # 编排计划
    plan = SkillOrchestrationPlan(
        plan_id="plan_001",
        steps=[
            SkillDAGStep(step_id="step_market", skill_id=sk1.skill_id, is_critical=True),
            SkillDAGStep(
                step_id="step_action",
                skill_id=sk2.skill_id,
                input_mapping={"step_market.regime": "regime"},
                is_critical=True
            )
        ],
        budget=SkillBudgetConfig(max_total_timeout_sec=5.0, max_steps_limit=10)
    )

    orchestrator = SkillOrchestrator(registry=registry)
    res = await orchestrator.execute_plan(plan)

    assert res.success is True
    assert res.step_results["step_market"]["regime"] == "BULL"
    assert res.step_results["step_action"]["action"] == "BUY"


@pytest.mark.asyncio
async def test_orchestrator_budget_step_limit_exceeded():
    registry = SkillRegistry()
    orchestrator = SkillOrchestrator(registry=registry)

    plan = SkillOrchestrationPlan(
        plan_id="plan_exceeded",
        steps=[SkillDAGStep(step_id=f"step_{i}", skill_id="dummy") for i in range(5)],
        budget=SkillBudgetConfig(max_steps_limit=3)
    )

    res = await orchestrator.execute_plan(plan)
    assert res.success is False
    assert "Budget Exceeded" in res.error_message
