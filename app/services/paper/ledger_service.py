import uuid
from typing import Optional
from app.models.paper import LedgerEntry, LedgerEntryType, PositionLot, OrderEvent
from app.repositories.paper_repository import PaperRepository
from app.utils.timezone import now_tz


class LedgerService:
    """复式记账与 Lot 交易撮合服务"""

    def __init__(self, repo: Optional[PaperRepository] = None):
        self.repo = repo or PaperRepository()

    async def execute_trade_buy(
        self,
        portfolio_id: str,
        symbol: str,
        quantity: int,
        price: float,
        commission: float,
        transfer_fee: float
    ) -> bool:
        """执行模拟买入：原子扣减现金并记账，更新 Lot"""
        total_cash_needed = (quantity * price) + commission + transfer_fee
        updated_p = await self.repo.update_cash_atomic(portfolio_id, -total_cash_needed)
        if not updated_p:
            return False

        # 记录分录
        now = now_tz()
        ref_id = f"buy_{uuid.uuid4().hex[:8]}"

        await self.repo.record_ledger_entry(LedgerEntry(
            entry_id=f"entry_{uuid.uuid4().hex[:12]}",
            portfolio_id=portfolio_id,
            entry_type=LedgerEntryType.TRADE_BUY,
            amount=-(quantity * price),
            balance_after=updated_p.cash + commission + transfer_fee,
            reference_id=ref_id,
            description=f"Buy {quantity} {symbol} @ {price}",
            created_at=now
        ))

        await self.repo.record_ledger_entry(LedgerEntry(
            entry_id=f"entry_{uuid.uuid4().hex[:12]}",
            portfolio_id=portfolio_id,
            entry_type=LedgerEntryType.COMMISSION,
            amount=-commission,
            balance_after=updated_p.cash + transfer_fee,
            reference_id=ref_id,
            description=f"Commission for buy {symbol}",
            created_at=now
        ))

        # 保存为新 Lot
        lot = PositionLot(
            lot_id=f"lot_{uuid.uuid4().hex[:12]}",
            portfolio_id=portfolio_id,
            symbol=symbol,
            quantity=quantity,
            t_plus_1_sellable_qty=0,  # 新买入当日为 0 (T+1 规则)
            buy_price=price,
            current_price=price,
            bought_at=now
        )
        await self.repo.save_lot(lot)

        return True
