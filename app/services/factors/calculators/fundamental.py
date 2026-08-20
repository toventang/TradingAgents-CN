import numpy as np
import pandas as pd
from typing import Dict, Any, Optional
from app.services.factors.calculators.common import clean_finite_series, to_series


def calculate_fundamental_factors(
    df: pd.DataFrame,
    financial_data: Optional[Dict[str, Any]] = None
) -> Dict[str, pd.Series]:
    """计算 51 个 Valuation(15), Quality(20), Growth(16) 基本面因子"""
    close = to_series(df["close"])
    res = {}

    fin = financial_data or {}

    def _get_val(key: str, default: float = np.nan) -> float:
        val = fin.get(key, default)
        try:
            return float(val) if val is not None else np.nan
        except (ValueError, TypeError):
            return np.nan

    def _make_const_series(val: float) -> pd.Series:
        return pd.Series(val if (val is not None and not np.isinf(val)) else np.nan, index=close.index)

    # 1. Valuation (15)
    pe_ttm = _get_val("pe_ttm", _get_val("pe"))
    pe_lyr = _get_val("pe_lyr")
    pb_mrq = _get_val("pb_mrq", _get_val("pb"))
    ps_ttm = _get_val("ps_ttm", _get_val("ps"))
    pcf_ttm = _get_val("pcf_ttm", _get_val("pcf"))
    ev_ebitda = _get_val("ev_ebitda")
    div_yield = _get_val("dividend_yield")
    peg = _get_val("peg_ratio")
    ev = _get_val("enterprise_value")
    mkt_cap = _get_val("total_mv", _get_val("market_cap"))
    circ_mkt_cap = _get_val("circ_mv", _get_val("circulating_market_cap"))

    res["pe_ttm"] = clean_finite_series(_make_const_series(pe_ttm))
    res["pe_lyr"] = clean_finite_series(_make_const_series(pe_lyr))
    res["pb_mrq"] = clean_finite_series(_make_const_series(pb_mrq))
    res["ps_ttm"] = clean_finite_series(_make_const_series(ps_ttm))
    res["pcf_ttm"] = clean_finite_series(_make_const_series(pcf_ttm))
    res["ev_ebitda"] = clean_finite_series(_make_const_series(ev_ebitda))
    res["dividend_yield"] = clean_finite_series(_make_const_series(div_yield))

    # 倒数因子 (EP / BP / SP / CF_P)
    res["earnings_yield"] = clean_finite_series(_make_const_series(1.0 / pe_ttm if pe_ttm and pe_ttm > 0 else np.nan))
    res["book_to_market"] = clean_finite_series(_make_const_series(1.0 / pb_mrq if pb_mrq and pb_mrq > 0 else np.nan))
    res["sales_to_price"] = clean_finite_series(_make_const_series(1.0 / ps_ttm if ps_ttm and ps_ttm > 0 else np.nan))
    res["cash_to_price"] = clean_finite_series(_make_const_series(1.0 / pcf_ttm if pcf_ttm and pcf_ttm > 0 else np.nan))

    res["peg_ratio"] = clean_finite_series(_make_const_series(peg))
    res["enterprise_value"] = clean_finite_series(_make_const_series(ev))
    res["market_cap"] = clean_finite_series(_make_const_series(mkt_cap))
    res["circulating_market_cap"] = clean_finite_series(_make_const_series(circ_mkt_cap))

    # 2. Quality (20)
    res["roe_ttm"] = clean_finite_series(_make_const_series(_get_val("roe")))
    res["roa_ttm"] = clean_finite_series(_make_const_series(_get_val("roa")))
    res["roic_ttm"] = clean_finite_series(_make_const_series(_get_val("roic")))
    res["gross_margin"] = clean_finite_series(_make_const_series(_get_val("gross_margin")))
    res["net_margin"] = clean_finite_series(_make_const_series(_get_val("netprofit_margin", _get_val("net_margin"))))
    res["operating_margin"] = clean_finite_series(_make_const_series(_get_val("operating_margin")))
    res["ebitda_margin"] = clean_finite_series(_make_const_series(_get_val("ebitda_margin")))

    res["asset_turnover"] = clean_finite_series(_make_const_series(_get_val("asset_turnover")))
    res["inventory_turnover"] = clean_finite_series(_make_const_series(_get_val("inventory_turnover")))
    res["receivables_turnover"] = clean_finite_series(_make_const_series(_get_val("receivables_turnover")))

    res["current_ratio"] = clean_finite_series(_make_const_series(_get_val("current_ratio")))
    res["quick_ratio"] = clean_finite_series(_make_const_series(_get_val("quick_ratio")))
    res["cash_ratio"] = clean_finite_series(_make_const_series(_get_val("cash_ratio")))
    res["debt_to_assets"] = clean_finite_series(_make_const_series(_get_val("debt_to_assets")))
    res["debt_to_equity"] = clean_finite_series(_make_const_series(_get_val("debt_to_equity")))
    res["interest_coverage"] = clean_finite_series(_make_const_series(_get_val("interest_coverage")))
    res["free_cash_flow_to_revenue"] = clean_finite_series(_make_const_series(_get_val("fcf_to_revenue")))
    res["accruals_ratio"] = clean_finite_series(_make_const_series(_get_val("accruals_ratio")))
    res["dupont_roe"] = clean_finite_series(_make_const_series(_get_val("dupont_roe", _get_val("roe"))))
    res["piotroski_f_score"] = clean_finite_series(_make_const_series(_get_val("piotroski_f_score", 5.0)))

    # 3. Growth (16)
    res["revenue_growth_yoy"] = clean_finite_series(_make_const_series(_get_val("revenue_growth_yoy", _get_val("tr_yoy"))))
    res["net_profit_growth_yoy"] = clean_finite_series(_make_const_series(_get_val("net_profit_growth_yoy", _get_val("netprofit_yoy"))))
    res["operating_profit_growth_yoy"] = clean_finite_series(_make_const_series(_get_val("operating_profit_growth_yoy")))
    res["eps_growth_yoy"] = clean_finite_series(_make_const_series(_get_val("eps_growth_yoy")))
    res["fcf_growth_yoy"] = clean_finite_series(_make_const_series(_get_val("fcf_growth_yoy")))
    res["total_asset_growth_yoy"] = clean_finite_series(_make_const_series(_get_val("asset_growth_yoy")))
    res["equity_growth_yoy"] = clean_finite_series(_make_const_series(_get_val("equity_growth_yoy")))

    res["revenue_cagr_3y"] = clean_finite_series(_make_const_series(_get_val("revenue_cagr_3y")))
    res["net_profit_cagr_3y"] = clean_finite_series(_make_const_series(_get_val("net_profit_cagr_3y")))

    res["revenue_qoq"] = clean_finite_series(_make_const_series(_get_val("revenue_qoq")))
    res["net_profit_qoq"] = clean_finite_series(_make_const_series(_get_val("net_profit_qoq")))
    res["gross_profit_growth_yoy"] = clean_finite_series(_make_const_series(_get_val("gross_profit_growth_yoy")))
    res["ebitda_growth_yoy"] = clean_finite_series(_make_const_series(_get_val("ebitda_growth_yoy")))
    res["operating_cash_flow_growth_yoy"] = clean_finite_series(_make_const_series(_get_val("ocf_growth_yoy")))
    res["sales_surprise"] = clean_finite_series(_make_const_series(_get_val("sales_surprise")))
    res["earnings_surprise"] = clean_finite_series(_make_const_series(_get_val("earnings_surprise")))

    return res
