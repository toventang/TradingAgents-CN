from collections import Counter

import pytest

from app.models.factor import FactorCategory, FactorDefinition, FactorStatus
from app.services.factors.definitions.catalog import (
    CATALOG_GROUP_COUNTS,
    FACTOR_CATALOG,
    V1_EXCLUDED_OVERFLOW_IDS,
)


EXPECTED_IDS = set("""
ret_1d ret_3d ret_5d ret_10d ret_20d ret_60d ret_120d ret_250d log_ret_1d gap_open_1d
intraday_ret intraday_range close_location_value distance_20d_high distance_60d_high distance_250d_high
distance_20d_low distance_60d_low
ma_ratio_5 ma_ratio_10 ma_ratio_20 ma_ratio_60 ma_ratio_120 ma_ratio_250 ema_ratio_5 ema_ratio_10
ema_ratio_20 ema_ratio_60 ma_cross_5_20 ma_cross_10_60 ma_cross_20_60 ma_cross_60_250 macd_dif
macd_dea macd_hist adx_14 aroon_up_25 aroon_down_25 linear_slope_20 linear_slope_60 trend_r2_60
rsi_6 rsi_12 rsi_14 rsi_24 roc_5 roc_10 roc_20 roc_60 kdj_k kdj_d kdj_j cci_14 williams_r_14
momentum_10 ppo_12_26 trix_15 ultimate_osc_7_14_28 dpo_20
hist_vol_5 hist_vol_10 hist_vol_20 hist_vol_60 hist_vol_120 atr_14 atr_pct_14 downside_vol_20
downside_vol_60 max_drawdown_20 max_drawdown_60 max_drawdown_250 beta_60 beta_250 alpha_60 idio_vol_60
var_95_20 cvar_95_60 return_skew_60 return_kurt_60
volume_ratio_5 volume_ratio_20 volume_ratio_60 amount_ratio_5 amount_ratio_20 turnover_rate turnover_mean_20
turnover_std_20 obv obv_change_20 mfi_14 cmf_20 adl_change_20 vwap_deviation_20 price_volume_corr_20
price_volume_corr_60 volume_volatility_20 amihud_illiq_20 zero_volume_days_20
pe_ttm pb_mrq ps_ttm pcf_ttm earnings_yield book_to_price sales_to_price cashflow_to_price dividend_yield_ttm
ev_to_ebitda ev_to_ebit ev_to_sales peg market_cap_log free_float_cap_log
roe_ttm roa_ttm roic_ttm gross_margin_ttm operating_margin_ttm net_margin_ttm fcf_margin_ttm
cfo_to_net_income accruals_ratio asset_turnover_ttm inventory_turnover_ttm receivable_turnover_ttm
current_ratio quick_ratio cash_ratio debt_to_assets debt_to_equity interest_coverage operating_cashflow_ratio
goodwill_to_assets
revenue_yoy net_profit_yoy eps_yoy cfo_yoy revenue_cagr_3y net_profit_cagr_3y eps_cagr_3y
roe_change_yoy gross_margin_change_yoy revenue_stability_8q profit_stability_8q positive_profit_quarters_8q
positive_cfo_quarters_8q consecutive_revenue_growth_q consecutive_profit_growth_q sustainable_growth_rate
news_sentiment_1d news_sentiment_7d news_sentiment_30d news_volume_zscore_7d negative_news_ratio_7d
social_sentiment_1d social_sentiment_7d social_volume_zscore_7d limit_up_count_20 limit_down_count_20
gap_event_20 suspension_days_20
industry_momentum_rank_20 market_momentum_rank_20 value_composite quality_composite growth_composite
momentum_composite low_vol_composite liquidity_composite sentiment_composite multi_factor_score
""".split())


def test_exact_v1_catalog_ids_and_counts():
    assert len(FACTOR_CATALOG) == 171
    assert {item.factor_id for item in FACTOR_CATALOG} == EXPECTED_IDS
    assert len(EXPECTED_IDS) == 171
    assert V1_EXCLUDED_OVERFLOW_IDS == ("retained_earnings_to_assets",)

    actual = Counter(item.catalog_group for item in FACTOR_CATALOG)
    assert actual == Counter(CATALOG_GROUP_COUNTS)
    assert sum(CATALOG_GROUP_COUNTS.values()) == 171


def test_every_definition_has_complete_versioned_metadata():
    for definition in FACTOR_CATALOG:
        assert isinstance(definition, FactorDefinition)
        assert definition.version == 1
        assert definition.status == FactorStatus.ACTIVE
        assert definition.name and definition.display_name and definition.description
        assert definition.formula_ref and definition.formula_ref.count(".") == 1
        assert definition.output_column == definition.factor_id
        assert definition.min_history >= 1
        assert definition.supported_markets
        assert len(definition.checksum or "") == 64
        assert definition.checksum == definition.content_checksum()


def test_point_in_time_and_market_specific_metadata():
    by_id = {item.factor_id: item for item in FACTOR_CATALOG}
    assert by_id["roe_ttm"].point_in_time_required is True
    assert by_id["news_sentiment_7d"].point_in_time_required is True
    assert by_id["ret_20d"].point_in_time_required is False
    assert [market.value for market in by_id["limit_up_count_20"].supported_markets] == ["CN"]
    assert by_id["value_composite"].dependencies == (
        "earnings_yield", "book_to_price", "sales_to_price"
    )
    assert by_id["multi_factor_score"].default_params == {}
    with pytest.raises(ValueError, match="required parameters missing"):
        by_id["multi_factor_score"].resolve_params()
    assert by_id["multi_factor_score"].resolve_params({"weights": {"ret_20d": 1.0}})
    assert by_id["industry_momentum_rank_20"].category == FactorCategory.CROSS_SECTION
    assert by_id["multi_factor_score"].category == FactorCategory.COMPOSITE
    assert by_id["gap_event_20"].category == FactorCategory.EVENT
