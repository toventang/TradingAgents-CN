"""Read-only adapters from legacy Mongo shapes to normalized contracts."""

from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from app.core.database import get_mongo_db
from app.models.market_data import (
    DailyBar,
    DataQualityInfo,
    DataQualityStatus,
    MarketDataBatch,
    NewsSocialInput,
    PointInTimeFact,
    finite_or_none,
)
from app.models.symbol import Market
from app.services.data_quality.quality_service import DataQualityService


class MarketDataReadService:
    """Normalize existing collections without mutating them.

    Query predicates intentionally avoid publication aliases.  Aliases are
    normalized and filtered in this boundary so a legacy ``ann_date`` or
    ``publish_time`` can never accidentally bypass the point-in-time cutoff.
    """

    DAILY_COLLECTIONS = {
        Market.CN: ("stock_daily_quotes",),
        Market.HK: ("stock_daily_quotes_hk", "stock_daily_quotes"),
        Market.US: ("stock_daily_quotes_us", "stock_daily_quotes"),
    }

    def __init__(self, db=None):
        self._db = db

    def get_db(self):
        return self._db if self._db is not None else get_mongo_db()

    async def read_daily_bars(
        self,
        symbol: str,
        market: Market | str,
        *,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        as_of: datetime,
        source_version: str | None = None,
        stale_after: timedelta | None = None,
    ) -> MarketDataBatch:
        as_of = _aware(as_of)
        normalized_market = Market(market)
        start = _as_date(start_date) if start_date else None
        end = _as_date(end_date) if end_date else as_of.astimezone(
            _market_zone(normalized_market)
        ).date()
        raw: list[dict[str, Any]] = []
        for collection_name in dict.fromkeys(self.DAILY_COLLECTIONS[normalized_market]):
            raw.extend(await self._find_all(collection_name, {"$or": [{"symbol": symbol}, {"code": symbol}]}))

        candidates: list[tuple[DailyBar, datetime, bool]] = []
        normalization_reasons: list[str] = []
        for doc in raw:
            if doc.get("market") and str(doc["market"]).upper() != normalized_market.value:
                continue
            if doc.get("period") not in (None, "daily", "day", "1d"):
                continue
            try:
                trade_date = _as_date(doc.get("trade_date") or doc.get("date"))
            except (TypeError, ValueError):
                normalization_reasons.append("INVALID_TRADE_DATE")
                continue
            if (start and trade_date < start) or (end and trade_date > end):
                continue
            values: dict[str, float | None] = {}
            had_non_finite = False
            for field, aliases in {
                "open": ("open",), "high": ("high",), "low": ("low",),
                "close": ("close",), "pre_close": ("pre_close", "preclose"),
                "volume": ("volume", "vol"), "amount": ("amount", "turnover"),
                "adj_factor": ("adj_factor", "adjustflag"),
            }.items():
                raw_value = _first(doc, aliases)
                if _is_non_finite(raw_value):
                    had_non_finite = True
                values[field] = finite_or_none(raw_value)
            pct_value = _first(doc, ("pct_chg_decimal", "pct_change_decimal"))
            if pct_value is None:
                pct_value = _first(doc, ("pct_chg", "pct_change", "change_percent"))
                pct_value = None if pct_value is None else finite_or_none(pct_value)
                pct_value = None if pct_value is None else pct_value / 100.0
            else:
                pct_value = finite_or_none(pct_value)
            if had_non_finite or _is_non_finite(pct_value):
                normalization_reasons.append("NON_FINITE_VALUE")
            version = str(doc.get("source_version") or doc.get("version") or source_version or "legacy-v1")
            bar = DailyBar(
                market=normalized_market,
                symbol=symbol,
                trade_date=trade_date,
                pct_chg=pct_value,
                suspended=_is_suspended(doc),
                source=str(doc.get("data_source") or doc.get("source") or "legacy-mongo"),
                source_version=version,
                **values,
            )
            updated = _parse_timestamp(doc.get("updated_at") or doc.get("created_at"), normalized_market)
            candidates.append((bar, updated or datetime.min.replace(tzinfo=timezone.utc), had_non_finite))

        # One record per canonical identity.  Latest ingestion wins, with a
        # deterministic source-name tiebreaker independent of Mongo order.
        selected: dict[tuple[Market, str, date], tuple[DailyBar, datetime, bool]] = {}
        for candidate in candidates:
            key = (candidate[0].market, candidate[0].symbol, candidate[0].trade_date)
            current = selected.get(key)
            if current is None or (candidate[1], candidate[0].source) > (current[1], current[0].source):
                selected[key] = candidate
        bars = [item[0] for item in sorted(selected.values(), key=lambda item: item[0].trade_date)]
        duplicate_count = len(candidates) - len(bars)
        batch_version = source_version or _batch_version(bars)
        quality = DataQualityService.classify_batch(
            bars, as_of=as_of, source_version=batch_version,
            duplicate_count=duplicate_count, stale_after=stale_after,
        )
        if normalization_reasons:
            quality.status = DataQualityStatus.INVALID
            quality.reason_code = normalization_reasons[0]
            quality.reason_codes = list(dict.fromkeys(normalization_reasons + quality.reason_codes))
        return MarketDataBatch(items=bars, as_of=as_of, source_version=batch_version, quality=quality)

    async def read_point_in_time_facts(
        self,
        symbol: str,
        market: Market | str,
        *,
        as_of: datetime,
        limit: int = 50,
        source_version: str | None = None,
    ) -> MarketDataBatch:
        as_of = _aware(as_of)
        normalized_market = Market(market)
        docs = await self._find_all("stock_financial_data", {"$or": [{"symbol": symbol}, {"code": symbol}]})
        facts: list[PointInTimeFact] = []
        missing_publication = 0
        coarse_publication = 0
        for doc in docs:
            raw_publish = _first(doc, ("publish_at", "publish_date", "ann_date", "announcement_date"))
            if raw_publish in (None, ""):
                missing_publication += 1
                continue
            publish_at, coarse = _parse_publication(raw_publish, normalized_market)
            if publish_at is None:
                missing_publication += 1
                continue
            coarse_publication += int(coarse)
            ingested = _parse_timestamp(doc.get("ingested_at") or doc.get("created_at") or doc.get("updated_at"), normalized_market)
            if publish_at > as_of or (ingested is not None and ingested > as_of):
                continue
            version = str(doc.get("source_version") or doc.get("version") or source_version or "legacy-v1")
            payload = {key: value for key, value in doc.items() if key != "_id"}
            facts.append(PointInTimeFact(
                fact_id=str(doc.get("_id") or f"{symbol}:{doc.get('report_period', 'unknown')}:{version}"),
                market=normalized_market,
                symbol=symbol,
                report_period=str(doc.get("report_period") or "unknown"),
                publish_at=publish_at,
                ingested_at=ingested,
                fact_type=str(doc.get("fact_type") or "financial"),
                data=payload,
                source=str(doc.get("data_source") or doc.get("source") or "legacy-mongo"),
                source_version=version,
            ))
        facts.sort(key=lambda fact: (fact.publish_at, fact.fact_id), reverse=True)
        facts = facts[:limit]
        version = source_version or _batch_version(facts)
        if not facts:
            status, reason = DataQualityStatus.UNAVAILABLE, (
                "PUBLICATION_TIME_MISSING" if missing_publication else "NO_DATA"
            )
        elif missing_publication or coarse_publication:
            status, reason = DataQualityStatus.PARTIAL, (
                "PUBLICATION_TIME_MISSING" if missing_publication else "PUBLICATION_TIME_COARSE"
            )
        else:
            status, reason = DataQualityStatus.VALID, "OK"
        quality = DataQualityInfo(
            status=status, reason_code=reason,
            details={"excluded_missing_publication": missing_publication, "coarse_publication": coarse_publication},
            as_of=as_of, source_version=version,
        )
        return MarketDataBatch(items=facts, as_of=as_of, source_version=version, quality=quality)

    async def read_news_inputs(
        self,
        symbol: str,
        market: Market | str,
        *,
        as_of: datetime,
        limit: int = 50,
        source_version: str | None = None,
        collection_name: str = "stock_news",
    ) -> MarketDataBatch:
        as_of = _aware(as_of)
        normalized_market = Market(market)
        docs = await self._find_all(collection_name, {"$or": [{"symbol": symbol}, {"code": symbol}, {"symbols": symbol}]})
        items: list[NewsSocialInput] = []
        incomplete = 0
        for doc in docs:
            published = _parse_timestamp(
                _first(doc, ("published_at", "publish_time", "publish_at")), normalized_market
            )
            ingested = _parse_timestamp(
                _first(doc, ("ingested_at", "created_at", "updated_at")), normalized_market
            )
            if published is None or ingested is None:
                incomplete += 1
                continue
            version = str(doc.get("source_version") or doc.get("version") or source_version or "legacy-v1")
            item = NewsSocialInput(
                news_id=str(doc.get("_id") or doc.get("news_id") or doc.get("message_id") or f"{symbol}:{published.isoformat()}"),
                market=normalized_market, symbol=symbol, published_at=published, ingested_at=ingested,
                title=str(doc.get("title") or doc.get("content") or ""),
                content_summary=doc.get("summary") or doc.get("content_summary") or doc.get("content"),
                sentiment_score=finite_or_none(doc.get("sentiment_score")),
                source=str(doc.get("data_source") or doc.get("source") or doc.get("platform") or "legacy-mongo"),
                source_version=version,
            )
            if item.is_visible_at(as_of):
                items.append(item)
        items.sort(key=lambda item: (item.published_at, item.news_id), reverse=True)
        items = items[:limit]
        version = source_version or _batch_version(items)
        if not items:
            status, reason = DataQualityStatus.UNAVAILABLE, (
                "VISIBILITY_TIMESTAMP_MISSING" if incomplete else "NO_DATA"
            )
        elif incomplete:
            status, reason = DataQualityStatus.PARTIAL, "VISIBILITY_TIMESTAMP_MISSING"
        else:
            status, reason = DataQualityStatus.VALID, "OK"
        quality = DataQualityInfo(
            status=status, reason_code=reason, details={"excluded_incomplete": incomplete},
            as_of=as_of, source_version=version,
        )
        return MarketDataBatch(items=items, as_of=as_of, source_version=version, quality=quality)

    async def read_social_inputs(
        self,
        symbol: str,
        market: Market | str,
        *,
        as_of: datetime,
        limit: int = 50,
        source_version: str | None = None,
    ) -> MarketDataBatch:
        return await self.read_news_inputs(
            symbol, market, as_of=as_of, limit=limit,
            source_version=source_version, collection_name="social_media_messages",
        )

    # Compatibility methods retained for callers of the earlier J10 draft.
    async def get_pit_financials(self, symbol, market, as_of, limit=50):
        return (await self.read_point_in_time_facts(symbol, market, as_of=as_of, limit=limit)).items

    async def get_news_inputs(self, symbol, market, as_of, limit=50):
        return (await self.read_news_inputs(symbol, market, as_of=as_of, limit=limit)).items

    async def _find_all(self, collection_name: str, query: Mapping[str, Any]) -> list[dict[str, Any]]:
        cursor = self.get_db()[collection_name].find(dict(query))
        if hasattr(cursor, "to_list"):
            return list(await cursor.to_list(length=None))
        if hasattr(cursor, "__aiter__"):
            return [item async for item in cursor]
        result = await cursor if hasattr(cursor, "__await__") else cursor
        return list(result)


