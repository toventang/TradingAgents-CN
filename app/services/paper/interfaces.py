"""Reusable service interfaces for manual paper trading and later adapters."""

from datetime import datetime
from typing import Any, Optional, Protocol

from app.models.paper import PaperSymbol, PriceSnapshot
from app.models.symbol import Market


class MarketCalendarService(Protocol):
    def next_execution_time(
        self,
        market: Market,
        requested_at: datetime,
    ) -> datetime: ...


class MarketRuleService(Protocol):
    async def get_rules(self, market: Market) -> Optional[dict[str, Any]]: ...

    def calculate_commission(
        self,
        market: Market,
        side: str,
        amount: float,
        rules: dict[str, Any],
    ) -> float: ...


class PriceSnapshotService(Protocol):
    async def get_snapshot(self, identity: PaperSymbol) -> Optional[PriceSnapshot]: ...


class PaperAccountService(Protocol):
    async def get_or_create(self, user_id: str) -> dict[str, Any]: ...


class PaperPositionService(Protocol):
    async def available_quantity(
        self,
        user_id: str,
        identity: PaperSymbol,
    ) -> int: ...


class PaperOrderService(Protocol):
    async def list_orders(self, user_id: str, limit: int) -> list[dict[str, Any]]: ...


class PaperPerformanceService(Protocol):
    async def account_overview(self, user_id: str) -> dict[str, Any]: ...
