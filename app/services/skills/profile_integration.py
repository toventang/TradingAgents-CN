from typing import Dict, Any, List, Optional
from app.models.analysis import AnalysisProfileVersion
from app.models.skill import SkillExecutionResult
from app.services.skills.orchestrator import SkillOrchestrator
from app.models.skill_orchestration import SkillOrchestrationPlan, SkillDAGStep


class SkillProfileIntegrationService:
    """AnalysisProfile 运行时 Skill 解析与 LangGraph 上下文证据注入服务"""

    def __init__(self, orchestrator: Optional[SkillOrchestrator] = None):
        self.orchestrator = orchestrator or SkillOrchestrator()

    async def resolve_and_execute_profile_skills(
        self,
        profile_version: AnalysisProfileVersion,
        inputs: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        解析 Profile 中声明的 future_skill_refs，执行 Skill DAG 并构建证据摘要与警告信息。
        """
        skill_refs = profile_version.future_skill_refs or []
        warnings = []

        if not skill_refs:
            warnings.append("WARNING: Running in legacy mode without runtime Skill evidence")
            return {
                "has_skills": False,
                "evidence_summary": "",
                "evidence_logs": [],
                "warnings": warnings
            }

        # 构建 Skill 编排计划
        steps = [
            SkillDAGStep(step_id=f"step_{sk_id}", skill_id=sk_id, is_critical=False)
            for sk_id in skill_refs
        ]
        plan = SkillOrchestrationPlan(plan_id=f"plan_{profile_version.profile_id}", steps=steps)

        orch_res = await self.orchestrator.execute_plan(plan, initial_inputs=inputs)

        evidence_summary_lines = []
        for step_id, res_data in orch_res.step_results.items():
            evidence_summary_lines.append(f"[{step_id} Result]: {res_data}")

        evidence_summary = "\n".join(evidence_summary_lines)

        return {
            "has_skills": True,
            "evidence_summary": evidence_summary,
            "evidence_logs": orch_res.step_results,
            "failed_steps": orch_res.failed_steps,
            "warnings": warnings
        }
