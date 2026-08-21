from typing import Optional, Dict, Any
from app.models.analysis import AnalysisProfileVersion, AnalysisDepth, RiskPreference, InvestmentHorizon
from app.repositories.analysis_profile_repository import AnalysisProfileRepository, AnalysisProfileNotFoundError


class AnalysisProfileConflictError(Exception):
    """Profile 与 Legacy 参数冲突异常"""
    pass


class AnalysisProfileResolver:
    """分析 Profile 解析与兼容层：统一解析 profile_id 与 legacy 内联参数"""

    def __init__(self, repo: Optional[AnalysisProfileRepository] = None):
        self.repo = repo or AnalysisProfileRepository()

    async def resolve_profile(
        self,
        profile_id: Optional[str] = None,
        legacy_params: Optional[Dict[str, Any]] = None
    ) -> AnalysisProfileVersion:
        """
        解析并校验获取生效的 AnalysisProfileVersion。
        - 若同时传入 profile_id 与 legacy_params 且存在属性矛盾，抛出 AnalysisProfileConflictError 显式拒绝；
        - 若仅有 profile_id，加载最新版本 Profile；
        - 若仅有 legacy_params，构建默认兼容 Profile；
        - 若二者均未提供，返回默认标准 Profile。
        """
        legacy = legacy_params or {}

        if profile_id:
            profile_ver = await self.repo.get_latest_version(profile_id)
            if not profile_ver:
                raise AnalysisProfileNotFoundError(f"AnalysisProfile '{profile_id}' not found")

            # 校验冲突: 若 legacy_params 中指定了与 Profile 不一致的深度/风控偏好/期限
            if "depth" in legacy and legacy["depth"] != profile_ver.depth.value:
                raise AnalysisProfileConflictError(
                    f"Conflicting depth parameter: inline '{legacy['depth']}' vs profile '{profile_ver.depth.value}'"
                )
            if "risk_preference" in legacy and legacy["risk_preference"] != profile_ver.risk_preference.value:
                raise AnalysisProfileConflictError(
                    f"Conflicting risk_preference parameter: inline '{legacy['risk_preference']}' vs profile '{profile_ver.risk_preference.value}'"
                )
            if "horizon" in legacy and legacy["horizon"] != profile_ver.horizon.value:
                raise AnalysisProfileConflictError(
                    f"Conflicting horizon parameter: inline '{legacy['horizon']}' vs profile '{profile_ver.horizon.value}'"
                )

            return profile_ver

        # 无 profile_id 时，依据 legacy_params 转换
        depth_val = legacy.get("depth", AnalysisDepth.STANDARD.value)
        risk_val = legacy.get("risk_preference", RiskPreference.BALANCED.value)
        horizon_val = legacy.get("horizon", InvestmentHorizon.MEDIUM_TERM.value)

        return AnalysisProfileVersion(
            version_id="v_inline_default",
            profile_id="p_inline_default",
            version_num=1,
            analysts=legacy.get("analysts", ["market_analyst", "fundamentals_analyst", "technical_analyst", "risk_analyst"]),
            depth=AnalysisDepth(depth_val),
            risk_preference=RiskPreference(risk_val),
            horizon=InvestmentHorizon(horizon_val),
            factor_context_limits=legacy.get("factor_context_limits", 20),
            debate_limits={"max_rounds": legacy.get("max_rounds", 3), "max_tokens": legacy.get("max_tokens", 4096)}
        )
