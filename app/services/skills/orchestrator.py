import time
import uuid
from typing import Dict, Any, Optional, List
from app.models.skill_orchestration import (
    SkillOrchestrationPlan,
    SkillOrchestrationResult,
    SkillDAGStep,
    SkillBudgetConfig
)
from app.services.skills.sandbox import PythonSandboxEngine
from app.services.skills.registry import SkillRegistry
from app.utils.timezone import now_tz


class SkillOrchestrator:
    """Skill 编排引擎：支持 DAG 步骤依赖传递、预算控制、降级容错与只读保护"""

    def __init__(self, registry: Optional[SkillRegistry] = None, sandbox: Optional[PythonSandboxEngine] = None):
        self.registry = registry or SkillRegistry()
        self.sandbox = sandbox or PythonSandboxEngine()
        self.cache: Dict[str, Dict[str, Any]] = {}

    async def execute_plan(
        self,
        plan: SkillOrchestrationPlan,
        initial_inputs: Optional[Dict[str, Any]] = None
    ) -> SkillOrchestrationResult:
        orch_id = f"orch_{uuid.uuid4().hex[:12]}"
        start_time = time.time()
        inputs = initial_inputs or {}

        if len(plan.steps) > plan.budget.max_steps_limit:
            return SkillOrchestrationResult(
                orchestration_id=orch_id,
                plan_id=plan.plan_id,
                success=False,
                error_message=f"Budget Exceeded: Step count {len(plan.steps)} exceeds limit {plan.budget.max_steps_limit}"
            )

        step_results: Dict[str, Any] = {}
        failed_steps: List[str] = []

        for step in plan.steps:
            # 检查总超时预算
            elapsed = time.time() - start_time
            if elapsed > plan.budget.max_total_timeout_sec:
                return SkillOrchestrationResult(
                    orchestration_id=orch_id,
                    plan_id=plan.plan_id,
                    success=False,
                    step_results=step_results,
                    failed_steps=failed_steps,
                    total_execution_time_ms=elapsed * 1000,
                    error_message=f"Budget Timeout Exceeded: Total time {elapsed:.2f}s exceeded limit {plan.budget.max_total_timeout_sec}s"
                )

            # 组装输入数据 (合并 static_inputs 与 upstream 依赖输出)
            step_inputs = dict(step.static_inputs)
            for up_key, param_name in step.input_mapping.items():
                if "." in up_key:
                    up_step, up_field = up_key.split(".", 1)
                    if up_step in step_results and isinstance(step_results[up_step], dict):
                        step_inputs[param_name] = step_results[up_step].get(up_field)
                elif up_key in inputs:
                    step_inputs[param_name] = inputs[up_key]

            # 获取 Skill 代码
            version = await self.registry.get_latest_version(step.skill_id)
            if not version:
                failed_steps.append(step.step_id)
                if step.is_critical or not plan.budget.allow_fallback:
                    return SkillOrchestrationResult(
                        orchestration_id=orch_id,
                        plan_id=plan.plan_id,
                        success=False,
                        step_results=step_results,
                        failed_steps=failed_steps,
                        total_execution_time_ms=(time.time() - start_time) * 1000,
                        error_message=f"Step '{step.step_id}' failed: Skill '{step.skill_id}' not found"
                    )
                continue

            # 评估缓存
            cache_key = f"{step.skill_id}_{version.version_num}_{hash(str(step_inputs))}"
            if plan.budget.enable_cache and cache_key in self.cache:
                step_results[step.step_id] = self.cache[cache_key]
                continue

            # 沙箱安全执行
            exec_res = self.sandbox.execute_skill(
                skill_id=step.skill_id,
                version_num=version.version_num,
                code=version.code,
                kwargs=step_inputs
            )

            if exec_res.success:
                step_results[step.step_id] = exec_res.result
                if plan.budget.enable_cache and exec_res.result:
                    self.cache[cache_key] = exec_res.result
            else:
                failed_steps.append(step.step_id)
                if step.is_critical or not plan.budget.allow_fallback:
                    return SkillOrchestrationResult(
                        orchestration_id=orch_id,
                        plan_id=plan.plan_id,
                        success=False,
                        step_results=step_results,
                        failed_steps=failed_steps,
                        total_execution_time_ms=(time.time() - start_time) * 1000,
                        error_message=f"Critical step '{step.step_id}' failed: {exec_res.error_message}"
                    )

        total_time = (time.time() - start_time) * 1000

        return SkillOrchestrationResult(
            orchestration_id=orch_id,
            plan_id=plan.plan_id,
            success=len(failed_steps) == 0 or plan.budget.allow_fallback,
            step_results=step_results,
            failed_steps=failed_steps,
            total_execution_time_ms=round(total_time, 2),
            executed_at=now_tz()
        )
