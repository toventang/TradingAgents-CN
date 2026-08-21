"""Facade consumed by the paper router; it owns all domain composition."""

from typing import Any, Optional

from app.services.paper.accounts import MongoPaperAccountService
from app.services.paper.consistency import PaperConsistencyBoundary
from app.services.paper.errors import PaperConsistencyError, PaperValidationError
from app.services.paper.execution import PaperExecutionService
from app.services.paper.market import (
    LegacyImmediateMarketCalendarService,
    MongoPaperMarketRuleService,
)
from app.services.paper.orders import MongoPaperOrderService
from app.services.paper.performance import LegacyPaperPerformanceService
from app.services.paper.positions import MongoPaperPositionService
from app.services.paper.prices import MongoPriceSnapshotService
from app.services.paper.symbols import PaperSymbolNormalizer
from app.services.symbols import SymbolNormalizationError


class PaperTradingService:
    def __init__(
        self,
        database: Any,
        *,
        prices: Optional[MongoPriceSnapshotService] = None,
    ):
        self.database = database
        self.accounts = MongoPaperAccountService(database)
        self.market_rules = MongoPaperMarketRuleService(database)
        self.calendar = LegacyImmediateMarketCalendarService()
        self.prices = prices or MongoPriceSnapshotService(database)
        self.positions = MongoPaperPositionService(
            database,
            self.market_rules,
            self.prices,
        )
        self.orders = MongoPaperOrderService(database)
        self.consistency = PaperConsistencyBoundary(database)
        self.execution = PaperExecutionService(
            accounts=self.accounts,
            market_rules=self.market_rules,
            calendar=self.calendar,
            prices=self.prices,
            positions=self.positions,
            orders=self.orders,
            consistency=self.consistency,
        )
        self.performance = LegacyPaperPerformanceService(
            self.accounts,
            self.positions,
        )

    @staticmethod
    def normalize_symbol(code: str, market: Optional[str] = None):
        try:
            return PaperSymbolNormalizer.normalize(code, market)
        except SymbolNormalizationError as exc:
            raise PaperValidationError(str(exc)) from exc

    async def get_account(self, user_id: str) -> dict:
        return await self.performance.account_overview(user_id)

    async def place_order(
        self,
        *,
        user_id: str,
        code: str,
        market: Optional[str],
        side: str,
        quantity: int,
        analysis_id: Optional[str] = None,
    ) -> dict:
        identity = self.normalize_symbol(code, market)
        result = await self.execution.execute_market_order(
            user_id=user_id,
            identity=identity,
            side=side,
            quantity=quantity,
            analysis_id=analysis_id,
        )
        return {"order": result.order}

    async def list_positions(self, user_id: str) -> dict:
        return {"items": await self.positions.list_enriched(user_id)}

    async def list_orders(self, user_id: str, limit: int) -> dict:
        return {"items": await self.orders.list_orders(user_id, limit)}

    async def reset(self, user_id: str) -> dict:
        execution_id = f"reset:{user_id}"
        completed: list[str] = []
        failed_stage = "account"
        collections = (
            ("account", "paper_accounts"),
            ("position", "paper_positions"),
            ("order", "paper_orders"),
            ("trade", "paper_trades"),
        )
        try:
            for stage, collection in collections:
                failed_stage = stage
                await self.database[collection].delete_many({"user_id": user_id})
                completed.append(stage)
            account = await self.accounts.get_or_create(user_id)
        except Exception as exc:
            recovery_id = await self.consistency.record_failure(
                execution_id=execution_id,
                user_id=user_id,
                operation="reset",
                failed_stage=failed_stage,
                completed_stages=completed,
                error=exc,
            )
            raise PaperConsistencyError(
                "模拟账户重置不完整，已创建恢复记录",
                recovery_id=recovery_id,
            ) from exc
        return {"message": "账户已重置", "cash": account.get("cash", {})}
