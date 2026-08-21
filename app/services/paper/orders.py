"""Filled-order and trade persistence compatible with existing collections."""

from typing import Any, Optional

from app.models.paper import PaperSymbol


class MongoPaperOrderService:
    def __init__(self, database: Any):
        self.database = database

    @staticmethod
    def fill_documents(
        *,
        user_id: str,
        identity: PaperSymbol,
        side: str,
        quantity: int,
        price: float,
        amount: float,
        commission: float,
        realized_pnl: float,
        timestamp: str,
        analysis_id: Optional[str],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        common = {
            "user_id": user_id,
            "code": identity.code,
            "market": identity.market.value,
            "currency": identity.currency.value,
            "side": side,
            "quantity": quantity,
            "price": price,
            "amount": amount,
            "commission": commission,
        }
        order = {
            **common,
            "status": "filled",
            "created_at": timestamp,
            "filled_at": timestamp,
        }
        trade = {
            **common,
            "pnl": realized_pnl if side == "sell" else 0.0,
            "timestamp": timestamp,
        }
        if analysis_id:
            order["analysis_id"] = analysis_id
            trade["analysis_id"] = analysis_id
        return order, trade

    async def insert_order(self, document: dict[str, Any]) -> None:
        await self.database["paper_orders"].insert_one(document)

    async def insert_trade(self, document: dict[str, Any]) -> None:
        await self.database["paper_trades"].insert_one(document)

    async def list_orders(
        self,
        user_id: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        cursor = (
            self.database["paper_orders"]
            .find({"user_id": user_id})
            .sort("created_at", -1)
            .limit(limit)
        )
        items = await cursor.to_list(None)
        return [
            {key: value for key, value in item.items() if key != "_id"}
            for item in items
        ]