def _first(doc: Mapping[str, Any], names: Iterable[str]) -> Any:
    for name in names:
        if name in doc and doc[name] is not None:
            return doc[name]
    return None


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    return value


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value)
    if len(text) == 8 and text.isdigit():
        return datetime.strptime(text, "%Y%m%d").date()
    return date.fromisoformat(text[:10])


def _market_zone(market: Market) -> ZoneInfo:
    return ZoneInfo({Market.CN: "Asia/Shanghai", Market.HK: "Asia/Hong_Kong", Market.US: "America/New_York"}[market])


def _parse_timestamp(value: Any, market: Market) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min)
    else:
        text = str(value).strip()
        try:
            if len(text) == 8 and text.isdigit():
                parsed = datetime.strptime(text, "%Y%m%d")
            else:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=_market_zone(market))
    return parsed


def _parse_publication(value: Any, market: Market) -> tuple[datetime | None, bool]:
    date_only = isinstance(value, date) and not isinstance(value, datetime)
    if isinstance(value, str):
        stripped = value.strip()
        date_only = (len(stripped) == 8 and stripped.isdigit()) or (
            len(stripped) == 10 and stripped[4:5] == "-" and stripped[7:8] == "-"
        )
    elif isinstance(value, (int, float)):
        text = str(int(value)) if float(value).is_integer() else str(value)
        date_only = len(text) == 8 and text.isdigit()
    parsed = _parse_timestamp(value, market)
    if parsed is not None and date_only:
        parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
    return parsed, date_only


def _is_non_finite(value: Any) -> bool:
    if value is None or value == "":
        return False
    try:
        return not math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _is_suspended(doc: Mapping[str, Any]) -> bool:
    value = _first(doc, ("suspended", "is_suspended", "tradestatus", "trade_status"))
    if isinstance(value, str):
        return value.strip().lower() in {"suspended", "停牌", "0", "false"}
    return value is True or value == 0


def _batch_version(items: Iterable[Any]) -> str:
    versions = sorted({str(getattr(item, "source_version", "unknown")) for item in items})
    return "+".join(versions) if versions else "unavailable-v1"
