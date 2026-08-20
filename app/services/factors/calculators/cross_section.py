import numpy as np
import pandas as pd
from typing import Dict, List, Optional
from app.services.factors.calculators.common import clean_finite_series, to_series


def calculate_cross_sectional_factors(
    universe_factor_matrix: pd.DataFrame,
    min_universe_symbols: int = 20
) -> Dict[str, pd.Series]:
    """
    计算 10 个 Cross-sectional & Composite 因子 (横截面矩阵: 行=symbol, 列=factor_name)
    若 valid 股票数 < 20，返回 NaN
    """
    n_valid = universe_factor_matrix.dropna(how="all").shape[0]
    res = {}

    if n_valid < min_universe_symbols:
        # 数量不足 20，返回 全 NaN Series
        nan_s = pd.Series(np.nan, index=universe_factor_matrix.index)
        for name in [
            "size_factor", "value_composite", "momentum_composite", "quality_composite",
            "growth_composite", "volatility_composite", "liquidity_composite",
            "sentiment_composite", "multi_factor_score", "industry_neutral_momentum"
        ]:
            res[name] = nan_s
        return res

    def _zscore(s: pd.Series) -> pd.Series:
        s_clean = s.copy()
        s_clean[np.isinf(s_clean)] = np.nan
        std = s_clean.std()
        if pd.isna(std) or std == 0:
            return pd.Series(np.nan, index=s.index)
        return (s_clean - s_clean.mean()) / std

    # Size Factor
    mkt_cap = universe_factor_matrix.get("market_cap", pd.Series(np.nan, index=universe_factor_matrix.index))
    size_factor = np.log(mkt_cap.replace(0, np.nan))
    res["size_factor"] = clean_finite_series(_zscore(size_factor))

    # Value Composite (B/P, E/P, S/P)
    v1 = _zscore(universe_factor_matrix.get("book_to_market", pd.Series(np.nan)))
    v2 = _zscore(universe_factor_matrix.get("earnings_yield", pd.Series(np.nan)))
    v3 = _zscore(universe_factor_matrix.get("sales_to_price", pd.Series(np.nan)))
    val_comp = pd.concat([v1, v2, v3], axis=1).mean(axis=1)
    res["value_composite"] = clean_finite_series(val_comp)

    # Momentum Composite (ret_20d, ret_60d, ret_120d)
    m1 = _zscore(universe_factor_matrix.get("ret_20d", pd.Series(np.nan)))
    m2 = _zscore(universe_factor_matrix.get("ret_60d", pd.Series(np.nan)))
    m3 = _zscore(universe_factor_matrix.get("ret_120d", pd.Series(np.nan)))
    mom_comp = pd.concat([m1, m2, m3], axis=1).mean(axis=1)
    res["momentum_composite"] = clean_finite_series(mom_comp)

    # Quality Composite (ROE, ROA, Gross Margin)
    q1 = _zscore(universe_factor_matrix.get("roe_ttm", pd.Series(np.nan)))
    q2 = _zscore(universe_factor_matrix.get("roa_ttm", pd.Series(np.nan)))
    q3 = _zscore(universe_factor_matrix.get("gross_margin", pd.Series(np.nan)))
    qual_comp = pd.concat([q1, q2, q3], axis=1).mean(axis=1)
    res["quality_composite"] = clean_finite_series(qual_comp)

    # Growth Composite (revenue_growth_yoy, net_profit_growth_yoy)
    g1 = _zscore(universe_factor_matrix.get("revenue_growth_yoy", pd.Series(np.nan)))
    g2 = _zscore(universe_factor_matrix.get("net_profit_growth_yoy", pd.Series(np.nan)))
    growth_comp = pd.concat([g1, g2], axis=1).mean(axis=1)
    res["growth_composite"] = clean_finite_series(growth_comp)

    # Volatility Composite (-volatility_20d, -max_drawdown_60d)
    vol1 = _zscore(-universe_factor_matrix.get("volatility_20d", pd.Series(np.nan)))
    vol2 = _zscore(-universe_factor_matrix.get("max_drawdown_60d", pd.Series(np.nan)))
    vol_comp = pd.concat([vol1, vol2], axis=1).mean(axis=1)
    res["volatility_composite"] = clean_finite_series(vol_comp)

    # Liquidity Composite (volume_sma_20, -amihud_illiquidity_20d)
    l1 = _zscore(universe_factor_matrix.get("volume_sma_20", pd.Series(np.nan)))
    l2 = _zscore(-universe_factor_matrix.get("amihud_illiquidity_20d", pd.Series(np.nan)))
    liq_comp = pd.concat([l1, l2], axis=1).mean(axis=1)
    res["liquidity_composite"] = clean_finite_series(liq_comp)

    # Sentiment Composite (news_sentiment_3d, social_sentiment_3d)
    s1 = _zscore(universe_factor_matrix.get("news_sentiment_3d", pd.Series(np.nan)))
    s2 = _zscore(universe_factor_matrix.get("social_sentiment_3d", pd.Series(np.nan)))
    sent_comp = pd.concat([s1, s2], axis=1).mean(axis=1)
    res["sentiment_composite"] = clean_finite_series(sent_comp)

    # Multi Factor Score
    multi_score = pd.concat([val_comp, mom_comp, qual_comp, growth_comp], axis=1).mean(axis=1)
    res["multi_factor_score"] = clean_finite_series(multi_score)

    # Industry Neutral Momentum
    ret20 = universe_factor_matrix.get("ret_20d", pd.Series(np.nan, index=universe_factor_matrix.index))
    res["industry_neutral_momentum"] = clean_finite_series(_zscore(ret20))

    return res
