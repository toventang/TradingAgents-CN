from datetime import datetime
from typing import Optional, Dict, Any, List
from app.models.market_data import PointInTimeFact
from app.core.database import get_mongo_db


class PointInTimeService:
    """Point-in-Time 财务观测服务（防止未来数据泄漏）"""

    def __init__(self, db=None):
        self._db = db

    def get_db(self):
        return self._db if self._db is not None else get_mongo_db()

    async def get_latest_observation(
        self,
        symbol: str,
        market: str,
        as_of: datetime
    ) -> Optional[PointInTimeFact]:
        """在 as_of 时点前获取最新已公开的财务观测事实"""
        db = self.get_db()
        cursor = db["stock_financial_data"].find({
            "$or": [{"code": symbol}, {"symbol": symbol}],
            "publish_at": {"$lte": as_of.isoformat()}
        }).sort("publish_at", -1).limit(1)

        docs = await cursor.to_list(1) if hasattr(cursor, "to_list") else await cursor
        if not docs:
            return None

        d = docs[0]
        pub_at = d.get("publish_at")
        pub_dt = datetime.fromisoformat(pub_at) if isinstance(pub_at, str) else (pub_at or as_of)

        fact = PointInTimeFact(
            fact_id=str(d.get("_id", f"fact_{symbol}")),
            symbol=symbol,
            market=market,
            report_period=d.get("report_period", "UNKNOWN"),
            publish_at=pub_dt,
            ingested_at=as_of,
            fact_type="financial",
            data=d.get("data", d),
            source=d.get("source", "default"),
            source_version="1.0.0"
        )

        return fact if fact.is_visible_at(as_of) else None
