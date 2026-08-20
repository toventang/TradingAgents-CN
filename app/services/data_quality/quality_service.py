import math
from typing import Optional, List
from app.models.market_data import DailyBar, DataQualityInfo, DataQualityStatus
from app.utils.timezone import now_tz


class DataQualityService:
    """数据质量校验服务"""

    @staticmethod
    def validate_daily_bar(bar: DailyBar) -> DataQualityInfo:
        """校验单日 K 线数据合法性"""
        missing = []
        if bar.open is None or math.isnan(bar.open) or math.isinf(bar.open):
            missing.append("open")
        if bar.high is None or math.isnan(bar.high) or math.isinf(bar.high):
            missing.append("high")
        if bar.low is None or math.isnan(bar.low) or math.isinf(bar.low):
            missing.append("low")
        if bar.close is None or math.isnan(bar.close) or math.isinf(bar.close):
            missing.append("close")

        if missing:
            return DataQualityInfo(
                status=DataQualityStatus.INVALID,
                reason_code="NON_FINITE_PRICE",
                message=f"Prices contain non-finite values or missing fields: {missing}",
                missing_fields=missing,
                as_of=now_tz(),
                source_version=bar.source_version
            )

        if bar.volume < 0 or bar.amount < 0:
            return DataQualityInfo(
                status=DataQualityStatus.INVALID,
                reason_code="NEGATIVE_VOLUME",
                message="Volume or amount is negative",
                as_of=now_tz(),
                source_version=bar.source_version
            )

        # High/Low bounds check
        if bar.high < max(bar.open, bar.close) or bar.low > min(bar.open, bar.close):
            return DataQualityInfo(
                status=DataQualityStatus.INVALID,
                reason_code="INVALID_OHLC_BOUNDS",
                message="High price is below max(open, close) or low price is above min(open, close)",
                as_of=now_tz(),
                source_version=bar.source_version
            )

        return DataQualityInfo(
            status=DataQualityStatus.VALID,
            reason_code="OK",
            as_of=now_tz(),
            source_version=bar.source_version
        )
