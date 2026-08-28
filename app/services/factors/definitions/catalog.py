"""Version-one built-in factor metadata catalog.

This module contains declarations only.  Formula references are inert registry
keys; importing this catalog cannot execute or dynamically import a formula.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from app.models.factor import (
    FactorCategory,
    FactorDefinition,
    FactorDirection,
    FactorGroup,
    MissingValuePolicy,
    NormalizeMethod,
    ParameterSpec,
    ParameterType,
    WinsorizeMethod,
)
from app.models.symbol import Market


CATALOG_GROUP_COUNTS = {
    FactorGroup.RETURN_PRICE: 18,
    FactorGroup.TREND: 23,
    FactorGroup.MOMENTUM: 18,
    FactorGroup.VOLATILITY_RISK: 20,
    FactorGroup.LIQUIDITY: 19,
    FactorGroup.VALUATION: 15,
    FactorGroup.QUALITY: 20,
    FactorGroup.GROWTH: 16,
    FactorGroup.SENTIMENT_EVENT: 12,
    FactorGroup.CROSS_COMPOSITE: 10,
}

# The referenced 4.3.7 table enumerates 21 IDs while J11's authoritative
# packet fixes the quality group at 20 and the catalog at 171.  V1 retains the
# first 20 enumerated IDs and records the overflow explicitly rather than
# silently changing the count.
V1_EXCLUDED_OVERFLOW_IDS = ("retained_earnings_to_assets",)


_GROUP_IDS: dict[FactorCategory, tuple[str, ...]] = {
    FactorCategory.PRICE: (
        "ret_1d", "ret_3d", "ret_5d", "ret_10d", "ret_20d", "ret_60d", "ret_120d", "ret_250d",
        "log_ret_1d", "gap_open_1d", "intraday_ret", "intraday_range", "close_location_value",
        "distance_20d_high", "distance_60d_high", "distance_250d_high",
        "distance_20d_low", "distance_60d_low",
    ),
    FactorCategory.TREND: (
        "ma_ratio_5", "ma_ratio_10", "ma_ratio_20", "ma_ratio_60", "ma_ratio_120", "ma_ratio_250",
        "ema_ratio_5", "ema_ratio_10", "ema_ratio_20", "ema_ratio_60",
        "ma_cross_5_20", "ma_cross_10_60", "ma_cross_20_60", "ma_cross_60_250",
        "macd_dif", "macd_dea", "macd_hist", "adx_14", "aroon_up_25", "aroon_down_25",
        "linear_slope_20", "linear_slope_60", "trend_r2_60",
    ),
    FactorCategory.MOMENTUM: (
        "rsi_6", "rsi_12", "rsi_14", "rsi_24", "roc_5", "roc_10", "roc_20", "roc_60",
        "kdj_k", "kdj_d", "kdj_j", "cci_14", "williams_r_14", "momentum_10",
        "ppo_12_26", "trix_15", "ultimate_osc_7_14_28", "dpo_20",
    ),
    FactorCategory.VOLATILITY: (
        "hist_vol_5", "hist_vol_10", "hist_vol_20", "hist_vol_60", "hist_vol_120",
        "atr_14", "atr_pct_14", "downside_vol_20", "downside_vol_60",
        "max_drawdown_20", "max_drawdown_60", "max_drawdown_250",
        "beta_60", "beta_250", "alpha_60", "idio_vol_60", "var_95_20", "cvar_95_60",
        "return_skew_60", "return_kurt_60",
    ),
    FactorCategory.LIQUIDITY: (
        "volume_ratio_5", "volume_ratio_20", "volume_ratio_60", "amount_ratio_5", "amount_ratio_20",
        "turnover_rate", "turnover_mean_20", "turnover_std_20", "obv", "obv_change_20", "mfi_14",
        "cmf_20", "adl_change_20", "vwap_deviation_20", "price_volume_corr_20",
        "price_volume_corr_60", "volume_volatility_20", "amihud_illiq_20", "zero_volume_days_20",
    ),
    FactorCategory.VALUATION: (
        "pe_ttm", "pb_mrq", "ps_ttm", "pcf_ttm", "earnings_yield", "book_to_price",
        "sales_to_price", "cashflow_to_price", "dividend_yield_ttm", "ev_to_ebitda", "ev_to_ebit",
        "ev_to_sales", "peg", "market_cap_log", "free_float_cap_log",
    ),
    FactorCategory.QUALITY: (
        "roe_ttm", "roa_ttm", "roic_ttm", "gross_margin_ttm", "operating_margin_ttm",
        "net_margin_ttm", "fcf_margin_ttm", "cfo_to_net_income", "accruals_ratio",
        "asset_turnover_ttm", "inventory_turnover_ttm", "receivable_turnover_ttm",
        "current_ratio", "quick_ratio", "cash_ratio", "debt_to_assets", "debt_to_equity",
        "interest_coverage", "operating_cashflow_ratio", "goodwill_to_assets",
    ),
    FactorCategory.GROWTH: (
        "revenue_yoy", "net_profit_yoy", "eps_yoy", "cfo_yoy", "revenue_cagr_3y",
        "net_profit_cagr_3y", "eps_cagr_3y", "roe_change_yoy", "gross_margin_change_yoy",
        "revenue_stability_8q", "profit_stability_8q", "positive_profit_quarters_8q",
        "positive_cfo_quarters_8q", "consecutive_revenue_growth_q",
        "consecutive_profit_growth_q", "sustainable_growth_rate",
    ),
    FactorCategory.SENTIMENT: (
        "news_sentiment_1d", "news_sentiment_7d", "news_sentiment_30d", "news_volume_zscore_7d",
        "negative_news_ratio_7d", "social_sentiment_1d", "social_sentiment_7d",
        "social_volume_zscore_7d", "limit_up_count_20", "limit_down_count_20",
        "gap_event_20", "suspension_days_20",
    ),
    FactorCategory.CROSS_SECTION: (
        "industry_momentum_rank_20", "market_momentum_rank_20", "value_composite",
        "quality_composite", "growth_composite", "momentum_composite", "low_vol_composite",
        "liquidity_composite", "sentiment_composite", "multi_factor_score",
    ),
}


_CATEGORY_NAMES = {
    FactorCategory.PRICE: "收益与价格",
    FactorCategory.TREND: "趋势",
    FactorCategory.MOMENTUM: "动量与摆动",
    FactorCategory.VOLATILITY: "波动与风险",
    FactorCategory.LIQUIDITY: "成交量与流动性",
    FactorCategory.VALUATION: "估值",
    FactorCategory.QUALITY: "质量与偿债",
    FactorCategory.GROWTH: "成长与稳定性",
    FactorCategory.SENTIMENT: "情绪与事件",
    FactorCategory.EVENT: "情绪与事件",
    FactorCategory.CROSS_SECTION: "横截面与复合",
    FactorCategory.COMPOSITE: "横截面与复合",
}

_SPECIAL_NAMES = {
    "ret_1d": "1日收益率",
    "ret_3d": "3日收益率",
    "ret_5d": "5日收益率",
    "ret_10d": "10日收益率",
    "ret_20d": "20日收益率",
    "ret_60d": "60日收益率",
    "ret_120d": "120日收益率",
    "ret_250d": "250日收益率",
}

_DESCRIPTIONS = {
    "log_ret_1d": "自然对数日收益 ln(close / pre_close)。",
    "gap_open_1d": "开盘相对前收盘的跳空收益 open / pre_close - 1。",
    "intraday_ret": "日内收益 close / open - 1。",
    "intraday_range": "日内振幅 (high - low) / pre_close。",
    "close_location_value": "收盘在日内高低区间的位置；零区间返回缺失。",
    "macd_hist": "MACD DIF 与 DEA 之差，统一口径不乘 2。",
    "var_95_20": "20日历史法 95% 单日 VaR，输出正损失值。",
    "cvar_95_60": "60日超过 95% VaR 阈值样本的平均正损失。",
    "amihud_illiq_20": "20日 mean(abs(return) / amount)，金额使用统一货币单位。",
    "peg": "PE 与已披露历史增长或有来源的一致预期之比，禁止使用未来增长。",
    "multi_factor_score": "用户显式指定因子权重的组合分数；不得使用隐含权重。",
}

_DEPENDENCIES = {
    "earnings_yield": ("pe_ttm",),
    "book_to_price": ("pb_mrq",),
    "sales_to_price": ("ps_ttm",),
    "cashflow_to_price": ("pcf_ttm",),
    "industry_momentum_rank_20": ("ret_20d",),
    "market_momentum_rank_20": ("ret_20d",),
    "value_composite": ("earnings_yield", "book_to_price", "sales_to_price"),
    "quality_composite": ("roe_ttm", "roic_ttm", "cfo_to_net_income", "accruals_ratio", "debt_to_assets"),
    "growth_composite": ("revenue_yoy", "net_profit_yoy", "eps_yoy", "cfo_yoy"),
    "momentum_composite": ("ret_1d", "ret_20d", "ret_60d", "ret_120d"),
    "low_vol_composite": ("hist_vol_20", "downside_vol_20", "beta_60", "max_drawdown_60"),
    "liquidity_composite": ("turnover_mean_20", "amount_ratio_20", "amihud_illiq_20"),
    "sentiment_composite": ("news_sentiment_7d", "social_sentiment_7d", "news_volume_zscore_7d"),
}


def _columns(factor_id: str, category: FactorCategory) -> tuple[str, ...]:
    if factor_id in _DEPENDENCIES:
        return ()
    if category == FactorCategory.PRICE:
        if factor_id == "gap_open_1d": return ("open", "pre_close")
        if factor_id == "intraday_ret": return ("open", "close")
        if factor_id == "intraday_range": return ("high", "low", "pre_close")
        if factor_id == "close_location_value": return ("high", "low", "close")
        return ("close", "pre_close")
    if category in {FactorCategory.TREND, FactorCategory.MOMENTUM}:
        if factor_id.startswith("adx_"): return ("high", "low", "close", "pre_close")
        if factor_id.startswith("aroon_up_"): return ("high",)
        if factor_id.startswith("aroon_down_"): return ("low",)
        if factor_id.startswith(("kdj_", "cci_", "williams_")): return ("high", "low", "close")
        if factor_id.startswith("ultimate_"): return ("high", "low", "close", "pre_close")
        return ("close",)
    if category == FactorCategory.VOLATILITY:
        if factor_id.startswith(("atr_", "atr_pct_")): return ("high", "low", "close", "pre_close")
        if factor_id.startswith(("beta_", "alpha_", "idio_vol_")): return ("close", "benchmark_close")
        return ("close",)
    if category == FactorCategory.LIQUIDITY:
        if factor_id.startswith("amount_"): return ("amount",)
        if factor_id.startswith("amihud_"): return ("close", "amount")
        if factor_id.startswith("turnover_") or factor_id == "turnover_rate": return ("turnover_rate",)
        if factor_id == "mfi_14": return ("high", "low", "close", "volume")
        if factor_id in {"cmf_20", "adl_change_20"}: return ("high", "low", "close", "volume")
        if factor_id == "vwap_deviation_20": return ("close", "volume", "amount")
        if factor_id.startswith("volume_") or factor_id == "zero_volume_days_20": return ("volume",)
        return ("close", "volume")
    if category == FactorCategory.VALUATION:
        mapping = {
            "pe_ttm": ("market_cap", "net_profit_ttm"), "pb_mrq": ("market_cap", "equity_mrq"),
            "ps_ttm": ("market_cap", "revenue_ttm"), "pcf_ttm": ("market_cap", "operating_cashflow_ttm"),
            "dividend_yield_ttm": ("cash_dividend_ttm", "market_cap"),
            "ev_to_ebitda": ("enterprise_value", "ebitda_ttm"), "ev_to_ebit": ("enterprise_value", "ebit_ttm"),
            "ev_to_sales": ("enterprise_value", "revenue_ttm"), "peg": ("pe_ttm", "historical_growth"),
            "market_cap_log": ("market_cap",), "free_float_cap_log": ("free_float_market_cap",),
        }
        return mapping.get(factor_id, ())
    if category == FactorCategory.QUALITY:
        return _fundamental_columns(factor_id)
    if category == FactorCategory.GROWTH:
        return _growth_columns(factor_id)
    if category in {FactorCategory.SENTIMENT, FactorCategory.EVENT}:
        if factor_id == "news_volume_zscore_7d": return ("news_published_at", "news_ingested_at")
        if factor_id.startswith("news_") or factor_id == "negative_news_ratio_7d":
            return ("news_published_at", "news_ingested_at", "news_sentiment", "news_source")
        if factor_id == "social_volume_zscore_7d": return ("social_published_at", "social_ingested_at")
        if factor_id.startswith("social_"):
            return ("social_published_at", "social_ingested_at", "social_sentiment")
        if factor_id in {"limit_up_count_20", "limit_down_count_20"}:
            return ("market", "board", "trade_date", "close", "pre_close")
        if factor_id == "gap_event_20": return ("open", "pre_close", "close")
        return ("suspended",)
    return ()


def _fundamental_columns(factor_id: str) -> tuple[str, ...]:
    mapping = {
        "roe_ttm": ("net_profit_ttm", "average_equity"), "roa_ttm": ("net_profit_ttm", "average_assets"),
        "roic_ttm": ("nopat_ttm", "invested_capital"), "gross_margin_ttm": ("gross_profit_ttm", "revenue_ttm"),
        "operating_margin_ttm": ("operating_profit_ttm", "revenue_ttm"),
        "net_margin_ttm": ("net_profit_ttm", "revenue_ttm"), "fcf_margin_ttm": ("free_cashflow_ttm", "revenue_ttm"),
        "cfo_to_net_income": ("operating_cashflow_ttm", "net_profit_ttm"),
        "accruals_ratio": ("net_profit_ttm", "operating_cashflow_ttm", "average_assets"),
        "asset_turnover_ttm": ("revenue_ttm", "average_assets"),
        "inventory_turnover_ttm": ("cost_of_revenue_ttm", "average_inventory"),
        "receivable_turnover_ttm": ("revenue_ttm", "average_receivables"),
        "current_ratio": ("current_assets", "current_liabilities"),
        "quick_ratio": ("quick_assets", "current_liabilities"), "cash_ratio": ("cash", "current_liabilities"),
        "debt_to_assets": ("total_debt", "total_assets"), "debt_to_equity": ("total_debt", "total_equity"),
        "interest_coverage": ("ebit_ttm", "interest_expense_ttm"),
        "operating_cashflow_ratio": ("operating_cashflow_ttm", "current_liabilities"),
        "goodwill_to_assets": ("goodwill", "total_assets"),
    }
    return mapping[factor_id]


def _growth_columns(factor_id: str) -> tuple[str, ...]:
    if factor_id == "sustainable_growth_rate": return ("roe_ttm", "retention_ratio")
    if factor_id.startswith("revenue_"): return ("revenue", "publish_at", "report_period")
    if factor_id.startswith(("net_profit_", "profit_", "positive_profit", "consecutive_profit")):
        return ("net_profit", "publish_at", "report_period")
    if factor_id.startswith("eps_"): return ("eps", "publish_at", "report_period")
    if factor_id.startswith(("cfo_", "positive_cfo")): return ("operating_cashflow", "publish_at", "report_period")
    if factor_id.startswith("roe_"): return ("roe", "publish_at", "report_period")
    return ("gross_margin", "publish_at", "report_period")


def _parameter_metadata(factor_id: str) -> tuple[dict[str, ParameterSpec], dict[str, object]]:
    if factor_id == "multi_factor_score":
        schema = ParameterSpec(
            type=ParameterType.OBJECT, required=True, min_properties=1,
            description="Explicit factor_id to weight mapping",
        )
        return {"weights": schema}, {}
    if factor_id.startswith("macd_"):
        return _integer_params(fast=12, slow=26, signal=9, hist_multiplier=1)
    if factor_id.startswith("kdj_"):
        return _integer_params(window=9, k_smoothing=3, d_smoothing=3)
    if factor_id == "ppo_12_26": return _integer_params(fast=12, slow=26)
    if factor_id == "ultimate_osc_7_14_28": return _integer_params(short=7, medium=14, long=28)
    if factor_id in {"var_95_20", "cvar_95_60"}:
        window = 20 if factor_id == "var_95_20" else 60
        schema, defaults = _integer_params(window=window)
        schema["confidence"] = ParameterSpec(type=ParameterType.NUMBER, minimum=0.5, maximum=0.999)
        defaults["confidence"] = 0.95
        return schema, defaults
    if factor_id.startswith("rsi_"):
        window = max(int(value) for value in re.findall(r"\d+", factor_id))
        schema, defaults = _integer_params(window=window)
        schema["method"] = ParameterSpec(type=ParameterType.STRING, choices=("wilder",))
        defaults["method"] = "wilder"
        return schema, defaults
    if factor_id.startswith("hist_vol_"):
        window = max(int(value) for value in re.findall(r"\d+", factor_id))
        schema, defaults = _integer_params(window=window)
        schema["annualization"] = ParameterSpec(
            type=ParameterType.STRING, choices=("market_trading_days",)
        )
        defaults["annualization"] = "market_trading_days"
        return schema, defaults
    if factor_id in {"news_volume_zscore_7d", "social_volume_zscore_7d"}:
        schema, defaults = _integer_params(window=7, baseline_window=60)
        return schema, defaults
    if factor_id == "gap_event_20":
        schema, defaults = _integer_params(window=20)
        schema["volatility_multiple"] = ParameterSpec(type=ParameterType.NUMBER, minimum=0.1, maximum=20)
        defaults["volatility_multiple"] = 2.0
        return schema, defaults
    numbers = [int(value) for value in re.findall(r"(?:^|_)(\d+)(?:d|q|y)?(?:_|$)", factor_id)]
    if not numbers:
        return {}, {}
    return _integer_params(window=max(numbers))


def _integer_params(**values: int) -> tuple[dict[str, ParameterSpec], dict[str, object]]:
    return (
        {name: ParameterSpec(type=ParameterType.INTEGER, minimum=1, maximum=5000) for name in values},
        dict(values),
    )


def _min_history(factor_id: str, category: FactorCategory) -> int:
    if category in {FactorCategory.VALUATION, FactorCategory.QUALITY}: return 1
    if category == FactorCategory.GROWTH:
        if "8q" in factor_id or factor_id.endswith("_q"): return 8
        if "3y" in factor_id: return 4
        return 5
    numbers = [int(value) for value in re.findall(r"\d+", factor_id)]
    return max(numbers, default=1) + (1 if category in {FactorCategory.PRICE, FactorCategory.VOLATILITY} else 0)


def _direction(factor_id: str, category: FactorCategory) -> FactorDirection:
    if factor_id == "low_vol_composite": return FactorDirection.POSITIVE
    negative_tokens = ("vol", "drawdown", "var_", "cvar_", "kurt", "amihud", "zero_volume", "accruals", "debt_", "goodwill", "down_count")
    if any(token in factor_id for token in negative_tokens): return FactorDirection.NEGATIVE
    if category == FactorCategory.VALUATION and factor_id.startswith(("pe_", "pb_", "ps_", "pcf_", "ev_to_", "peg")):
        return FactorDirection.NEGATIVE
    if factor_id in {"aroon_down_25", "negative_news_ratio_7d", "suspension_days_20"}:
        return FactorDirection.NEGATIVE
    return FactorDirection.POSITIVE


def _description(factor_id: str, category: FactorCategory) -> str:
    if factor_id in _DESCRIPTIONS: return _DESCRIPTIONS[factor_id]
    if match := re.fullmatch(r"ret_(\d+)d", factor_id):
        return f"{match.group(1)}日简单收益 close / close.shift(N) - 1。"
    if match := re.fullmatch(r"distance_(\d+)d_(high|low)", factor_id):
        extreme = "rolling_max" if match.group(2) == "high" else "rolling_min"
        return f"close / {extreme}(close, {match.group(1)}) - 1。"
    return f"{_CATEGORY_NAMES[category]}因子 {factor_id}；固定口径见实现级规格 4.3，输出列为 {factor_id}。"


def _definition(factor_id: str, category: FactorCategory) -> FactorDefinition:
    catalog_category = category
    if factor_id in {"limit_up_count_20", "limit_down_count_20", "gap_event_20", "suspension_days_20"}:
        category = FactorCategory.EVENT
    elif factor_id in {"industry_momentum_rank_20", "market_momentum_rank_20"}:
        category = FactorCategory.CROSS_SECTION
    elif catalog_category == FactorCategory.CROSS_SECTION:
        category = FactorCategory.COMPOSITE
    params_schema, default_params = _parameter_metadata(factor_id)
    fundamental = category in {FactorCategory.VALUATION, FactorCategory.QUALITY, FactorCategory.GROWTH}
    point_in_time = fundamental or category == FactorCategory.SENTIMENT
    supported = (Market.CN,) if factor_id in {"limit_up_count_20", "limit_down_count_20"} else (Market.CN, Market.HK, Market.US)
    return FactorDefinition(
        factor_id=factor_id,
        version=1,
        name=_SPECIAL_NAMES.get(factor_id, f"{_CATEGORY_NAMES[category]}：{factor_id}"),
        display_name=factor_id.replace("_", " ").title(),
        description=_description(factor_id, category),
        category=category,
        catalog_group={
            FactorCategory.PRICE: FactorGroup.RETURN_PRICE,
            FactorCategory.TREND: FactorGroup.TREND,
            FactorCategory.MOMENTUM: FactorGroup.MOMENTUM,
            FactorCategory.VOLATILITY: FactorGroup.VOLATILITY_RISK,
            FactorCategory.LIQUIDITY: FactorGroup.LIQUIDITY,
            FactorCategory.VALUATION: FactorGroup.VALUATION,
            FactorCategory.QUALITY: FactorGroup.QUALITY,
            FactorCategory.GROWTH: FactorGroup.GROWTH,
            FactorCategory.SENTIMENT: FactorGroup.SENTIMENT_EVENT,
            FactorCategory.EVENT: FactorGroup.SENTIMENT_EVENT,
            FactorCategory.CROSS_SECTION: FactorGroup.CROSS_COMPOSITE,
            FactorCategory.COMPOSITE: FactorGroup.CROSS_COMPOSITE,
        }[category],
        required_columns=_columns(factor_id, category),
        dependencies=_DEPENDENCIES.get(factor_id, ()),
        params_schema=params_schema,
        default_params=default_params,
        min_history=_min_history(factor_id, category),
        formula_ref=f"{category.value}.{factor_id}",
        direction=_direction(factor_id, category),
        winsorize_default=WinsorizeMethod.MAD,
        normalize_default=NormalizeMethod.RANK if category in {FactorCategory.CROSS_SECTION, FactorCategory.COMPOSITE} else NormalizeMethod.ZSCORE,
        missing_policy=MissingValuePolicy.INDUSTRY_MEDIAN if fundamental else MissingValuePolicy.DROP,
        supported_markets=supported,
        point_in_time_required=point_in_time,
    )


def _build_catalog(groups: dict[FactorCategory, Iterable[str]]) -> tuple[FactorDefinition, ...]:
    return tuple(_definition(factor_id, category) for category, factor_ids in groups.items() for factor_id in factor_ids)


FACTOR_CATALOG = _build_catalog(_GROUP_IDS)
