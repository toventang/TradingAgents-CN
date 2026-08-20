from datetime import datetime
from typing import Optional, List, Dict, Any
from app.utils.timezone import now_tz
from app.models.market_data import (
    DailyBar,
    PointInTimeFact,
    NewsSocialInput,
    MarketDataBatch,
    DataQualityInfo,
    DataQualityStatus
)
from app.services.data_quality.quality_service import DataQualityService
from app.services.calendars.market_calendar import MarketCalendarService
from app.core.database import get_mongo_db


class MarketDataReadService:
    """标准化市场数据读取服务（只读，支持 PIT 检查）"""

    def __init__(self, db=None):
        self._db = db

    def get_db(self):
        return self._db if self._db is not None else get_mongo_db()

    async def get_pit_financials(
        self,
        symbol: str,
        market: str,
        as_of: datetime,
        limit: int = 50
    ) -> List[PointInTimeFact]:
        """获取 Point-in-Time 财务事实（严格按 publish_at <= as_of 过滤，防止 Look-ahead Bias）"""
        db = self.get_db()
        cursor = db["stock_financial_data"].find({
            "$or": [{"code": symbol}, {"symbol": symbol}],
            "publish_at": {"$lte": as_of.isoformat()}
        }).sort("publish_at", -1).limit(limit)

        docs = await cursor.to_list(length=limit) if hasattr(cursor, "to_list") else await cursor
        facts = []
        for d in docs:
            pub_at = d.get("publish_at")
            if isinstance(pub_at, str):
                pub_dt = datetime.fromisoformat(pub_at)
            else:
                pub_dt = pub_at or as_of

            facts.append(PointInTimeFact(
                fact_id=str(d.get("_id", f"fact_{d.get(code)}")),
                symbol=symbol,
                market=market,
                report_period=d.get("report_period", "UNKNOWN"),
                publish_at=pub_dt,
                ingested_at=as_of,
                fact_type=d.get("fact_type", "financial"),
                data=d.get("data", d),
                source=d.get("source", "default"),
                source_version="1.0.0"
            ))

        return [f for f in facts if f.is_visible_at(as_of)]

    async def get_news_inputs(
        self,
        symbol: str,
        market: str,
        as_of: datetime,
        limit: int = 50
    ) -> List[NewsSocialInput]:
        """获取可用的新闻/社交输入（严格按 published_at <= as_of 过滤）"""
        db = self.get_db()
        cursor = db["stock_news"].find({
            "$or": [{"code": symbol}, {"symbol": symbol}],
            "published_at": {"$lte": as_of.isoformat()}
        }).sort("published_at", -1).limit(limit)

        docs = await cursor.to_list(length=limit) if hasattr(cursor, "to_list") else await cursor
        news_items = []
        for d in docs:
            pub_at = d.get("published_at")
            if isinstance(pub_at, str):
                pub_dt = datetime.fromisoformat(pub_at)
            else:
                pub_dt = pub_at or as_of

            news_items.append(NewsSocialInput(
                news_id=str(d.get("_id", f"news_{d.get(code)}")),
                symbol=symbol,
                market=market,
                published_at=pub_dt,
                ingested_at=as_of,
                title=d.get("title", "No Title"),
                content_summary=d.get("summary"),
                sentiment_score=d.get("sentiment_score"),
                source=d.get("source", "default"),
                source_version="1.0.0"
            ))

        return [n for n in news_items if n.is_visible_at(as_of)]
