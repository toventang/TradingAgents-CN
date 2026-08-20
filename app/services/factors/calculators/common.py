import numpy as np
import pandas as pd
from typing import Optional, Union, List


def to_series(data: Union[List[float], np.ndarray, pd.Series]) -> pd.Series:
    """转为 Float64 pandas Series"""
    if isinstance(data, pd.Series):
        return data.astype(float)
    return pd.Series(data, dtype=float)


def clean_finite_series(s: pd.Series) -> pd.Series:
    """清理 Inf / -Inf 为 NaN"""
    s = s.copy()
    s[np.isinf(s)] = np.nan
    return s


def calc_sma(s: pd.Series, window: int) -> pd.Series:
    """简单移动平均"""
    if len(s) < window:
        return pd.Series(np.nan, index=s.index)
    return s.rolling(window=window, min_periods=window).mean()


def calc_ema(s: pd.Series, span: int) -> pd.Series:
    """指数移动平均"""
    if len(s) < span:
        return pd.Series(np.nan, index=s.index)
    return s.ewm(span=span, adjust=False, min_periods=span).mean()


def calc_std(s: pd.Series, window: int) -> pd.Series:
    """移动标准差"""
    if len(s) < window:
        return pd.Series(np.nan, index=s.index)
    return s.rolling(window=window, min_periods=window).std()


def calc_rsi(close: pd.Series, window: int = 14) -> pd.Series:
    """相对强弱指数 (RSI)"""
    if len(close) < window + 1:
        return pd.Series(np.nan, index=close.index)

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1/window, adjust=False, min_periods=window).mean()
    avg_loss = loss.ewm(alpha=1/window, adjust=False, min_periods=window).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    rsi[avg_loss == 0] = 100.0
    rsi[(avg_gain == 0) & (avg_loss == 0)] = 50.0

    return clean_finite_series(rsi)
