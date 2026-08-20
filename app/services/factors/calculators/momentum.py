import numpy as np
import pandas as pd
from typing import Dict
from app.services.factors.calculators.common import (
    calc_rsi,
    calc_sma,
    calc_ema,
    clean_finite_series,
    to_series
)


def calculate_momentum_factors(df: pd.DataFrame) -> Dict[str, pd.Series]:
    """计算 18 个 Momentum 因子"""
    close = to_series(df["close"])
    high = to_series(df["high"]) if "high" in df else close
    low = to_series(df["low"]) if "low" in df else close

    res = {}

    # RSI
    for w in [6, 12, 24]:
        res[f"rsi_{w}"] = clean_finite_series(calc_rsi(close, w))

    # StochRSI (14)
    rsi14 = calc_rsi(close, 14)
    rsi14_min = rsi14.rolling(14, min_periods=14).min()
    rsi14_max = rsi14.rolling(14, min_periods=14).max()
    stoch_rsi = (rsi14 - rsi14_min) / (rsi14_max - rsi14_min).replace(0, np.nan)
    stoch_k = calc_sma(stoch_rsi, 3)
    stoch_d = calc_sma(stoch_k, 3)

    res["stoch_rsi_k"] = clean_finite_series(stoch_k * 100.0)
    res["stoch_rsi_d"] = clean_finite_series(stoch_d * 100.0)

    # CCI
    tp = (high + low + close) / 3.0
    for w in [14, 20]:
        tp_sma = calc_sma(tp, w)
        mad = tp.rolling(w, min_periods=w).apply(lambda x: np.mean(np.abs(x - np.mean(x))), raw=True)
        cci = (tp - tp_sma) / (0.015 * mad.replace(0, np.nan))
        res[f"cci_{w}"] = clean_finite_series(cci)

    # Williams %R
    w_n = 14
    hh = high.rolling(w_n, min_periods=w_n).max()
    ll = low.rolling(w_n, min_periods=w_n).min()
    willr = -100.0 * (hh - close) / (hh - ll).replace(0, np.nan)
    res["willr_14"] = clean_finite_series(willr)

    # ROC
    for days in [5, 10, 20, 60]:
        roc = (close - close.shift(days)) / close.shift(days).replace(0, np.nan) * 100.0
        res[f"roc_{days}"] = clean_finite_series(roc)

    # TSI (13, 25)
    diff = close.diff()
    double_smoothed_diff = calc_ema(calc_ema(diff, 13), 25)
    double_smoothed_abs_diff = calc_ema(calc_ema(diff.abs(), 13), 25)
    tsi = 100.0 * double_smoothed_diff / double_smoothed_abs_diff.replace(0, np.nan)
    res["tsi_13_25"] = clean_finite_series(tsi)

    # Ultimate Oscillator (7, 14, 28)
    prev_close = close.shift(1)
    bp = close - np.minimum(low, prev_close)
    tr = np.maximum(high, prev_close) - np.minimum(low, prev_close)

    avg7 = bp.rolling(7).sum() / tr.rolling(7).sum().replace(0, np.nan)
    avg14 = bp.rolling(14).sum() / tr.rolling(14).sum().replace(0, np.nan)
    avg28 = bp.rolling(28).sum() / tr.rolling(28).sum().replace(0, np.nan)

    uo = 100.0 * (4.0 * avg7 + 2.0 * avg14 + avg28) / 7.0
    res["uo_7_14_28"] = clean_finite_series(uo)

    # AO (Awesome Oscillator 5, 34)
    median_price = (high + low) / 2.0
    ao = calc_sma(median_price, 5) - calc_sma(median_price, 34)
    res["ao_5_34"] = clean_finite_series(ao)

    # Momentum
    for days in [10, 20, 60]:
        mom = close - close.shift(days)
        res[f"momentum_{days}"] = clean_finite_series(mom)

    return res
