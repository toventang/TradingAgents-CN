"""Authoritative catalog for the fourteen version-one system templates.

Definitions are closed StrategyDefinitionDSL payloads.  Descriptive metadata is
kept beside (not inside) that DSL so validation and execution remain free of
unrecognized or non-executable fields.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from app.models.strategy import StrategyKind
from app.models.symbol import Market


@dataclass(frozen=True)
class ParameterRange:
    name: str
    default: float | int
    minimum: float | int
    maximum: float | int
    unit: str
    sensitivity: str


@dataclass(frozen=True)
class TemplateFixture:
    """Latest factor values for one deterministic fixture symbol."""

    name: str
    factor_values: Mapping[str, float]
    expected_buy: bool


@dataclass(frozen=True)
class SystemStrategyTemplate:
    template_id: str
    version: int
    name: str
    description: str
    formula: str
    kind: StrategyKind
    market: Market
    definition: Mapping[str, Any]
    parameter_ranges: tuple[ParameterRange, ...]
    suitable_markets: tuple[str, ...]
    unsuitable_scenarios: tuple[str, ...]
    risk_warning: str
    signal_fixture: TemplateFixture
    no_signal_fixture: TemplateFixture

    @property
    def strategy_id(self) -> str:
        return f"system-template:{self.template_id}"

    @property
    def strategy_version_id(self) -> str:
        return f"system-template:{self.template_id}:v{self.version}"

    @property
    def minimum_history(self) -> int:
        return int(self.definition["data"]["minimum_history"])

    @property
    def factor_ids(self) -> tuple[str, ...]:
        return tuple(item["factor_id"] for item in self.definition["features"])

    @property
    def benchmark(self) -> str:
        benchmark = self.definition["benchmark"]
        return f"{benchmark['market']}:{benchmark['symbol']}"

    @property
    def fee_model_version(self) -> str:
        return str(self.definition["execution"]["fee_model_version"])

    @property
    def slippage_bps(self) -> float:
        return float(self.definition["execution"]["slippage_bps"])

    def definition_copy(self) -> dict[str, Any]:
        return deepcopy(dict(self.definition))


def _factor(factor_id: str, *, lag: int = 0) -> dict[str, Any]:
    return {"kind": "factor", "factor_id": factor_id, "version": 1, "lag": lag}


def _constant(value: float) -> dict[str, Any]:
    return {"kind": "constant", "value": value}


def _compare(factor_id: str, operator: str, value: float, *, lag: int = 0) -> dict[str, Any]:
    return {
        "type": "compare",
        "left": _factor(factor_id, lag=lag),
        "operator": operator,
        "right": _constant(value),
    }


def _compare_factors(left_factor_id: str, operator: str, right_factor_id: str) -> dict[str, Any]:
    return {
        "type": "compare",
        "left": _factor(left_factor_id),
        "operator": operator,
        "right": _factor(right_factor_id),
    }


def _all(*children: dict[str, Any]) -> dict[str, Any]:
    return {"type": "all", "children": list(children)}


def _any(*children: dict[str, Any]) -> dict[str, Any]:
    return {"type": "any", "children": list(children)}


def _not(child: dict[str, Any]) -> dict[str, Any]:
    return {"type": "not", "child": child}


def _rank(factor_id: str, percentile: float, *, higher: bool = True) -> dict[str, Any]:
    return {
        "type": "rank",
        "factor": _factor(factor_id),
        "mode": "percentile",
        "percentile": percentile,
        "higher_is_better": higher,
    }


def _definition(
    *,
    factors: tuple[str, ...],
    entry: dict[str, Any],
    exit_condition: dict[str, Any],
    ranking: tuple[tuple[str, float, bool], ...],
    minimum_history: int,
    rebalance: str,
    stop_loss: float,
    max_holding_periods: int | None = None,
    weighting: str = "equal_weight",
) -> Mapping[str, Any]:
    rebalance_spec: dict[str, Any] = {"frequency": rebalance}
    if rebalance == "weekly":
        rebalance_spec["weekday"] = 0
    elif rebalance == "monthly":
        rebalance_spec["day_of_month"] = 2
    exit_spec: dict[str, Any] = {
        "condition": exit_condition,
        "stop_loss": stop_loss,
    }
    if max_holding_periods is not None:
        exit_spec["max_holding_periods"] = max_holding_periods
    payload = {
        "universe": {
            "minimum_listing_days": 120,
            "exclude_st": True,
            "exclude_delisting": True,
            "exclude_suspended": True,
            "minimum_market_cap": 1_000_000_000,
        },
        "data": {
            "frequency": "daily",
            "adjustment": "qfq",
            "minimum_history": minimum_history,
            "allowed_quality": ["ok", "valid"],
            "point_in_time": True,
        },
        "features": [
            {
                "factor_id": factor_id,
                "version": 1,
                "params": (
                    {
                        "weights": {
                            "value_composite": 0.2,
                            "quality_composite": 0.2,
                            "growth_composite": 0.2,
                            "momentum_composite": 0.2,
                            "low_vol_composite": 0.2,
                        }
                    }
                    if factor_id == "multi_factor_score"
                    else {}
                ),
            }
            for factor_id in factors
        ],
        "entry": {
            "condition": entry,
            "ranking": {
                "factors": [
                    {
                        "factor": _factor(factor_id),
                        "weight": weight,
                        "higher_is_better": higher,
                        "normalization": "rank",
                    }
                    for factor_id, weight, higher in ranking
                ],
                "top_percent": 0.20,
                "tie_breaker": "symbol_asc",
            },
        },
        "exit": exit_spec,
        "rebalance": rebalance_spec,
        "portfolio": {
            "weighting": weighting,
            "max_positions": 20,
            "max_position_weight": 0.08,
            "max_industry_weight": 0.25,
            "min_cash_ratio": 0.05,
            "minimum_lot": 100,
            "minimum_notional": 5_000,
        },
        "execution": {
            "signal_time": "close",
            "execution_time": "next_open",
            "price": "open",
            "slippage_bps": 5,
            "fee_model_version": "cn-a-v1",
        },
        "risk": {
            "max_drawdown_stop": 0.20,
            "cooldown_periods": 3,
        },
        "benchmark": {"market": "CN", "symbol": "000300"},
    }
    if weighting == "inverse_volatility":
        payload["portfolio"]["volatility_factor"] = _factor("hist_vol_20")
    return MappingProxyType(payload)


def _ranges(*items: tuple[str, float | int, float | int, float | int, str, str]) -> tuple[ParameterRange, ...]:
    return tuple(ParameterRange(*item) for item in items)


def _fixture(name: str, expected_buy: bool, **values: float) -> TemplateFixture:
    return TemplateFixture(name, MappingProxyType(values), expected_buy)


_WARNING = "历史信号不代表未来收益；数据缺失、停牌、涨跌停和交易成本可能使信号无法成交，使用前必须独立评估风险。"


def _template(
    template_id: str,
    name: str,
    description: str,
    formula: str,
    definition: Mapping[str, Any],
    parameter_ranges: tuple[ParameterRange, ...],
    suitable: tuple[str, ...],
    unsuitable: tuple[str, ...],
    signal_values: dict[str, float],
    no_signal_values: dict[str, float],
    *,
    kind: StrategyKind = StrategyKind.PORTFOLIO,
) -> SystemStrategyTemplate:
    return SystemStrategyTemplate(
        template_id=template_id,
        version=1,
        name=name,
        description=description,
        formula=formula,
        kind=kind,
        market=Market.CN,
        definition=definition,
        parameter_ranges=parameter_ranges,
        suitable_markets=suitable,
        unsuitable_scenarios=unsuitable,
        risk_warning=_WARNING,
        signal_fixture=_fixture(f"{template_id}-signal", True, **signal_values),
        no_signal_fixture=_fixture(f"{template_id}-none", False, **no_signal_values),
    )


SYSTEM_STRATEGY_TEMPLATES = (
    _template(
        "value_quality", "价值质量", "选择估值与质量复合分高且经营现金流为正的股票。",
        "entry = value_composite > 0 AND quality_composite > 0 AND operating_cashflow_ratio > 0; score = 0.5*rank(value)+0.4*rank(quality)+0.1*rank(cashflow)",
        _definition(factors=("value_composite", "quality_composite", "operating_cashflow_ratio"), entry=_all(_compare("value_composite", "gt", 0), _compare("quality_composite", "gt", 0), _compare("operating_cashflow_ratio", "gt", 0)), exit_condition=_any(_not(_rank("value_composite", .40)), _compare("quality_composite", "lt", -.20), _compare("operating_cashflow_ratio", "lte", 0)), ranking=(("value_composite", .5, True), ("quality_composite", .4, True), ("operating_cashflow_ratio", .1, True)), minimum_history=1, rebalance="monthly", stop_loss=.15),
        _ranges(("entry composite floor", 0, -.5, .5, "z-score", "阈值升高会减少持仓并提高风格集中度"), ("exit percentile", .40, .25, .60, "fraction", "退出越快换手和成本越高")),
        ("A股大中盘、财报披露稳定的成熟行业",), ("亏损早期成长公司", "会计质量快速变化或财报数据陈旧时"),
        {"value_composite": 1.2, "quality_composite": 1.0, "operating_cashflow_ratio": .8}, {"value_composite": -.3, "quality_composite": .2, "operating_cashflow_ratio": .4}),
    _template(
        "growth_quality", "成长质量", "选择成长与质量兼备且估值收益率不过度为负的股票。",
        "entry = growth_composite > 0.2 AND quality_composite > 0 AND earnings_yield > -0.05; score = 0.5*growth+0.4*quality+0.1*earnings_yield",
        _definition(factors=("growth_composite", "quality_composite", "earnings_yield"), entry=_all(_compare("growth_composite", "gt", .2), _compare("quality_composite", "gt", 0), _compare("earnings_yield", "gt", -.05)), exit_condition=_any(_compare("growth_composite", "lt", 0), _not(_rank("quality_composite", .40))), ranking=(("growth_composite", .5, True), ("quality_composite", .4, True), ("earnings_yield", .1, True)), minimum_history=5, rebalance="monthly", stop_loss=.18),
        _ranges(("growth floor", .2, 0, .8, "z-score", "高阈值偏向高增长并放大估值风险"), ("earnings-yield floor", -.05, -.15, .05, "ratio", "更高下限排除高估值股票")),
        ("盈利增长可验证、披露质量高的市场",), ("主题炒作期", "增长基数效应显著时"),
        {"growth_composite": 1.1, "quality_composite": .8, "earnings_yield": .04}, {"growth_composite": -.1, "quality_composite": .8, "earnings_yield": .04}),
    _template(
        "momentum_20_60", "20/60日动量", "同时要求中短期动量与流动性确认。",
        "entry = ret_20d > 0.05 AND ret_60d > 0.10 AND volume_ratio_20 > 0.8; exit = ma_cross_20_60 < 0",
        _definition(factors=("ret_20d", "ret_60d", "volume_ratio_20", "ma_cross_20_60"), entry=_all(_compare("ret_20d", "gt", .05), _compare("ret_60d", "gt", .10), _compare("volume_ratio_20", "gt", .8)), exit_condition=_compare("ma_cross_20_60", "lt", 0), ranking=(("ret_20d", .45, True), ("ret_60d", .45, True), ("volume_ratio_20", .1, True)), minimum_history=61, rebalance="weekly", stop_loss=.10),
        _ranges(("20-day return", .05, 0, .15, "return", "阈值越高越易追涨"), ("60-day return", .10, .03, .30, "return", "长周期门槛控制趋势强度"), ("stop loss", .10, .06, .15, "loss ratio", "收紧会增加震荡止损")),
        ("趋势清晰且流动性充足的市场",), ("横盘震荡", "急速反转或涨跌停密集期"),
        {"ret_20d": .12, "ret_60d": .25, "volume_ratio_20": 1.4, "ma_cross_20_60": .1}, {"ret_20d": -.02, "ret_60d": .25, "volume_ratio_20": 1.4, "ma_cross_20_60": .1}),
    _template(
        "low_volatility", "低波动", "选择低历史波动、低 beta 与低回撤股票，并按逆波动配置。",
        "entry = hist_vol_20 < 0.25 AND beta_60 < 0.9 AND max_drawdown_60 > -0.20; score favors lower risk",
        _definition(factors=("hist_vol_20", "beta_60", "max_drawdown_60"), entry=_all(_compare("hist_vol_20", "lt", .25), _compare("beta_60", "lt", .9), _compare("max_drawdown_60", "gt", -.20)), exit_condition=_not(_rank("hist_vol_20", .40, higher=False)), ranking=(("hist_vol_20", .5, False), ("beta_60", .3, False), ("max_drawdown_60", .2, True)), minimum_history=61, rebalance="monthly", stop_loss=.12, weighting="inverse_volatility"),
        _ranges(("annual volatility cap", .25, .15, .40, "ratio", "低上限降低样本数"), ("beta cap", .9, .6, 1.1, "beta", "低上限增强防御属性")),
        ("风险偏好下降、成熟行业占比较高的市场",), ("强劲单边牛市", "波动率结构突然跃迁时"),
        {"hist_vol_20": .16, "beta_60": .65, "max_drawdown_60": -.08}, {"hist_vol_20": .35, "beta_60": .65, "max_drawdown_60": -.08}),
    _template(
        "high_dividend_quality", "高股息质量", "选择高股息且盈利、现金流稳定的股票。",
        "entry = dividend_yield_ttm > 0.03 AND positive_profit_quarters_8q >= 7 AND positive_cfo_quarters_8q >= 6",
        _definition(factors=("dividend_yield_ttm", "positive_profit_quarters_8q", "positive_cfo_quarters_8q"), entry=_all(_compare("dividend_yield_ttm", "gt", .03), _compare("positive_profit_quarters_8q", "gte", 7), _compare("positive_cfo_quarters_8q", "gte", 6)), exit_condition=_any(_compare("dividend_yield_ttm", "lt", .02), _compare("positive_cfo_quarters_8q", "lt", 5)), ranking=(("dividend_yield_ttm", .5, True), ("positive_profit_quarters_8q", .25, True), ("positive_cfo_quarters_8q", .25, True)), minimum_history=8, rebalance="monthly", stop_loss=.15),
        _ranges(("dividend yield", .03, .02, .06, "ratio", "过高阈值可能捕获价值陷阱"), ("positive CFO quarters", 6, 5, 8, "quarters", "更高下限偏向成熟企业")),
        ("分红制度稳定的成熟行业",), ("周期盈利峰值", "一次性高分红或高杠杆派息公司"),
        {"dividend_yield_ttm": .05, "positive_profit_quarters_8q": 8, "positive_cfo_quarters_8q": 8}, {"dividend_yield_ttm": .01, "positive_profit_quarters_8q": 8, "positive_cfo_quarters_8q": 8}),
    _template(
        "mean_reversion_rsi", "RSI均值回归", "在长期趋势未破坏时捕捉 RSI 超卖后的均值回归。",
        "entry = RSI14 < 30 AND price/MA250 > 0.95; exit = RSI14 > 55 OR price/MA250 < 0.90",
        _definition(factors=("rsi_14", "ma_ratio_250"), entry=_all(_compare("rsi_14", "lt", 30), _compare("ma_ratio_250", "gt", .95)), exit_condition=_any(_compare("rsi_14", "gt", 55), _compare("ma_ratio_250", "lt", .90)), ranking=(("rsi_14", .7, False), ("ma_ratio_250", .3, True)), minimum_history=250, rebalance="daily", stop_loss=.08, max_holding_periods=10),
        _ranges(("RSI oversold", 30, 20, 35, "index", "高阈值增加交易和假反转"), ("RSI exit", 55, 45, 65, "index", "高目标延长持有"), ("max holding", 10, 5, 20, "trading days", "期限越短越依赖反弹速度")),
        ("长期趋势稳定的震荡市场",), ("持续下跌趋势", "流动性枯竭或重大负面事件期间"),
        {"rsi_14": 22, "ma_ratio_250": 1.02}, {"rsi_14": 48, "ma_ratio_250": 1.02}, kind=StrategyKind.SCREENING),
    _template(
        "trend_following", "趋势跟随", "要求短中长期均线结构与 ADX 同时确认。",
        "entry = ma_ratio_20 > ma_ratio_60 > ma_ratio_250 proxy levels AND adx_14 > 25; exit = ma_cross_20_60 < 0 OR ma_cross_60_250 < 0",
        _definition(factors=("ma_ratio_20", "ma_ratio_60", "ma_ratio_250", "adx_14", "ma_cross_20_60", "ma_cross_60_250", "atr_pct_14"), entry=_all(_compare_factors("ma_ratio_20", "gt", "ma_ratio_60"), _compare_factors("ma_ratio_60", "gt", "ma_ratio_250"), _compare("ma_ratio_250", "gt", 1.0), _compare("adx_14", "gt", 25)), exit_condition=_any(_compare("ma_cross_20_60", "lt", 0), _compare("ma_cross_60_250", "lt", 0), _compare("atr_pct_14", "gt", .08)), ranking=(("adx_14", .5, True), ("ma_ratio_20", .3, True), ("ma_ratio_60", .2, True)), minimum_history=250, rebalance="daily", stop_loss=.10),
        _ranges(("ADX confirmation", 25, 18, 35, "index", "高阈值减少弱趋势"), ("ATR risk ceiling", .08, .04, .12, "price ratio", "低上限可能过早退出高波趋势")),
        ("方向持续、成交正常的趋势市场",), ("窄幅震荡", "隔夜跳空和趋势快速反转期"),
        {"ma_ratio_20": 1.12, "ma_ratio_60": 1.08, "ma_ratio_250": 1.03, "adx_14": 32, "ma_cross_20_60": .1, "ma_cross_60_250": .1, "atr_pct_14": .03}, {"ma_ratio_20": .98, "ma_ratio_60": 1.08, "ma_ratio_250": 1.03, "adx_14": 32, "ma_cross_20_60": .1, "ma_cross_60_250": .1, "atr_pct_14": .03}),
    _template(
        "breakout_60", "60日放量突破", "选择接近或突破 60 日高点且成交量扩张的股票。",
        "entry = distance_60d_high >= -0.005 AND volume_ratio_20 > 1.5; exit = distance_60d_high < -0.08 OR atr_pct_14 > 0.08",
        _definition(factors=("distance_60d_high", "volume_ratio_20", "atr_pct_14"), entry=_all(_compare("distance_60d_high", "gte", -.005), _compare("volume_ratio_20", "gt", 1.5)), exit_condition=_any(_compare("distance_60d_high", "lt", -.08), _compare("atr_pct_14", "gt", .08)), ranking=(("distance_60d_high", .6, True), ("volume_ratio_20", .4, True)), minimum_history=61, rebalance="daily", stop_loss=.08),
        _ranges(("breakout tolerance", -.005, -.02, .01, "return", "放宽会引入未真正突破的标的"), ("volume ratio", 1.5, 1.2, 2.5, "multiple", "高门槛降低频率")),
        ("有持续增量资金的趋势市场",), ("假突破频繁的震荡市", "一字涨停或无法按次日开盘成交时"),
        {"distance_60d_high": .01, "volume_ratio_20": 2.0, "atr_pct_14": .03}, {"distance_60d_high": -.05, "volume_ratio_20": 2.0, "atr_pct_14": .03}),
    _template(
        "volume_price_confirmation", "量价确认", "要求价格动量与成交量、量价相关性同向。",
        "entry = ret_20d > 0.05 AND volume_ratio_20 > 1.1 AND price_volume_corr_20 > 0.2; exit = price_volume_corr_20 < 0",
        _definition(factors=("ret_20d", "volume_ratio_20", "price_volume_corr_20"), entry=_all(_compare("ret_20d", "gt", .05), _compare("volume_ratio_20", "gt", 1.1), _compare("price_volume_corr_20", "gt", .2)), exit_condition=_compare("price_volume_corr_20", "lt", 0), ranking=(("ret_20d", .5, True), ("volume_ratio_20", .25, True), ("price_volume_corr_20", .25, True)), minimum_history=21, rebalance="weekly", stop_loss=.10),
        _ranges(("price momentum", .05, .02, .15, "return", "门槛越高越偏追涨"), ("price-volume correlation", .2, 0, .5, "correlation", "高门槛减少背离但降低覆盖")),
        ("成交活跃、量能有信息含量的市场",), ("成交受限或大宗交易主导期", "高频操纵量能的小盘股"),
        {"ret_20d": .12, "volume_ratio_20": 1.8, "price_volume_corr_20": .6}, {"ret_20d": .12, "volume_ratio_20": .8, "price_volume_corr_20": .6}),
    _template(
        "sentiment_reversal", "情绪反转", "在质量和流动性合格时选择极端负面情绪标的。",
        "entry = news_sentiment_7d < -0.6 AND quality_composite > 0 AND liquidity_composite > 0; exit = news_sentiment_7d > -0.1 OR negative_news_ratio_7d > 0.8",
        _definition(factors=("news_sentiment_7d", "quality_composite", "liquidity_composite", "negative_news_ratio_7d"), entry=_all(_compare("news_sentiment_7d", "lt", -.6), _compare("quality_composite", "gt", 0), _compare("liquidity_composite", "gt", 0)), exit_condition=_any(_compare("news_sentiment_7d", "gt", -.1), _compare("negative_news_ratio_7d", "gt", .8)), ranking=(("news_sentiment_7d", .6, False), ("quality_composite", .25, True), ("liquidity_composite", .15, True)), minimum_history=30, rebalance="daily", stop_loss=.08, max_holding_periods=10),
        _ranges(("negative sentiment", -.6, -.85, -.35, "score", "极端门槛降低频率并加大事件集中度"), ("max holding", 10, 3, 15, "trading days", "长持有增加基本面恶化暴露")),
        ("新闻覆盖充分且流动性正常的市场",), ("欺诈、退市、监管调查等结构性事件", "新闻源延迟或样本稀疏时"),
        {"news_sentiment_7d": -.8, "quality_composite": .7, "liquidity_composite": .6, "negative_news_ratio_7d": .5}, {"news_sentiment_7d": -.2, "quality_composite": .7, "liquidity_composite": .6, "negative_news_ratio_7d": .5}),
    _template(
        "sentiment_momentum", "情绪动量", "要求正面新闻情绪、热度与价格动量共同确认。",
        "entry = news_sentiment_7d > 0.4 AND news_volume_zscore_7d > 1 AND ret_5d > 0; exit = news_sentiment_7d < 0 OR news_volume_zscore_7d < 0",
        _definition(factors=("news_sentiment_7d", "news_volume_zscore_7d", "ret_5d"), entry=_all(_compare("news_sentiment_7d", "gt", .4), _compare("news_volume_zscore_7d", "gt", 1), _compare("ret_5d", "gt", 0)), exit_condition=_any(_compare("news_sentiment_7d", "lt", 0), _compare("news_volume_zscore_7d", "lt", 0)), ranking=(("news_sentiment_7d", .45, True), ("news_volume_zscore_7d", .35, True), ("ret_5d", .2, True)), minimum_history=60, rebalance="daily", stop_loss=.10, max_holding_periods=15),
        _ranges(("positive sentiment", .4, .2, .7, "score", "高门槛偏向拥挤事件"), ("attention z-score", 1, .5, 2.5, "z-score", "高门槛降低信号数量")),
        ("信息传播快且新闻覆盖稳定的市场",), ("消息操纵、谣言或公告前泄漏风险高时", "低流动性股票"),
        {"news_sentiment_7d": .8, "news_volume_zscore_7d": 2, "ret_5d": .06}, {"news_sentiment_7d": -.1, "news_volume_zscore_7d": 2, "ret_5d": .06}),
    _template(
        "multi_factor_balanced", "多因子均衡", "均衡组合价值、质量、成长、动量和低波因子。",
        "score = 0.2*(value + quality + growth + momentum + low_vol); entry = all five composites > -0.5",
        _definition(factors=("value_composite", "quality_composite", "growth_composite", "momentum_composite", "low_vol_composite", "multi_factor_score"), entry=_all(*(_compare(factor_id, "gt", -.5) for factor_id in ("value_composite", "quality_composite", "growth_composite", "momentum_composite", "low_vol_composite"))), exit_condition=_not(_rank("multi_factor_score", .40)), ranking=(("value_composite", .2, True), ("quality_composite", .2, True), ("growth_composite", .2, True), ("momentum_composite", .2, True), ("low_vol_composite", .2, True)), minimum_history=121, rebalance="monthly", stop_loss=.15),
        _ranges(("factor weight", .2, .1, .4, "portfolio share", "偏离等权会提高单一风格周期风险"), ("eligibility floor", -.5, -1, 0, "z-score", "高下限减少分散度")),
        ("行业与风格覆盖充分的宽基股票池",), ("单一主题或极小股票池", "因子高度相关或大面积缺失时"),
        {"value_composite": .7, "quality_composite": .8, "growth_composite": .6, "momentum_composite": .9, "low_vol_composite": .5, "multi_factor_score": .7}, {"value_composite": -1.0, "quality_composite": .8, "growth_composite": .6, "momentum_composite": .9, "low_vol_composite": .5, "multi_factor_score": .2}),
    _template(
        "industry_rotation", "行业轮动", "先选择行业动量靠前的股票，再以质量和个股动量排序。",
        "entry = industry_momentum_rank_20 >= 0.8 AND quality_composite > 0 AND momentum_composite > 0; exit = industry rank < 0.5",
        _definition(factors=("industry_momentum_rank_20", "quality_composite", "momentum_composite"), entry=_all(_compare("industry_momentum_rank_20", "gte", .8), _compare("quality_composite", "gt", 0), _compare("momentum_composite", "gt", 0)), exit_condition=_compare("industry_momentum_rank_20", "lt", .5), ranking=(("industry_momentum_rank_20", .5, True), ("quality_composite", .25, True), ("momentum_composite", .25, True)), minimum_history=121, rebalance="monthly", stop_loss=.15),
        _ranges(("industry rank floor", .8, .65, .9, "percentile score", "高门槛提高行业集中度"), ("industry exit floor", .5, .35, .65, "percentile score", "高退出线提高换手")),
        ("行业分类稳定、板块轮动明显的市场",), ("行业分类变更期", "宏观冲击导致全行业同步下跌时"),
        {"industry_momentum_rank_20": .95, "quality_composite": .7, "momentum_composite": .8}, {"industry_momentum_rank_20": .4, "quality_composite": .7, "momentum_composite": .8}),
    _template(
        "defensive_risk_off", "防御型风险规避", "选择低 beta、盈利稳定且低杠杆股票。",
        "entry = beta_60 < 0.75 AND profit_stability_8q > 0.6 AND debt_to_assets < 0.45; exit = beta_60 > 1 OR stability < 0.3",
        _definition(factors=("beta_60", "profit_stability_8q", "debt_to_assets", "hist_vol_20"), entry=_all(_compare("beta_60", "lt", .75), _compare("profit_stability_8q", "gt", .6), _compare("debt_to_assets", "lt", .45)), exit_condition=_any(_compare("beta_60", "gt", 1), _compare("profit_stability_8q", "lt", .3), _compare("debt_to_assets", "gt", .6)), ranking=(("beta_60", .4, False), ("profit_stability_8q", .35, True), ("debt_to_assets", .25, False)), minimum_history=61, rebalance="monthly", stop_loss=.12, weighting="inverse_volatility"),
        _ranges(("beta cap", .75, .5, .95, "beta", "低上限更防御但行业集中"), ("debt ratio cap", .45, .3, .6, "ratio", "严格杠杆限制可能排除资本密集行业")),
        ("宏观风险上升、风险偏好下降阶段",), ("流动性牛市", "防御行业出现政策或信用冲击时"),
        {"beta_60": .5, "profit_stability_8q": .85, "debt_to_assets": .25, "hist_vol_20": .15}, {"beta_60": 1.2, "profit_stability_8q": .85, "debt_to_assets": .25, "hist_vol_20": .3}),
)


SYSTEM_TEMPLATE_IDS = tuple(template.template_id for template in SYSTEM_STRATEGY_TEMPLATES)
_BY_ID = MappingProxyType({template.template_id: template for template in SYSTEM_STRATEGY_TEMPLATES})


def get_system_template(template_id: str) -> SystemStrategyTemplate:
    try:
        return _BY_ID[template_id]
    except KeyError as exc:
        raise KeyError(f"unknown system strategy template: {template_id}") from exc


if len(SYSTEM_STRATEGY_TEMPLATES) != 14 or len(set(SYSTEM_TEMPLATE_IDS)) != 14:
    raise RuntimeError("the system strategy catalog must contain exactly 14 unique templates")
