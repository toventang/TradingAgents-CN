"""Extracted, reusable manual paper-trading domain services."""

from app.services.paper.accounts import (
    INITIAL_CASH_BY_CURRENCY,
    MongoPaperAccountService,
)
from app.services.paper.consistency import PaperConsistencyBoundary
from app.services.paper.errors import (
    PaperConsistencyError,
    PaperTradingError,
    PaperValidationError,
)
from app.services.paper.execution import PaperExecutionService
from app.services.paper.market import (
    LegacyImmediateMarketCalendarService,
    MongoPaperMarketRuleService,
)
from app.services.paper.orders import MongoPaperOrderService
from app.services.paper.performance import LegacyPaperPerformanceService
from app.services.paper.positions import MongoPaperPositionService
from app.services.paper.prices import MongoPriceSnapshotService
from app.services.paper.service import PaperTradingService
from app.services.paper.symbols import PaperSymbolNormalizer

__all__ = [
    "INITIAL_CASH_BY_CURRENCY",
    "LegacyImmediateMarketCalendarService",
    "LegacyPaperPerformanceService",
    "MongoPaperAccountService",
    "MongoPaperMarketRuleService",
    "MongoPaperOrderService",
    "MongoPaperPositionService",
    "MongoPriceSnapshotService",
    "PaperConsistencyBoundary",
    "PaperConsistencyError",
    "PaperExecutionService",
    "PaperSymbolNormalizer",
    "PaperTradingError",
    "PaperTradingService",
    "PaperValidationError",
]
