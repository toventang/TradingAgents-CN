import numpy as np
import pandas as pd
from typing import Dict
from app.services.factors.calculators.common import (
    calc_sma,
    calc_std,
    clean_finite_series,
    to_series
)


def calculate_liquidity_factors(df: pd.DataFrame) -> Dict[str, pd.Series]:
    """计算 19 个 Liquidity & Volume 因子"""
    close = to_series(df["close"])
    high = to_series(df["high"]) if "high" in df else close
    low = to_series(df["low"]) if "low" in df else close
    volume = to_series(df["volume"]) if "volume" in df else pd.Series(0.0, index=close.index)
    amount = to_series(df["amount"]) if "amount" in df else volume * close
    turnover = to_series(df["turnover_rate"]) if "turnover_rate" in df else pd.Series(np.nan, index=close.index)

    res = {}
    returns = close.pct_change()

    # 成交量与换手率均值
    vol_sma5 = calc_sma(volume, 5)
    vol_sma20 = calc_sma(volume, 20)
    res["volume_sma_5"] = clean_finite_series(vol_sma5)
    res["volume_sma_20"] = clean_finite_series(vol_sma20)
    res["volume_ratio_5_20"] = clean_finite_series(vol_sma5 / vol_sma20.replace(0, np.nan))

    res["turnover_rate_sma_5"] = clean_finite_series(calc_sma(turnover, 5))
    res["turnover_rate_sma_20"] = clean_finite_series(calc_sma(turnover, 20))

    # Amihud 非流动性指标 (|ret| / amount)
    amount_safe = amount.replace(0, np.nan)
    daily_illiquidity = returns.abs() / amount_safe
    amihud_20d = daily_illiquidity.rolling(20, min_periods=20).mean()
    res["amihud_illiquidity_20d"] = clean_finite_series(amihud_20d)

    # MFI (14)
    tp = (high + low + close) / 3.0
    raw_money_flow = tp * volume
    tp_diff = tp.diff()
    pos_flow = np.where(tp_diff > 0, raw_money_flow, 0.0)
    neg_flow = np.where(tp_diff < 0, raw_money_flow, 0.0)

    pos_mf = pd.Series(pos_flow, index=close.index).rolling(14, min_periods=14).sum()
    neg_mf = pd.Series(neg_flow, index=close.index).rolling(14, min_periods=14).sum()
    mfr = pos_mf / neg_mf.replace(0, np.nan)
    mfi = 100.0 - (100.0 / (1.0 + mfr))
    res["mfi_14"] = clean_finite_series(mfi)

    # CMF (20)
    hl_range = (high - low).replace(0, np.nan)
    mf_multiplier = ((close - low) - (high - close)) / hl_range
    mf_volume = mf_multiplier * volume
    cmf = mf_volume.rolling(20, min_periods=20).sum() / volume.rolling(20, min_periods=20).sum().replace(0, np.nan)
    res["cmf_20"] = clean_finite_series(cmf)

    # OBV
    obv_direction = np.sign(returns.fillna(0.0))
    obv = (obv_direction * volume).cumsum()
    res["obv"] = clean_finite_series(obv)
    res["obv_sma_20"] = clean_finite_series(calc_sma(obv, 20))

    # PVT
    pvt = (returns * volume).cumsum()
    res["pvt"] = clean_finite_series(pvt)

    # NVI & PVI
    vol_diff = volume.diff()
    nvi = [1000.0]
    pvi = [1000.0]
    ret_vals = returns.fillna(0.0).values
    vol_diff_vals = vol_diff.fillna(0.0).values

    for i in range(1, len(close)):
        r = ret_vals[i]
        vd = vol_diff_vals[i]
        nvi_prev = nvi[-1]
        pvi_prev = pvi[-1]

        if vd < 0:
            nvi.append(nvi_prev * (1.0 + r))
        else:
            nvi.append(nvi_prev)

        if vd > 0:
            pvi.append(pvi_prev * (1.0 + r))
        else:
            pvi.append(pvi_prev)

    res["nvi"] = clean_finite_series(pd.Series(nvi, index=close.index))
    res["pvi"] = clean_finite_series(pd.Series(pvi, index=close.index))

    # EOM (14)
    distance_moved = ((high + low) / 2.0).diff()
    box_ratio = (volume / 10000.0) / hl_range
    eom_1 = distance_moved / box_ratio.replace(0, np.nan)
    res["eom_14"] = clean_finite_series(calc_sma(eom_1, 14))

    # A/D Line
    ad_flow = mf_multiplier.fillna(0.0) * volume
    res["ad_line"] = clean_finite_series(ad_flow.cumsum())

    # 成交量波动率与偏度
    res["volume_std_20d"] = clean_finite_series(calc_std(volume, 20))
    res["volume_skew_20d"] = clean_finite_series(volume.rolling(20, min_periods=20).skew())

    # Bid-Ask Spread Estimate (Corwin-Schultz simplified estimator)
    log_hl = np.log((high / low.replace(0, np.nan)).replace(0, np.nan))
    spread_est = (2.0 * (np.exp(log_hl) - 1.0) / (1.0 + np.exp(log_hl))).rolling(20, min_periods=20).mean()
    res["bid_ask_spread_est"] = clean_finite_series(spread_est)

    # 流动性比率 (20d)
    sum_amount = amount.rolling(20, min_periods=20).sum()
    sum_abs_pct = returns.abs().rolling(20, min_periods=20).sum().replace(0, np.nan)
    res["liquidity_ratio_20d"] = clean_finite_series(sum_amount / sum_abs_pct)

    return res
