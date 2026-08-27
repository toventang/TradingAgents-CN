from typing import List, Dict, Any
from app.models.strategy import Strategy, StrategyVersion, StrategyStatus, StrategyType, UniverseSnapshot
from app.utils.timezone import now_tz

# 14 系统策略模板元数据与配置目录

SYSTEM_TEMPLATES_SPEC: List[Dict[str, Any]] = [
    {
        "strategy_id": "sys_tmpl_01_val_mom",
        "name": "Value & Momentum Dual Factor",
        "description": " Combines value (ret_120d valuation proxy) and momentum (ret_20d) for multi-factor stock selection.",
        "strategy_type": StrategyType.FACTOR_MODEL,
        "parameters": {"weights": {"ret_20d": 0.6, "ret_120d": 0.4}},
        "rules": {
            "conditions": {
                "op": "AND",
                "children": [
                    {"op": ">", "factor_id": "ret_20d", "value": 0.0},
                    {"op": ">", "factor_id": "ret_120d", "value": -0.2}
                ]
            },
            "top_k": 10
        },
        "benchmark": "000300.SH",
        "suitable_markets": ["CN", "US"],
        "unsuitable_markets": ["CRYPTO"],
        "cost_slippage_defaults": {"commission_rate": 0.0003, "slippage_rate": 0.001},
        "min_history_days": 120,
        "warnings": ["May underperform during sudden market style shifts."]
    },
    {
        "strategy_id": "sys_tmpl_02_short_momentum",
        "name": "Short-Term Trend Momentum",
        "description": "Captures 5-day price momentum with positive 1-day return confirmation.",
        "strategy_type": StrategyType.FACTOR_MODEL,
        "parameters": {"weights": {"ret_5d": 0.7, "ret_1d": 0.3}},
        "rules": {
            "conditions": {
                "op": "AND",
                "children": [
                    {"op": ">", "factor_id": "ret_1d", "value": 0.005},
                    {"op": ">", "factor_id": "ret_5d", "value": 0.02}
                ]
            },
            "top_k": 5
        },
        "benchmark": "000905.SH",
        "suitable_markets": ["CN"],
        "unsuitable_markets": [],
        "cost_slippage_defaults": {"commission_rate": 0.0003, "slippage_rate": 0.0015},
        "min_history_days": 20,
        "warnings": ["High turnover rate; sensitive to transaction costs."]
    },
    {
        "strategy_id": "sys_tmpl_03_medium_momentum",
        "name": "Medium-Term Trend Follower",
        "description": "Follows 60-day medium term trend with 20-day momentum filter.",
        "strategy_type": StrategyType.FACTOR_MODEL,
        "parameters": {"weights": {"ret_60d": 0.6, "ret_20d": 0.4}},
        "rules": {
            "conditions": {
                "op": ">", "factor_id": "ret_60d", "value": 0.05
            },
            "top_k": 15
        },
        "benchmark": "000300.SH",
        "suitable_markets": ["CN", "US", "HK"],
        "unsuitable_markets": [],
        "cost_slippage_defaults": {"commission_rate": 0.0003, "slippage_rate": 0.001},
        "min_history_days": 60,
        "warnings": ["Lags during V-shaped market reversals."]
    },
    {
        "strategy_id": "sys_tmpl_04_long_term_trend",
        "name": "Long-Term Trend Heavyweight",
        "description": "Selects stocks with strong 240-day long-term returns.",
        "strategy_type": StrategyType.FACTOR_MODEL,
        "parameters": {"weights": {"ret_240d": 0.8, "ret_120d": 0.2}},
        "rules": {
            "conditions": {
                "op": ">", "factor_id": "ret_240d", "value": 0.10
            },
            "top_k": 20
        },
        "benchmark": "000001.SH",
        "suitable_markets": ["CN", "US"],
        "unsuitable_markets": [],
        "cost_slippage_defaults": {"commission_rate": 0.0003, "slippage_rate": 0.0008},
        "min_history_days": 240,
        "warnings": ["Low trading frequency; requires long holding patience."]
    },
    {
        "strategy_id": "sys_tmpl_05_log_ret_momentum",
        "name": "Log-Return Normalized Momentum",
        "description": "Uses log-transformed returns for normalized cross-sectional momentum.",
        "strategy_type": StrategyType.FACTOR_MODEL,
        "parameters": {"weights": {"log_ret_20d": 0.7, "log_ret_5d": 0.3}},
        "rules": {
            "conditions": {
                "op": ">", "factor_id": "log_ret_20d", "value": 0.0
            },
            "top_k": 10
        },
        "benchmark": "000300.SH",
        "suitable_markets": ["CN", "US"],
        "unsuitable_markets": [],
        "cost_slippage_defaults": {"commission_rate": 0.0003, "slippage_rate": 0.001},
        "min_history_days": 30,
        "warnings": ["Log returns smooth compounding but may mask extreme volatility."]
    },
    {
        "strategy_id": "sys_tmpl_06_reversal_strategy",
        "name": "Short-Term Reversal Mean Reversion",
        "description": "Selects oversold stocks with low 5-day return and positive 1-day turnaround.",
        "strategy_type": StrategyType.FACTOR_MODEL,
        "parameters": {"weights": {"ret_5d": -0.8, "ret_1d": 0.2}},
        "rules": {
            "conditions": {
                "op": "AND",
                "children": [
                    {"op": "<", "factor_id": "ret_5d", "value": -0.05},
                    {"op": ">", "factor_id": "ret_1d", "value": 0.0}
                ]
            },
            "top_k": 5
        },
        "benchmark": "000905.SH",
        "suitable_markets": ["CN"],
        "unsuitable_markets": ["TRENDING_BULL"],
        "cost_slippage_defaults": {"commission_rate": 0.0003, "slippage_rate": 0.0015},
        "min_history_days": 20,
        "warnings": ["Risk of catching falling knives in strong downtrends."]
    },
    {
        "strategy_id": "sys_tmpl_07_multi_period_mom",
        "name": "Multi-Period Momentum Composite",
        "description": "Composites 5d, 20d, 60d, and 120d returns for comprehensive momentum scoring.",
        "strategy_type": StrategyType.FACTOR_MODEL,
        "parameters": {"weights": {"ret_5d": 0.1, "ret_20d": 0.3, "ret_60d": 0.4, "ret_120d": 0.2}},
        "rules": {
            "conditions": {
                "op": ">", "factor_id": "ret_60d", "value": 0.0
            },
            "top_percent": 0.1
        },
        "benchmark": "000300.SH",
        "suitable_markets": ["CN", "US"],
        "unsuitable_markets": [],
        "cost_slippage_defaults": {"commission_rate": 0.0003, "slippage_rate": 0.001},
        "min_history_days": 120,
        "warnings": ["Requires balanced market conditions across multiple horizons."]
    },
    {
        "strategy_id": "sys_tmpl_08_log_reversal",
        "name": "Log-Return Reversal Hunter",
        "description": "Seeks oversold recovery opportunities using 5-day log return reversal.",
        "strategy_type": StrategyType.FACTOR_MODEL,
        "parameters": {"weights": {"log_ret_5d": -1.0}},
        "rules": {
            "conditions": {
                "op": "<", "factor_id": "log_ret_5d", "value": -0.03
            },
            "top_k": 8
        },
        "benchmark": "000852.SH",
        "suitable_markets": ["CN"],
        "unsuitable_markets": [],
        "cost_slippage_defaults": {"commission_rate": 0.0003, "slippage_rate": 0.0012},
        "min_history_days": 15,
        "warnings": ["Higher volatility in small-cap universe."]
    },
    {
        "strategy_id": "sys_tmpl_09_breakout_mom",
        "name": "High Momentum Breakout",
        "description": "Filters for strong 10-day price momentum with positive 1-day surge.",
        "strategy_type": StrategyType.FACTOR_MODEL,
        "parameters": {"weights": {"ret_10d": 0.7, "ret_1d": 0.3}},
        "rules": {
            "conditions": {
                "op": "AND",
                "children": [
                    {"op": ">", "factor_id": "ret_10d", "value": 0.03},
                    {"op": ">", "factor_id": "ret_1d", "value": 0.01}
                ]
            },
            "top_k": 10
        },
        "benchmark": "000300.SH",
        "suitable_markets": ["CN", "US"],
        "unsuitable_markets": [],
        "cost_slippage_defaults": {"commission_rate": 0.0003, "slippage_rate": 0.001},
        "min_history_days": 30,
        "warnings": ["Watch out for false breakouts."]
    },
    {
        "strategy_id": "sys_tmpl_10_steady_growth",
        "name": "Steady Medium-Long Growth",
        "description": "Focuses on steady 120d return with 20d positive stability filter.",
        "strategy_type": StrategyType.FACTOR_MODEL,
        "parameters": {"weights": {"ret_120d": 0.7, "ret_20d": 0.3}},
        "rules": {
            "conditions": {
                "op": "between", "factor_id": "ret_20d", "value": [0.0, 0.20]
            },
            "top_k": 15
        },
        "benchmark": "000300.SH",
        "suitable_markets": ["CN", "US"],
        "unsuitable_markets": [],
        "cost_slippage_defaults": {"commission_rate": 0.0003, "slippage_rate": 0.0008},
        "min_history_days": 120,
        "warnings": ["Excludes hyper-growth speculative stocks."]
    },
    {
        "strategy_id": "sys_tmpl_11_ultra_short_surge",
        "name": "Ultra Short-Term Surge",
        "description": "Targets 1-day momentum surges for high-frequency daily tactical rotation.",
        "strategy_type": StrategyType.FACTOR_MODEL,
        "parameters": {"weights": {"ret_1d": 1.0}},
        "rules": {
            "conditions": {
                "op": ">", "factor_id": "ret_1d", "value": 0.02
            },
            "top_k": 3
        },
        "benchmark": "000905.SH",
        "suitable_markets": ["CN"],
        "unsuitable_markets": [],
        "cost_slippage_defaults": {"commission_rate": 0.0003, "slippage_rate": 0.002},
        "min_history_days": 10,
        "warnings": ["Very high turnover; subject to intraday noise."]
    },
    {
        "strategy_id": "sys_tmpl_12_broad_market_rank",
        "name": "Broad Market Relative Ranker",
        "description": "Ranks broad market stocks using normalized 20-day return z-scores.",
        "strategy_type": StrategyType.FACTOR_MODEL,
        "parameters": {"weights": {"ret_20d": 1.0}},
        "rules": {
            "conditions": {
                "op": "zscore_gte", "factor_id": "ret_20d", "value": 0.5
            },
            "top_percent": 0.05
        },
        "benchmark": "000001.SH",
        "suitable_markets": ["CN", "US", "HK"],
        "unsuitable_markets": [],
        "cost_slippage_defaults": {"commission_rate": 0.0003, "slippage_rate": 0.001},
        "min_history_days": 30,
        "warnings": ["Top percent cutoff expands in large universes."]
    },
    {
        "strategy_id": "sys_tmpl_13_balanced_horizon",
        "name": "Balanced Horizon Equal Weight",
        "description": "Equal weights 5d, 20d, and 120d return metrics for balanced risk allocation.",
        "strategy_type": StrategyType.FACTOR_MODEL,
        "parameters": {"weights": {"ret_5d": 0.33, "ret_20d": 0.33, "ret_120d": 0.34}},
        "rules": {
            "conditions": {
                "op": "AND",
                "children": [
                    {"op": ">", "factor_id": "ret_5d", "value": -0.02},
                    {"op": ">", "factor_id": "ret_20d", "value": 0.0}
                ]
            },
            "top_k": 12
        },
        "benchmark": "000300.SH",
        "suitable_markets": ["CN", "US"],
        "unsuitable_markets": [],
        "cost_slippage_defaults": {"commission_rate": 0.0003, "slippage_rate": 0.001},
        "min_history_days": 120,
        "warnings": ["Moderate risk profile; neutral style bias."]
    },
    {
        "strategy_id": "sys_tmpl_14_log_trend_follower",
        "name": "Log-Return Long-Term Trend Follower",
        "description": "Log-return based 20-day trend follower with robust outlier resistance.",
        "strategy_type": StrategyType.FACTOR_MODEL,
        "parameters": {"weights": {"log_ret_20d": 1.0}},
        "rules": {
            "conditions": {
                "op": ">", "factor_id": "log_ret_20d", "value": 0.02
            },
            "top_k": 10
        },
        "benchmark": "000300.SH",
        "suitable_markets": ["CN", "US"],
        "unsuitable_markets": [],
        "cost_slippage_defaults": {"commission_rate": 0.0003, "slippage_rate": 0.001},
        "min_history_days": 30,
        "warnings": ["Requires persistent trend continuation."]
    }
]


def get_all_system_templates() -> List[Dict[str, Any]]:
    """获取全部 14 个系统模板配置字典"""
    return SYSTEM_TEMPLATES_SPEC
