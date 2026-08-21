"""Account equity and position valuation preserving current API semantics."""

from app.services.paper.accounts import MongoPaperAccountService
from app.services.paper.positions import MongoPaperPositionService


class LegacyPaperPerformanceService:
    def __init__(
        self,
        accounts: MongoPaperAccountService,
        positions: MongoPaperPositionService,
    ):
        self.accounts = accounts
        self.positions = positions

    async def account_overview(self, user_id: str) -> dict:
        account = await self.accounts.get_or_create(user_id)
        positions = await self.positions.list_enriched(user_id)
        values = {"CNY": 0.0, "HKD": 0.0, "USD": 0.0}
        for position in positions:
            values[position["currency"]] += position["market_value"]
        cash = account.get("cash", {})
        realized = account.get("realized_pnl", {})
        if not isinstance(cash, dict):
            cash = {"CNY": float(cash), "HKD": 0.0, "USD": 0.0}
        if not isinstance(realized, dict):
            realized = {
                "CNY": float(realized),
                "HKD": 0.0,
                "USD": 0.0,
            }
        normalized_cash = {
            currency: round(float(cash.get(currency, 0.0)), 2)
            for currency in values
        }
        normalized_realized = {
            currency: round(float(realized.get(currency, 0.0)), 2)
            for currency in values
        }
        summary = {
            "cash": normalized_cash,
            "realized_pnl": normalized_realized,
            "positions_value": values,
            "equity": {
                currency: round(
                    float(cash.get(currency, 0.0)) + values[currency],
                    2,
                )
                for currency in values
            },
            "updated_at": account.get("updated_at"),
        }
        return {"account": summary, "positions": positions}
