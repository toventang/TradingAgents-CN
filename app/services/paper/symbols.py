"""Canonical symbol normalization with legacy paper collection compatibility."""

from typing import Optional

from app.models.paper import PaperSymbol
from app.models.symbol import Market
from app.services.symbols import SymbolNormalizer


class PaperSymbolNormalizer:
    @staticmethod
    def normalize(code: str, market: Optional[str] = None) -> PaperSymbol:
        canonical = SymbolNormalizer.normalize(code, market=market)
        legacy_code = (
            canonical.symbol.zfill(5)
            if canonical.market == Market.HK
            else canonical.symbol
        )
        return PaperSymbol(
            market=canonical.market,
            symbol=canonical.symbol,
            currency=canonical.currency,
            code=legacy_code,
        )
