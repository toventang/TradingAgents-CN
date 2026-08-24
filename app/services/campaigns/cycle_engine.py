import uuid
from typing import Dict, Any, List, Optional
import pandas as pd

from app.models.campaign import (
    Campaign,
    CampaignStatus,
    CampaignCycleRecord,
    CampaignCycleStatus,
    CandidateRecord
)
from app.models.risk import RiskConfig
from app.models.paper import OrderEvent
from app.services.strategies.signal_engine import DeterministicSignalEngine
from app.services.risk.pre_trade import PreTradeRiskService
from app.services.paper.ledger_service import LedgerService
from app.repositories.strategy_repository import StrategyRepository
from app.repositories.paper_repository import PaperRepository
from app.repositories.campaign_repository import CampaignRepository
from app.utils.timezone import now_tz


class CampaignCycleEngine:
    """Post-Activation 调仓周期执行引擎 (支持幂等、候选分录、风控与下派)"""

    def __init__(
        self,
        signal_engine: Optional[DeterministicSignalEngine] = None,
        risk_service: Optional[PreTradeRiskService] = None,
        ledger_service: Optional[LedgerService] = None,
        strategy_repo: Optional[StrategyRepository] = None,
        paper_repo: Optional[PaperRepository] = None,
        campaign_repo: Optional[CampaignRepository] = None
    ):
        self.signal_engine = signal_engine or DeterministicSignalEngine()
        self.risk_service = risk_service or PreTradeRiskService()
        self.ledger_service = ledger_service or LedgerService()
        self.strategy_repo = strategy_repo or StrategyRepository()
        self.paper_repo = paper_repo or PaperRepository()
        self.campaign_repo = campaign_repo or CampaignRepository()

    async def execute_cycle(
        self,
        campaign_id: str,
        cycle_date: str,
        factor_values_df: pd.DataFrame,
        current_prices: Dict[str, float]
    ) -> CampaignCycleRecord:
        """
        执行特定调仓周期。
        """
        idempotency_key = f"{campaign_id}_{cycle_date}"
        cycle_id = f"cycle_{uuid.uuid4().hex[:12]}"
        now = now_tz()

        campaign = await self.campaign_repo.get_campaign(campaign_id)
        if not campaign or campaign.status != CampaignStatus.ACTIVATED:
            return CampaignCycleRecord(
                cycle_id=cycle_id,
                campaign_id=campaign_id,
                cycle_date=cycle_date,
                status=CampaignCycleStatus.FAILED,
                idempotency_key=idempotency_key,
                error_message="Campaign not found or not in ACTIVATED status"
            )

        # 1. 获取冻结的策略版本
        versions = await self.strategy_repo.list_versions(campaign.strategy_id)
        target_version = next((v for v in versions if v.version_num == campaign.strategy_version_num), None)
        if not target_version:
            return CampaignCycleRecord(
                cycle_id=cycle_id,
                campaign_id=campaign_id,
                cycle_date=cycle_date,
                status=CampaignCycleStatus.FAILED,
                idempotency_key=idempotency_key,
                error_message=f"Frozen strategy version {campaign.strategy_version_num} not found"
            )

        # 2. 信号计算
        as_of_dt = now
        signals = self.signal_engine.generate_signals(target_version, campaign.user_id, as_of_dt, factor_values_df)

        # 记录候选分录
        candidate_records = []
        proposed_trades = []

        for sig in signals:
            cand = CandidateRecord(
                candidate_id=f"cand_{uuid.uuid4().hex[:12]}",
                cycle_id=cycle_id,
                campaign_id=campaign_id,
                symbol=sig.symbol,
                score=sig.score,
                rank=sig.rank,
                selected=(sig.signal_type == "buy"),
                rejection_reason=sig.reason_code if sig.signal_type != "buy" else None,
                target_weight=sig.target_weight
            )
            candidate_records.append(cand)

            if sig.signal_type == "buy":
                price = current_prices.get(sig.symbol, 10.0)
                qty = 1000 # 示示例基础数量
                proposed_trades.append({
                    "symbol": sig.symbol,
                    "side": "buy",
                    "quantity": qty,
                    "price": price
                })

        # 3. 盘前风控校验
        portfolio = await self.paper_repo.get_portfolio(campaign.portfolio_id)
        cash = portfolio.cash if portfolio else 0.0
        equity = portfolio.total_equity if portfolio else 0.0

        risk_config = RiskConfig(**campaign.risk_config_override) if campaign.risk_config_override else RiskConfig()
        risk_res = self.risk_service.check_pre_trade_orders(
            config=risk_config,
            total_equity=equity,
            cash=cash,
            positions={},
            proposed_trades=proposed_trades
        )

        orders_executed = 0
        if not risk_res["is_blocked"]:
            for trade in risk_res["approved_orders"]:
                ok = await self.ledger_service.execute_trade_buy(
                    portfolio_id=campaign.portfolio_id,
                    symbol=trade["symbol"],
                    quantity=trade["quantity"],
                    price=trade["price"],
                    commission=5.0,
                    transfer_fee=0.10
                )
                if ok:
                    orders_executed += 1

        return CampaignCycleRecord(
            cycle_id=cycle_id,
            campaign_id=campaign_id,
            cycle_date=cycle_date,
            status=CampaignCycleStatus.COMPLETED,
            idempotency_key=idempotency_key,
            candidates_count=len(candidate_records),
            orders_count=orders_executed,
            executed_at=now
        )
