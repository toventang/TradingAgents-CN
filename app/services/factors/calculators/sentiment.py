import numpy as np
import pandas as pd
from typing import Dict, Any, Optional, List
from app.services.factors.calculators.common import clean_finite_series, to_series


def calculate_sentiment_factors(
    df: pd.DataFrame,
    sentiment_data: Optional[Dict[str, Any]] = None
) -> Dict[str, pd.Series]:
    """计算 12 个 Sentiment & Event 因子"""
    close = to_series(df["close"])
    pct_chg = to_series(df["pct_chg"]) if "pct_chg" in df else close.pct_change() * 100.0
    volume = to_series(df["volume"]) if "volume" in df else pd.Series(0.0, index=close.index)

    res = {}
    sent = sentiment_data or {}

    def _get_val(key: str, default: float = np.nan) -> float:
        val = sent.get(key, default)
        try:
            return float(val) if val is not None else np.nan
        except (ValueError, TypeError):
            return np.nan

    def _make_const_series(val: float) -> pd.Series:
        return pd.Series(val if (val is not None and not np.isinf(val)) else np.nan, index=close.index)

    # 情绪与新闻指标
    res["news_sentiment_3d"] = clean_finite_series(_make_const_series(_get_val("news_sentiment_3d", 0.0)))
    res["news_sentiment_7d"] = clean_finite_series(_make_const_series(_get_val("news_sentiment_7d", 0.0)))
    res["news_volume_3d"] = clean_finite_series(_make_const_series(_get_val("news_volume_3d", 0.0)))
    res["social_sentiment_3d"] = clean_finite_series(_make_const_series(_get_val("social_sentiment_3d", 0.0)))

    # 分析师与机构指标
    rating = _get_val("analyst_rating_mean", 3.0)
    target_price = _get_val("target_price")
    last_close = close.iloc[-1] if len(close) > 0 else np.nan
    upside = (target_price / last_close - 1.0) if (target_price and last_close and last_close > 0) else np.nan

    res["analyst_rating_mean"] = clean_finite_series(_make_const_series(rating))
    res["analyst_target_price_upside"] = clean_finite_series(_make_const_series(upside))
    res["earnings_revision_30d"] = clean_finite_series(_make_const_series(_get_val("earnings_revision_30d", 0.0)))
    res["institution_holding_pct"] = clean_finite_series(_make_const_series(_get_val("institution_holding_pct")))
    res["margin_trading_ratio"] = clean_finite_series(_make_const_series(_get_val("margin_trading_ratio")))

    # 涨跌停与停牌事件 (20日)
    # A股普通股涨跌停幅度为 +-9.8%
    is_limit_up = (pct_chg >= 9.8).astype(float)
    is_limit_down = (pct_chg <= -9.8).astype(float)

    res["limit_up_count_20d"] = clean_finite_series(is_limit_up.rolling(20, min_periods=1).sum())
    res["limit_down_count_20d"] = clean_finite_series(is_limit_down.rolling(20, min_periods=1).sum())

    # 停牌标识 (成交量为0或显式停牌)
    is_suspended = (volume == 0).astype(float)
    res["suspension_flag"] = clean_finite_series(is_suspended)

    return res
