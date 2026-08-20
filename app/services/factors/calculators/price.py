import numpy as np
import pandas as pd
from typing import Dict
from app.services.factors.calculators.common import clean_finite_series, to_series


def calculate_price_factors(df: pd.DataFrame) -> Dict[str, pd.Series]:
    """计算 18 个 Price / Return 因子"""
    close = to_series(df["close"])
    open_p = to_series(df["open"]) if "open" in df else close
    high = to_series(df["high"]) if "high" in df else close
    low = to_series(df["low"]) if "low" in df else close

    res = {}

    # 收益率因子
    for days in [1, 5, 10, 20, 60, 120, 240]:
        res[f"ret_{days}d"] = clean_finite_series((close / close.shift(days)) - 1.0)

    for days in [1, 5, 20]:
        res[f"log_ret_{days}d"] = clean_finite_series(np.log(close / close.shift(days)))

    res["close_to_open_ret"] = clean_finite_series((open_p / close.shift(1)) - 1.0)
    res["open_to_close_ret"] = clean_finite_series((close / open_p) - 1.0)

    # 振幅与区间位置
    low_safe = low.replace(0, np.nan)
    res["high_to_low_ratio"] = clean_finite_series(high / low_safe)

    w52 = 240
    high_52w = high.rolling(window=w52, min_periods=1).max()
    low_52w = low.rolling(window=w52, min_periods=1).min()
    range_52w = (high_52w - low_52w).replace(0, np.nan)

    res["price_position_52w"] = clean_finite_series((close - low_52w) / range_52w)
    res["price_pct_52w_high"] = clean_finite_series((close / high_52w.replace(0, np.nan)) - 1.0)
    res["price_pct_52w_low"] = clean_finite_series((close / low_52w.replace(0, np.nan)) - 1.0)

    # 跳空幅度
    prev_close = close.shift(1).replace(0, np.nan)
    prev_high = high.shift(1)
    prev_low = low.shift(1)

    res["gap_up_pct"] = clean_finite_series(np.maximum(0, open_p - prev_high) / prev_close)
    res["gap_down_pct"] = clean_finite_series(np.maximum(0, prev_low - open_p) / prev_close)

    return res
