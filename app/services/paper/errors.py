"""Typed paper-domain failures mapped by the API router."""

from typing import Optional


class PaperTradingError(RuntimeError):
    code = "PAPER_TRADING_ERROR"


class PaperValidationError(PaperTradingError):
    code = "PAPER_VALIDATION_ERROR"


class PaperConsistencyError(PaperTradingError):
    code = "PAPER_CONSISTENCY_ERROR"

    def __init__(
        self,
        message: str,
        *,
        recovery_id: Optional[str],
    ) -> None:
        super().__init__(message)
        self.recovery_id = recovery_id
