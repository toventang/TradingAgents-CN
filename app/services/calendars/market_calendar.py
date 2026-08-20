from datetime import datetime, date, timedelta
from typing import List, Union


class MarketCalendarService:
    """交易日历服务（支持 CN / HK / US）"""

    @staticmethod
    def _to_date(dt: Union[str, date, datetime]) -> date:
        if isinstance(dt, datetime):
            return dt.date()
        if isinstance(dt, date):
            return dt
        return datetime.strptime(str(dt)[:10], "%Y-%m-%d").date()

    @staticmethod
    def is_trade_day(market: str, dt: Union[str, date, datetime]) -> bool:
        """检查是否为法定交易日（周末排查）"""
        d = MarketCalendarService._to_date(dt)
        if d.weekday() >= 5:  # 5=Saturday, 6=Sunday
            return False
        return True

    @staticmethod
    def get_trading_days(market: str, start_date: Union[str, date], end_date: Union[str, date]) -> List[str]:
        """获取区间内的所有交易日字符串列表"""
        cur = MarketCalendarService._to_date(start_date)
        end = MarketCalendarService._to_date(end_date)
        trade_days = []
        while cur <= end:
            if MarketCalendarService.is_trade_day(market, cur):
                trade_days.append(cur.strftime("%Y-%m-%d"))
            cur += timedelta(days=1)
        return trade_days

    @staticmethod
    def get_next_trade_day(market: str, dt: Union[str, date]) -> str:
        """获取下一个交易日"""
        cur = MarketCalendarService._to_date(dt) + timedelta(days=1)
        while not MarketCalendarService.is_trade_day(market, cur):
            cur += timedelta(days=1)
        return cur.strftime("%Y-%m-%d")

    @staticmethod
    def get_prev_trade_day(market: str, dt: Union[str, date]) -> str:
        """获取上一个交易日"""
        cur = MarketCalendarService._to_date(dt) - timedelta(days=1)
        while not MarketCalendarService.is_trade_day(market, cur):
            cur -= timedelta(days=1)
        return cur.strftime("%Y-%m-%d")
