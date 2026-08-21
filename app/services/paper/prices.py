"""Price snapshot adapter preserving current CN/HK/US quote fallbacks."""

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.models.paper import PaperSymbol, PriceSnapshot
from app.models.symbol import Market

logger = logging.getLogger("paper_trading")


def _latency_ms(quote_time: Any) -> Optional[int]:
    if not isinstance(quote_time, (str, datetime)):
        return None
    try:
        parsed = (
            quote_time
            if isinstance(quote_time, datetime)
            else datetime.fromisoformat(quote_time.replace("Z", "+00:00"))
        )
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(
            0,
            int((datetime.now(timezone.utc) - parsed).total_seconds() * 1000),
        )
    except (TypeError, ValueError):
        return None


class MongoPriceSnapshotService:
    def __init__(self, database: Any):
        self.database = database

    @staticmethod
    def _snapshot(
        identity: PaperSymbol,
        value: Any,
        *,
        quote_time: Any,
        source: str,
    ) -> Optional[PriceSnapshot]:
        try:
            price = float(value)
        except (TypeError, ValueError):
            return None
        if price <= 0:
            return None
        normalized_time = (
            quote_time.isoformat()
            if isinstance(quote_time, datetime)
            else str(quote_time)
            if quote_time is not None
            else None
        )
        return PriceSnapshot(
            market=identity.market,
            symbol=identity.symbol,
            price=price,
            quote_time=normalized_time,
            source=source,
            latency_ms=_latency_ms(quote_time),
        )

    async def get_snapshot(
        self,
        identity: PaperSymbol,
    ) -> Optional[PriceSnapshot]:
        if identity.market == Market.CN:
            quote = await self.database["market_quotes"].find_one(
                {"$or": [{"code": identity.code}, {"symbol": identity.symbol}]},
                {"_id": 0, "close": 1, "updated_at": 1, "timestamp": 1},
            )
            if quote:
                snapshot = self._snapshot(
                    identity,
                    quote.get("close"),
                    quote_time=quote.get("updated_at") or quote.get("timestamp"),
                    source="market_quotes",
                )
                if snapshot:
                    return snapshot
            basic = await self.database["stock_basic_info"].find_one(
                {"$or": [{"code": identity.code}, {"symbol": identity.symbol}]},
                {"_id": 0, "current_price": 1, "updated_at": 1},
            )
            if basic:
                snapshot = self._snapshot(
                    identity,
                    basic.get("current_price"),
                    quote_time=basic.get("updated_at"),
                    source="stock_basic_info",
                )
                if snapshot:
                    return snapshot
            return None

        try:
            from app.services.foreign_stock_service import ForeignStockService

            quote = await ForeignStockService(db=self.database).get_quote(
                identity.market.value,
                identity.code,
                force_refresh=False,
            )
        except Exception as exc:
            logger.error(
                "Foreign quote failed for %s/%s (type=%s)",
                identity.market.value,
                identity.symbol,
                type(exc).__name__,
            )
            return None
        if not quote:
            return None
        return self._snapshot(
            identity,
            quote.get("price")
            or quote.get("current_price")
            or quote.get("close"),
            quote_time=quote.get("quote_time")
            or quote.get("updated_at")
            or quote.get("timestamp"),
            source="foreign_stock_service",
        )
