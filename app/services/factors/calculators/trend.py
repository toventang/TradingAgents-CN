import numpy as np
import pandas as pd
from typing import Dict
from app.services.factors.calculators.common import (
    calc_sma,
    calc_ema,
    clean_finite_series,
    to_series
)


def calculate_trend_factors(df: pd.DataFrame) -> Dict[str, pd.Series]:
    """计算 23 个 Trend 因子"""
    close = to_series(df["close"])
    high = to_series(df["high"]) if "high" in df else close
    low = to_series(df["low"]) if "low" in df else close

    res = {}

    # SMA & EMA
    for w in [5, 10, 20, 60, 120, 200]:
        res[f"sma_{w}"] = clean_finite_series(calc_sma(close, w))

    for span in [5, 12, 26]:
        res[f"ema_{span}"] = clean_finite_series(calc_ema(close, span))

    # MACD (Unmultiplied histogram)
    ema_12 = calc_ema(close, 12)
    ema_26 = calc_ema(close, 26)
    macd_line = ema_12 - ema_26
    macd_signal = calc_ema(macd_line, 9)
    macd_hist = macd_line - macd_signal

    res["macd_line"] = clean_finite_series(macd_line)
    res["macd_signal"] = clean_finite_series(macd_signal)
    res["macd_hist"] = clean_finite_series(macd_hist)

    # ADX / DMI
    window_adx = 14
    if len(close) >= window_adx:
        up_move = high.diff()
        down_move = -low.diff()
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs()
        ], axis=1).max(axis=1)

        atr = tr.ewm(alpha=1/window_adx, adjust=False).mean()
        plus_di = 100.0 * pd.Series(plus_dm, index=close.index).ewm(alpha=1/window_adx, adjust=False).mean() / atr.replace(0, np.nan)
        minus_di = 100.0 * pd.Series(minus_dm, index=close.index).ewm(alpha=1/window_adx, adjust=False).mean() / atr.replace(0, np.nan)

        dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
        adx = dx.ewm(alpha=1/window_adx, adjust=False).mean()

        res["adx_14"] = clean_finite_series(adx)
        res["di_plus_14"] = clean_finite_series(plus_di)
        res["di_minus_14"] = clean_finite_series(minus_di)
    else:
        nan_s = pd.Series(np.nan, index=close.index)
        res["adx_14"] = nan_s
        res["di_plus_14"] = nan_s
        res["di_minus_14"] = nan_s

    # Aroon
    window_aroon = 25
    if len(close) >= window_aroon:
        aroon_up = high.rolling(window_aroon + 1).apply(lambda x: float(np.argmax(x)) / window_aroon * 100.0, raw=True)
        aroon_down = low.rolling(window_aroon + 1).apply(lambda x: float(np.argmin(x)) / window_aroon * 100.0, raw=True)
        res["aroon_up"] = clean_finite_series(aroon_up)
        res["aroon_down"] = clean_finite_series(aroon_down)
        res["aroon_osc"] = clean_finite_series(aroon_up - aroon_down)
    else:
        nan_s = pd.Series(np.nan, index=close.index)
        res["aroon_up"] = nan_s
        res["aroon_down"] = nan_s
        res["aroon_osc"] = nan_s

    # TRIX
    trix_1 = calc_ema(close, 12)
    trix_2 = calc_ema(trix_1, 12)
    trix_3 = calc_ema(trix_2, 12)
    trix_line = trix_3.pct_change() * 100.0
    trix_signal = calc_sma(trix_line, 9)

    res["trix_12"] = clean_finite_series(trix_line)
    res["trix_signal"] = clean_finite_series(trix_signal)

    # KDJ (9, 3, 3)
    kdj_n = 9
    low_n = low.rolling(kdj_n, min_periods=kdj_n).min()
    high_n = high.rolling(kdj_n, min_periods=kdj_n).max()
    rsv = (close - low_n) / (high_n - low_n).replace(0, np.nan) * 100.0

    k_vals = []
    d_vals = []
    k_curr = 50.0
    d_curr = 50.0

    for r in rsv.fillna(50.0):
        k_curr = (2.0 / 3.0) * k_curr + (1.0 / 3.0) * r
        d_curr = (2.0 / 3.0) * d_curr + (1.0 / 3.0) * k_curr
        k_vals.append(k_curr)
        d_vals.append(d_curr)

    k_s = pd.Series(k_vals, index=close.index)
    d_s = pd.Series(d_vals, index=close.index)
    j_s = 3.0 * k_s - 2.0 * d_s

    res["kdj_k"] = clean_finite_series(k_s)
    res["kdj_d"] = clean_finite_series(d_s)
    res["kdj_j"] = clean_finite_series(j_s)

    return res
