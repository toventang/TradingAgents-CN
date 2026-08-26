import uuid
from datetime import datetime, date
from typing import Optional, Dict, Any, Tuple

from app.models.campaign import Campaign, CampaignStatus, CampaignRevision, CampaignValidationResult
from app.repositories.campaign_repository import CampaignRepository, CampaignNotFoundError, CampaignForbiddenError
from app.repositories.strategy_repository import StrategyRepository
from app.repositories.paper_repository import PaperRepository
from app.utils.timezone import now_tz


class CampaignLifecycleError(Exception):
    """Campaign 生命周期与冻结校验异常"""
    pass


class CampaignLifecycleService:
    """Campaign 生命周期状态变迁与冻结规则管理"""

    def __init__(
        self,
        campaign_repo: Optional[CampaignRepository] = None,
        strategy_repo: Optional[StrategyRepository] = None,
        paper_repo: Optional[PaperRepository] = None
    ):
        self.campaign_repo = campaign_repo or CampaignRepository()
        self.strategy_repo = strategy_repo or StrategyRepository()
        self.paper_repo = paper_repo or PaperRepository()

    async def create_campaign_draft(
        self,
        user_id: str,
        name: str,
        strategy_id: str,
        strategy_version_num: int,
        portfolio_id: str,
        initial_allocation_cash: float,
        start_date: str,
        description: str = "",
        rebalance_frequency: str = "daily"
    ) -> Tuple[Campaign, CampaignRevision]:
        """新建 DRAFT Campaign"""
        cid = f"camp_{uuid.uuid4().hex[:12]}"
        rid = f"rev_{uuid.uuid4().hex[:12]}"
        now = now_tz()

        campaign = Campaign(
            campaign_id=cid,
            user_id=user_id,
            name=name,
            description=description,
            status=CampaignStatus.DRAFT,
            strategy_id=strategy_id,
            strategy_version_num=strategy_version_num,
            portfolio_id=portfolio_id,
            initial_allocation_cash=initial_allocation_cash,
            start_date=start_date,
            current_revision_num=1,
            rebalance_frequency=rebalance_frequency,
            created_at=now,
            updated_at=now
        )

        revision = CampaignRevision(
            revision_id=rid,
            campaign_id=cid,
            revision_num=1,
            rebalance_frequency=rebalance_frequency,
            commit_message="Initial campaign creation",
            created_at=now
        )

        c_created = await self.campaign_repo.create_campaign(campaign, revision)
        return c_created, revision

    async def validate_activation(self, campaign_id: str, user_id: str) -> CampaignValidationResult:
        """校验 Campaign 激活条件"""
        campaign = await self.campaign_repo.get_campaign(campaign_id)
        if not campaign:
            return CampaignValidationResult(is_valid=False, errors=[f"Campaign {campaign_id} not found"])
        if campaign.user_id != user_id:
            return CampaignValidationResult(is_valid=False, errors=["Forbidden: Not campaign owner"])

        errors = []
        warnings = []

        # 1. 校验策略与已发布版本存在
        strat = await self.strategy_repo.get_strategy(campaign.strategy_id)
        if not strat:
            errors.append(f"Strategy {campaign.strategy_id} not found")
        else:
            versions = await self.strategy_repo.list_versions(campaign.strategy_id)
            target_ver = next((v for v in versions if v.version_num == campaign.strategy_version_num), None)
            if not target_ver or not target_ver.is_published:
                errors.append(f"Strategy version {campaign.strategy_version_num} is not published or does not exist")

        # 2. 校验组合资金
        portfolio = await self.paper_repo.get_portfolio(campaign.portfolio_id)
        if not portfolio:
            errors.append(f"Portfolio {campaign.portfolio_id} not found")
        elif portfolio.cash < campaign.initial_allocation_cash:
            errors.append(f"Portfolio cash ({portfolio.cash}) is less than campaign allocation ({campaign.initial_allocation_cash})")

        # 3. 校验非追溯开始时间 (start_date >= today)
        today_str = now_tz().strftime("%Y-%m-%d")
        if campaign.start_date < today_str:
            errors.append(f"Retroactive start date {campaign.start_date} is prohibited; must be >= {today_str}")

        return CampaignValidationResult(is_valid=len(errors) == 0, errors=errors, warnings=warnings)

    async def activate_campaign(self, campaign_id: str, user_id: str) -> Campaign:
        """激活 Campaign，冻结核心字段 (strategy, portfolio, allocation_cash, start_date)"""
        val = await self.validate_activation(campaign_id, user_id)
        if not val.is_valid:
            raise CampaignLifecycleError(f"Activation validation failed: {'; '.join(val.errors)}")

        now = now_tz()
        updated = await self.campaign_repo.update_campaign(
            campaign_id,
            {"status": CampaignStatus.ACTIVATED, "activated_at": now, "updated_at": now}
        )
        return updated
