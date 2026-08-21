"""Multi-currency paper account persistence and legacy migration."""

import logging
from datetime import datetime, timezone
from typing import Any, Callable

from app.models.symbol import Currency

logger = logging.getLogger("paper_trading")

INITIAL_CASH_BY_CURRENCY = {
    Currency.CNY: 1_000_000.0,
    Currency.HKD: 1_000_000.0,
    Currency.USD: 100_000.0,
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class MongoPaperAccountService:
    def __init__(
        self,
        database: Any,
        *,
        clock: Callable[[], datetime] = utc_now,
    ):
        self.database = database
        self.clock = clock

    def now_iso(self) -> str:
        return self.clock().isoformat()

    async def get_or_create(self, user_id: str) -> dict[str, Any]:
        collection = self.database["paper_accounts"]
        account = await collection.find_one({"user_id": user_id})
        if account is None:
            now = self.now_iso()
            account = {
                "user_id": user_id,
                "cash": {
                    currency.value: amount
                    for currency, amount in INITIAL_CASH_BY_CURRENCY.items()
                },
                "realized_pnl": {
                    currency.value: 0.0 for currency in Currency
                },
                "settings": {
                    "auto_currency_conversion": False,
                    "default_market": "CN",
                },
                "created_at": now,
                "updated_at": now,
            }
            await collection.insert_one(account)
            return account

        updates: dict[str, Any] = {}
        try:
            cash = account.get("cash")
            if not isinstance(cash, dict):
                updates["cash"] = {
                    "CNY": float(cash or 0.0),
                    "HKD": 0.0,
                    "USD": 0.0,
                }
            realized = account.get("realized_pnl")
            if not isinstance(realized, dict):
                updates["realized_pnl"] = {
                    "CNY": float(realized or 0.0),
                    "HKD": 0.0,
                    "USD": 0.0,
                }
            if updates:
                updates["updated_at"] = self.now_iso()
                await collection.update_one(
                    {"user_id": user_id},
                    {"$set": updates},
                )
                migrated = await collection.find_one({"user_id": user_id})
                if migrated is not None:
                    account = migrated
        except Exception as exc:
            # Compatibility: legacy migration failures did not make reads fail.
            logger.error(
                "Paper account migration failed for user (type=%s)",
                type(exc).__name__,
            )
        return account

    @staticmethod
    def available_cash(
        account: dict[str, Any],
        currency: Currency,
    ) -> float:
        cash = account.get("cash", {})
        if isinstance(cash, dict):
            return float(cash.get(currency.value, 0.0))
        return float(cash) if currency == Currency.CNY else 0.0

    async def debit(
        self,
        user_id: str,
        currency: Currency,
        new_cash: float,
        timestamp: str,
    ) -> None:
        result = await self.database["paper_accounts"].update_one(
            {"user_id": user_id},
            {
                "$set": {
                    f"cash.{currency.value}": new_cash,
                    "updated_at": timestamp,
                }
            },
        )
        if result.matched_count != 1:
            raise RuntimeError("paper account debit matched no account")

    async def credit_sale(
        self,
        user_id: str,
        currency: Currency,
        net_proceeds: float,
        realized_pnl: float,
        timestamp: str,
    ) -> None:
        result = await self.database["paper_accounts"].update_one(
            {"user_id": user_id},
            {
                "$inc": {
                    f"cash.{currency.value}": net_proceeds,
                    f"realized_pnl.{currency.value}": realized_pnl,
                },
                "$set": {"updated_at": timestamp},
            },
        )
        if result.matched_count != 1:
            raise RuntimeError("paper account credit matched no account")
