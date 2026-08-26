import uuid
from typing import Dict, Any, List, Optional

from app.models.campaign import (
    Campaign,
    CampaignStatus,
    ExitReasonCode,
    CampaignRiskExitTrigger,
    CampaignRiskExitResult
)
from app.repositories.campaign_repository import CampaignRepository
from app.repositories.paper_repository import PaperRepository
from app.services.paper.ledger_service import LedgerService
from app.utils.timezone import now_tz


class CampaignRiskExitService:
    """Campaign 止损止盈、组合回撤与紧急暂停/确认恢复服务"""

    def __init__(
        self,
        campaign_repo: Optional[CampaignRepository] = None,
        paper_repo: Optional[PaperRepository] = None,
        ledger_service: Optional[LedgerService] = None
    ):
        self.campaign_repo = campaign_repo or CampaignRepository()
        self.paper_repo = paper_repo or PaperRepository()
        self.ledger_service = ledger_service or LedgerService()

    async def evaluate_risk_exits(
        self,
        campaign_id: str,
        positions: Dict[str, Dict[str, Any]],    # symbol -> {quantity, buy_price, current_price}
        current_drawdown: float = 0.0,
        stop_loss_pct: float = 0.10,            # 10% 止损
        take_profit_pct: float = 0.20           # 20% 止盈
    ) -> CampaignRiskExitResult:
        """
        评估持仓个股止损止盈及组合回撤风控平仓。
        """
        campaign = await self.campaign_repo.get_campaign(campaign_id)
        if not campaign or campaign.status != CampaignStatus.ACTIVATED:
            return CampaignRiskExitResult(campaign_id=campaign_id, has_risk_exit=False)

        triggers: List[CampaignRiskExitTrigger] = []
        exit_orders: List[Dict[str, Any]] = []
        should_pause = False
        now = now_tz()

        # 1. 组合回撤检查
        max_mdd_limit = campaign.risk_config_override.get("max_drawdown_limit", 0.15)
        if current_drawdown >= max_mdd_limit:
            should_pause = True
            triggers.append(CampaignRiskExitTrigger(
                trigger_id=f"trig_{uuid.uuid4().hex[:12]}",
                campaign_id=campaign_id,
                reason_code=ExitReasonCode.PORTFOLIO_DRAWDOWN_PAUSE,
                threshold_value=max_mdd_limit,
                current_value=round(current_drawdown, 4),
                action_taken="PAUSE_CAMPAIGN",
                detailed_message=f"组合最大回撤 {current_drawdown:.2%} 达到告警上限 {max_mdd_limit:.2%}，触发暂停保护",
                triggered_at=now
            ))

        # 2. 个股止损与止盈检查
        for sym, pos in positions.items():
            qty = pos.get("quantity", 0)
            buy_p = pos.get("buy_price", 0.0)
            curr_p = pos.get("current_price", 0.0)

            if qty <= 0 or buy_p <= 0:
                continue

            pnl_pct = (curr_p - buy_p) / buy_p

            # 止损逻辑
            if pnl_pct <= -stop_loss_pct:
                triggers.append(CampaignRiskExitTrigger(
                    trigger_id=f"trig_{uuid.uuid4().hex[:12]}",
                    campaign_id=campaign_id,
                    symbol=sym,
                    reason_code=ExitReasonCode.STOP_LOSS_TRIGGERED,
                    threshold_value=-stop_loss_pct,
                    current_value=round(pnl_pct, 4),
                    action_taken="FORCE_SELL_ALL",
                    detailed_message=f"股票 {sym} 跌幅 {pnl_pct:.2%} 达到止损上限 -{stop_loss_pct:.2%}，触发清仓卖出",
                    triggered_at=now
                ))
                exit_orders.append({"symbol": sym, "side": "sell", "quantity": qty, "price": curr_p, "reason": "STOP_LOSS"})

            # 止盈逻辑
            elif pnl_pct >= take_profit_pct:
                triggers.append(CampaignRiskExitTrigger(
                    trigger_id=f"trig_{uuid.uuid4().hex[:12]}",
                    campaign_id=campaign_id,
                    symbol=sym,
                    reason_code=ExitReasonCode.TAKE_PROFIT_TRIGGERED,
                    threshold_value=take_profit_pct,
                    current_value=round(pnl_pct, 4),
                    action_taken="FORCE_SELL_ALL",
                    detailed_message=f"股票 {sym} 涨幅 {pnl_pct:.2%} 达到止盈上限 +{take_profit_pct:.2%}，触发锁定利润卖出",
                    triggered_at=now
                ))
                exit_orders.append({"symbol": sym, "side": "sell", "quantity": qty, "price": curr_p, "reason": "TAKE_PROFIT"})

        if should_pause:
            await self.campaign_repo.update_campaign(
                campaign_id,
                {"status": CampaignStatus.PAUSED, "paused_at": now}
            )

        return CampaignRiskExitResult(
            campaign_id=campaign_id,
            has_risk_exit=len(triggers) > 0,
            should_pause=should_pause,
            triggers=triggers,
            exit_orders=exit_orders
        )

    async def resume_campaign(self, campaign_id: str, user_id: str, confirmation_note: str = "") -> Campaign:
        """用户显式确认并重新恢复 PAUSED Campaign 运行"""
        campaign = await self.campaign_repo.get_campaign(campaign_id)
        if not campaign or campaign.user_id != user_id:
            raise ValueError(f"Campaign {campaign_id} not found or forbidden")
        if campaign.status != CampaignStatus.PAUSED:
            raise ValueError(f"Campaign {campaign_id} is in status '{campaign.status}', cannot resume unless PAUSED")

        now = now_tz()
        updated = await self.campaign_repo.update_campaign(
            campaign_id,
            {"status": CampaignStatus.ACTIVATED, "updated_at": now}
        )
        return updated
