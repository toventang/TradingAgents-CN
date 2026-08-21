"""Position persistence, T+1 availability, cost, and valuation."""

from datetime import datetime, timezone
from typing import Any

from app.models.paper import PaperSymbol
from app.models.symbol import Market
from app.services.paper.market import MongoPaperMarketRuleService
from app.services.paper.prices import MongoPriceSnapshotService


class MongoPaperPositionService:
    def __init__(
        self,
        database: Any,
        market_rules: MongoPaperMarketRuleService,
        prices: MongoPriceSnapshotService,
    ):
        self.database = database
        self.market_rules = market_rules
        self.prices = prices

    async def get_position(
        self,
        user_id: str,
        identity: PaperSymbol,
    ) -> dict[str, Any] | None:
        compatible_codes = list(dict.fromkeys([identity.code, identity.symbol]))
        return await self.database["paper_positions"].find_one(
            {
                "user_id": user_id,
                "code": {"$in": compatible_codes},
            }
        )

    async def available_quantity(
        self,
        user_id: str,
        identity: PaperSymbol,
    ) -> int:
        position = await self.get_position(user_id, identity)
        if position is None:
            return 0
        total = int(position.get("quantity", 0))
        if identity.market != Market.CN:
            return total
        rules = await self.market_rules.get_rules(identity.market)
        if not rules or rules.get("t_plus", 0) <= 0:
            return total
        today = datetime.now(timezone.utc).date().isoformat()
        pipeline = [
            {
                "$match": {
                    "user_id": user_id,
                    "code": {
                        "$in": list(
                            dict.fromkeys([identity.code, identity.symbol])
                        )
                    },
                    "side": "buy",
                    "timestamp": {"$gte": today},
                }
            },
            {"$group": {"_id": None, "total": {"$sum": "$quantity"}}},
        ]
        result = await self.database["paper_trades"].aggregate(pipeline).to_list(1)
        bought_today = result[0]["total"] if result else 0
        return max(0, total - bought_today)

    async def apply_buy(
        self,
        user_id: str,
        identity: PaperSymbol,
        position: dict[str, Any] | None,
        quantity: int,
        price: float,
        timestamp: str,
    ) -> None:
        collection = self.database["paper_positions"]
        if position is None:
            await collection.insert_one(
                {
                    "user_id": user_id,
                    "code": identity.code,
                    "market": identity.market.value,
                    "currency": identity.currency.value,
                    "quantity": quantity,
                    "available_qty": (
                        quantity if identity.market != Market.CN else 0
                    ),
                    "frozen_qty": 0,
                    "avg_cost": price,
                    "updated_at": timestamp,
                }
            )
            return
        old_quantity = int(position.get("quantity", 0))
        old_cost = float(position.get("avg_cost", 0.0))
        new_quantity = old_quantity + quantity
        average_cost = (
            round(
                (old_cost * old_quantity + price * quantity) / new_quantity,
                4,
            )
            if new_quantity > 0
            else price
        )
        available = (
            position.get("available_qty", old_quantity)
            if identity.market == Market.CN
            else new_quantity
        )
        result = await collection.update_one(
            {"_id": position["_id"]},
            {
                "$set": {
                    "quantity": new_quantity,
                    "available_qty": available,
                    "avg_cost": average_cost,
                    "updated_at": timestamp,
                }
            },
        )
        if result.matched_count != 1:
            raise RuntimeError("paper position buy matched no position")

    async def apply_sell(
        self,
        position: dict[str, Any],
        quantity: int,
        timestamp: str,
    ) -> None:
        collection = self.database["paper_positions"]
        old_quantity = int(position.get("quantity", 0))
        new_quantity = old_quantity - quantity
        if new_quantity == 0:
            result = await collection.delete_one({"_id": position["_id"]})
            if result.deleted_count != 1:
                raise RuntimeError("paper position sell matched no position")
            return
        available = max(
            0,
            int(position.get("available_qty", old_quantity)) - quantity,
        )
        result = await collection.update_one(
            {"_id": position["_id"]},
            {
                "$set": {
                    "quantity": new_quantity,
                    "available_qty": available,
                    "updated_at": timestamp,
                }
            },
        )
        if result.matched_count != 1:
            raise RuntimeError("paper position sell matched no position")

    async def list_enriched(self, user_id: str) -> list[dict[str, Any]]:
        documents = await self.database["paper_positions"].find(
            {"user_id": user_id}
        ).to_list(None)
        items = []
        for document in documents:
            identity = PaperSymbol(
                market=document.get("market", "CN"),
                symbol=str(document.get("code", "")),
                currency=document.get("currency", "CNY"),
                code=str(document.get("code", "")),
            )
            quantity = int(document.get("quantity", 0))
            average_cost = float(document.get("avg_cost", 0.0))
            snapshot = await self.prices.get_snapshot(identity)
            last_price = snapshot.price if snapshot else None
            market_value = round((last_price or 0.0) * quantity, 2)
            items.append(
                {
                    "code": document.get("code"),
                    "market": document.get("market", "CN"),
                    "currency": document.get("currency", "CNY"),
                    "quantity": quantity,
                    "available_qty": document.get("available_qty", quantity),
                    "avg_cost": average_cost,
                    "last_price": last_price,
                    "market_value": market_value,
                    "unrealized_pnl": (
                        None
                        if last_price is None
                        else round(
                            (last_price - average_cost) * quantity,
                            2,
                        )
                    ),
                }
            )
        return items
