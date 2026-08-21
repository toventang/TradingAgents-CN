"""Legacy-compatible market calendar and fee/rule services."""

from datetime import datetime
from typing import Any, Optional

from app.models.symbol import Market


class LegacyImmediateMarketCalendarService:
    """Characterizes the existing manual API: every valid quote fills now."""

    def next_execution_time(
        self,
        market: Market,
        requested_at: datetime,
    ) -> datetime:
        return requested_at


class MongoPaperMarketRuleService:
    def __init__(self, database: Any):
        self.database = database

    async def get_rules(self, market: Market) -> Optional[dict[str, Any]]:
        document = await self.database["paper_market_rules"].find_one(
            {"market": market.value}
        )
        return document.get("rules", {}) if document else None

    def calculate_commission(
        self,
        market: Market,
        side: str,
        amount: float,
        rules: dict[str, Any],
    ) -> float:
        if not rules or "commission" not in rules:
            return 0.0
        config = rules["commission"]
        commission = max(
            amount * config.get("rate", 0.0),
            config.get("min", 0.0),
        )
        if side == "sell" and "stamp_duty_rate" in config:
            commission += amount * config["stamp_duty_rate"]
        if market == Market.HK:
            for field in (
                "transaction_levy_rate",
                "trading_fee_rate",
                "settlement_fee_rate",
            ):
                if field in config:
                    commission += amount * config[field]
        if (
            market == Market.US
            and side == "sell"
            and "sec_fee_rate" in config
        ):
            commission += amount * config["sec_fee_rate"]
        # Compatibility: the existing CN transfer_fee_rate is not charged.
        return round(commission, 2)
