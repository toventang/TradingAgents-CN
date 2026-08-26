import uuid
from typing import Dict, Any, List, Optional

from app.models.attribution import (
    AITradeReview,
    LearningProposal,
    ProposalStatus,
    ProposalDiffItem,
    CauseCategory
)
from app.models.strategy import StrategyVersion
from app.repositories.strategy_repository import StrategyRepository
from app.services.strategies.version_service import VersionService
from app.utils.timezone import now_tz


# 允许修订单可调白名单参数路径
ALLOWED_TUNABLE_PATHS = {
    "rules.top_k",
    "parameters.weights.ret_1d",
    "parameters.weights.ret_5d",
    "parameters.weights.ret_20d",
    "rules.stop_loss_pct"
}


class LearningProposalService:
    """受控学习提议服务：样本门控、白名单差异比较与新策略草稿生成"""

    def __init__(self, strategy_repo: Optional[StrategyRepository] = None):
        self.strategy_repo = strategy_repo or StrategyRepository()

    def generate_proposal_from_reviews(
        self,
        campaign_id: str,
        strategy_id: str,
        reviews: List[AITradeReview],
        current_strategy_version: StrategyVersion,
        min_sample_gate: int = 5
    ) -> LearningProposal:
        """
        在复盘样本数达标（>= min_sample_gate）时生成可审阅的调参提议。
        """
        proposal_id = f"prop_{uuid.uuid4().hex[:12]}"
        now = now_tz()

        if len(reviews) < min_sample_gate:
            return LearningProposal(
                proposal_id=proposal_id,
                campaign_id=campaign_id,
                strategy_id=strategy_id,
                status=ProposalStatus.REJECTED,
                sample_count=len(reviews),
                diff_items=[],
                created_at=now,
                updated_at=now
            )

        # 统计复盘主因
        cause_counts: Dict[str, int] = {}
        for r in reviews:
            # 假定从 diagnosis 提取原因或统一频次
            cause_counts["FACTOR_TIMING"] = cause_counts.get("FACTOR_TIMING", 0) + 1

        diff_items = []

        # 针对建议进行白名单调参
        if cause_counts.get("FACTOR_TIMING", 0) >= 3:
            curr_top_k = current_strategy_version.rules.get("top_k", 10)
            proposed_top_k = max(3, curr_top_k - 2)

            diff_items.append(ProposalDiffItem(
                parameter_path="rules.top_k",
                current_value=curr_top_k,
                proposed_value=proposed_top_k,
                reasoning="缩减持仓 top_k 以提高高动量因子选股胜率，减少边缘股票择时误伤"
            ))

        return LearningProposal(
            proposal_id=proposal_id,
            campaign_id=campaign_id,
            strategy_id=strategy_id,
            status=ProposalStatus.PROPOSED,
            sample_count=len(reviews),
            diff_items=diff_items,
            created_at=now,
            updated_at=now
        )

    async def apply_proposal_to_new_draft(
        self,
        proposal: LearningProposal,
        user_id: str
    ) -> StrategyVersion:
        """
        将经过用户部分/全额批准的提议应用生成【全新策略草稿版本】，绝不自动发布或修改运行中的 Campaign。
        """
        version_service = VersionService(repo=self.strategy_repo)
        strat_ver = await self.strategy_repo.get_latest_version(proposal.strategy_id)
        if not strat_ver:
            raise ValueError(f"Strategy {proposal.strategy_id} has no existing version")

        params = dict(strat_ver.parameters)
        rules = dict(strat_ver.rules)

        # 仅应用标记为 approved 的白名单修改项
        for item in proposal.diff_items:
            if not item.approved:
                continue
            path = item.parameter_path
            val = item.proposed_value

            if path not in ALLOWED_TUNABLE_PATHS:
                continue

            if path == "rules.top_k":
                rules["top_k"] = val
            elif path.startswith("parameters.weights."):
                factor_id = path.replace("parameters.weights.", "")
                if "weights" not in params:
                    params["weights"] = {}
                params["weights"][factor_id] = val

        # 递增版本生成新草稿
        new_draft = await version_service.update_draft(
            strategy_id=proposal.strategy_id,
            user_id=user_id,
            parameters=params,
            rules=rules,
            commit_message=f"Created from approved learning proposal {proposal.proposal_id}"
        )
        return new_draft
