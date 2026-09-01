from __future__ import annotations

from copy import deepcopy


def valid_definition(**updates):
    definition = {
        "universe": {
            "snapshot_id": "universe-cn-20250603",
            "minimum_listing_days": 60,
            "exclude_st": True,
            "exclude_delisting": True,
            "exclude_suspended": True,
        },
        "data": {
            "frequency": "daily",
            "adjustment": "qfq",
            "minimum_history": 1,
            "allowed_quality": ["ok", "valid"],
            "point_in_time": True,
        },
        "features": [
            {"factor_id": "ret_1d", "version": 1, "params": {}},
        ],
        "entry": {
            "condition": {
                "type": "compare",
                "left": {
                    "kind": "factor",
                    "factor_id": "ret_1d",
                    "version": 1,
                },
                "operator": "gt",
                "right": {"kind": "constant", "value": 0.01},
            },
            "ranking": {
                "factors": [
                    {
                        "factor": {
                            "kind": "factor",
                            "factor_id": "ret_1d",
                            "version": 1,
                        },
                        "weight": 1,
                        "higher_is_better": True,
                        "normalization": "zscore",
                    }
                ],
                "top_n": 1,
                "tie_breaker": "symbol_asc",
            },
        },
        "exit": {"stop_loss": 0.1, "max_holding_periods": 20},
        "rebalance": {"frequency": "daily"},
        "portfolio": {
            "weighting": "equal_weight",
            "max_positions": 2,
            "max_position_weight": 0.6,
            "max_industry_weight": 0.8,
            "min_cash_ratio": 0.1,
            "minimum_lot": 100,
            "minimum_notional": 1000,
        },
        "execution": {
            "signal_time": "close",
            "execution_time": "next_open",
            "price": "open",
            "slippage_bps": 5,
            "fee_model_version": "cn-a-v1",
        },
        "risk": {"max_drawdown_stop": 0.2, "cooldown_periods": 3},
        "benchmark": {"market": "CN", "symbol": "000300"},
    }
    definition.update(deepcopy(updates))
    return definition
