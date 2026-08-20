import numpy as np
import pandas as pd
from typing import Dict, Optional
from app.services.factors.calculators.common import (
    calc_sma,
    calc_ema,
    calc_std,
    clean_finite_series,
    to_series
)


def calculate_volatility_factors(
    df: pd.DataFrame,
    annual_days: int = 242
) -> Dict[str, pd.Series]:
    """计算 20 个 Volatility & Risk 因子"""
    close = to_series(df["close"])
    high = to_series(df["high"]) if "high" in df else close
    low = to_series(df["low"]) if "low" in df else close

    res = {}
    returns = close.pct_change()

    # 年化波动率
    for days in [5, 20, 60, 240]:
        vol = calc_std(returns, days) * np.sqrt(annual_days)
        res[f"volatility_{days}d"] = clean_finite_series(vol)

    # ATR & NATR
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)

    atr_14 = tr.rolling(14, min_periods=14).mean()
    atr_20 = tr.rolling(20, min_periods=20).mean()
    natr_14 = (atr_14 / close.replace(0, np.nan)) * 100.0

    res["atr_14"] = clean_finite_series(atr_14)
    res["atr_20"] = clean_finite_series(atr_20)
    res["natr_14"] = clean_finite_series(natr_14)

    # 布林线 (Bollinger Bands - 20d, 2 std)
    sma_20 = calc_sma(close, 20)
    std_20 = calc_std(close, 20)
    b_upper = sma_20 + 2.0 * std_20
    b_lower = sma_20 - 2.0 * std_20
    b_width = (b_upper - b_lower) / sma_20.replace(0, np.nan)
    pct_b = (close - b_lower) / (b_upper - b_lower).replace(0, np.nan)

    res["bbands_upper"] = clean_finite_series(b_upper)
    res["bbands_middle"] = clean_finite_series(sma_20)
    res["bbands_lower"] = clean_finite_series(b_lower)
    res["bbands_bandwidth"] = clean_finite_series(b_width)
    res["bbands_pct_b"] = clean_finite_series(pct_b)

    # 肯特纳通道 (Keltner Channels - 20d EMA, 10d ATR * 2)
    kc_mid = calc_ema(close, 20)
    atr_10 = tr.rolling(10, min_periods=10).mean()
    kc_upper = kc_mid + 2.0 * atr_10
    kc_lower = kc_mid - 2.0 * atr_10

    res["kc_upper"] = clean_finite_series(kc_upper)
    res["kc_middle"] = clean_finite_series(kc_mid)
    res["kc_lower"] = clean_finite_series(kc_lower)

    # 唐奇安通道 (Donchian Channels - 20d)
    donch_h = high.rolling(20, min_periods=20).max()
    donch_l = low.rolling(20, min_periods=20).min()

    res["donchian_high"] = clean_finite_series(donch_h)
    res["donchian_low"] = clean_finite_series(donch_l)

    # VaR 95% 与 CVaR 95% (20d, 正损约定)
    w_var = 20
    var_list = []
    cvar_list = []

    ret_vals = returns.values
    for i in range(len(returns)):
        if i < w_var:
            var_list.append(np.nan)
            cvar_list.append(np.nan)
        else:
            win = ret_vals[i - w_var + 1 : i + 1]
            win_valid = win[~np.isnan(win)]
            if len(win_valid) >= w_var * 0.8:
                var_val = -np.percentile(win_valid, 5)  # 5th percentile return, negated
                tail = win_valid[win_valid <= -var_val]
                cvar_val = -np.mean(tail) if len(tail) > 0 else var_val
                var_list.append(var_val)
                cvar_list.append(cvar_val)
            else:
                var_list.append(np.nan)
                cvar_list.append(np.nan)

    res["var_95_20d"] = clean_finite_series(pd.Series(var_list, index=close.index))
    res["cvar_95_20d"] = clean_finite_series(pd.Series(cvar_list, index=close.index))

    # 最大回撤 (60d)
    w_dd = 60
    mdd_list = []
    close_vals = close.values

    for i in range(len(close)):
        if i < w_dd - 1:
            mdd_list.append(np.nan)
        else:
            win = close_vals[i - w_dd + 1 : i + 1]
            peak = np.maximum.accumulate(win)
            drawdown = (peak - win) / peak
            mdd_list.append(np.max(drawdown))

    res["max_drawdown_60d"] = clean_finite_series(pd.Series(mdd_list, index=close.index))

    return res
