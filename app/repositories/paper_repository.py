import uuid
from typing import Optional, List, Dict, Any
from app.core.database import get_mongo_db
from app.models.paper import PaperPortfolio, PositionLot, LedgerEntry, PortfolioReconciliation, LedgerEntryType
from app.utils.timezone import now_tz


class PaperRepository:
    """模拟组合、PositionLot 及 Ledger持久化 Repository (支持原子更新与对账)"""

    def __init__(self, db=None):
        self._db = db

    def get_db(self):
        return self._db if self._db is not None else get_mongo_db()

    async def create_portfolio(self, portfolio: PaperPortfolio) -> PaperPortfolio:
        db = self.get_db()
        await db["paper_portfolios"].insert_one(portfolio.model_dump())
        return portfolio

    async def get_portfolio(self, portfolio_id: str) -> Optional[PaperPortfolio]:
        db = self.get_db()
        doc = await db["paper_portfolios"].find_one({"portfolio_id": portfolio_id})
        if not doc:
            return None
        doc.pop("_id", None)
        return PaperPortfolio(**doc)

    async def update_cash_atomic(self, portfolio_id: str, delta_cash: float) -> Optional[PaperPortfolio]:
        """原子更新现金余额 (只在 cash + delta_cash >= 0 时成功)"""
        db = self.get_db()
        query = {"portfolio_id": portfolio_id}
        if delta_cash < 0:
            query["cash"] = {"$gte": abs(delta_cash)}

        res = await db["paper_portfolios"].find_one_and_update(
            query,
            {"$inc": {"cash": delta_cash}, "$set": {"updated_at": now_tz()}},
            return_document=True
        )
        if not res:
            return None
        res.pop("_id", None)
        return PaperPortfolio(**res)

    async def record_ledger_entry(self, entry: LedgerEntry) -> LedgerEntry:
        db = self.get_db()
        await db["paper_ledger"].insert_one(entry.model_dump())
        return entry

    async def list_lots(self, portfolio_id: str, symbol: Optional[str] = None) -> List[PositionLot]:
        db = self.get_db()
        query = {"portfolio_id": portfolio_id}
        if symbol:
            query["symbol"] = symbol

        cursor = db["paper_lots"].find(query)
        results = []
        async for doc in cursor:
            doc.pop("_id", None)
            results.append(PositionLot(**doc))
        return results

    async def save_lot(self, lot: PositionLot) -> PositionLot:
        db = self.get_db()
        await db["paper_lots"].update_one(
            {"lot_id": lot.lot_id},
            {"$set": lot.model_dump()},
            upsert=True
        )
        return lot

    async def reconcile(self, portfolio_id: str) -> PortfolioReconciliation:
        portfolio = await self.get_portfolio(portfolio_id)
        if not portfolio:
            raise ValueError(f"Portfolio {portfolio_id} not found")

        lots = await self.list_lots(portfolio_id)
        calc_mv = sum(l.quantity * l.current_price for l in lots)
        calc_equity = portfolio.cash + calc_mv

        db = self.get_db()
        cursor = db["paper_ledger"].find({"portfolio_id": portfolio_id})
        calc_cash = 0.0
        async for doc in cursor:
            calc_cash += doc.get("amount", 0.0)

        calc_cash = round(calc_cash, 2)
        cash_disc = round(portfolio.cash - calc_cash, 2)
        eq_disc = round(portfolio.total_equity - calc_equity, 2)

        return PortfolioReconciliation(
            portfolio_id=portfolio_id,
            is_balanced=(abs(cash_disc) <= 0.01 and abs(eq_disc) <= 0.01),
            calculated_equity=round(calc_equity, 2),
            recorded_equity=round(portfolio.total_equity, 2),
            equity_discrepancy=eq_disc,
            calculated_cash_balance=calc_cash,
            recorded_cash_balance=round(portfolio.cash, 2),
            cash_discrepancy=cash_disc,
            reconciled_at=now_tz()
        )
