from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.models.factor import (
    FactorSnapshot,
    FactorSnapshotStatus,
    FactorValueRow,
)
from app.models.strategy import (
    StrategyEntrySpec,
    StrategyKind,
    StrategyVersion,
    UniverseMember,
    UniverseSnapshot,
)
from app.models.symbol import Market
from app.services.strategies.condition_tree import (
    ConditionContext,
    condition_tree_stats,
    evaluate_condition,
)
from app.services.strategies.signal_engine import (
    DeterministicSignalEngine,
    PositionState,
    SignalInputError,
)
from tests.unit.strategies.dsl_fixtures import valid_definition


TRADE_DATE = date(2025, 6, 3)
VISIBLE_AT = datetime(2025, 6, 3, 8, tzinfo=timezone.utc)


def universe() -> UniverseSnapshot:
    return UniverseSnapshot(
        universe_snapshot_id="universe-cn-20250603",
        user_id="alice",
        market=Market.CN,
        trade_date=TRADE_DATE,
        as_of=datetime(2025, 6, 3, 7, tzinfo=timezone.utc),
        members=tuple(
            UniverseMember(market=Market.CN, symbol=symbol)
            for symbol in ("000001", "000002", "000003")
        ),
        source_versions={"security_master": "2025-06-03"},
        selection_definition={"market": "CN", "point_in_time": True},
        created_at=datetime(2025, 6, 3, 7, tzinfo=timezone.utc),
    )


def snapshot(*, published_at=None, as_of=None) -> FactorSnapshot:
    visible = as_of or datetime(2025, 6, 3, 7, tzinfo=timezone.utc)
    return FactorSnapshot(
        snapshot_id="a" * 64,
        user_id="alice",
        job_id="factor-job-1",
        task_id="factor-task-1",
        market=Market.CN,
        trade_date=TRADE_DATE,
        as_of=visible,
        universe_snapshot_id="universe-cn-20250603",
        factor_set_checksum="b" * 64,
        request_checksum="c" * 64,
        status=FactorSnapshotStatus.READY,
        expected_row_count=3,
        expected_factor_count=1,
        row_count=3,
        factor_count=1,
        source_versions={"daily": "2025-06-03"},
        values_checksum="d" * 64,
        created_at=visible,
        updated_at=visible,
        published_at=published_at or datetime(2025, 6, 3, 7, 30, tzinfo=timezone.utc),
    )


def rows(*, quality_overrides=None, values=None):
    quality_overrides = quality_overrides or {}
    values = values or {
        "000001": 0.05,
        "000002": 0.05,
        "000003": -0.01,
    }
    return tuple(
        FactorValueRow(
            snapshot_id="a" * 64,
            market=Market.CN,
            symbol=symbol,
            trade_date=TRADE_DATE,
            values={"ret_1d": value},
            quality={"ret_1d": quality_overrides.get(symbol, "ok")},
        )
        for symbol, value in values.items()
    )


def metadata():
    return {
        symbol: {
            "listing_days": 500,
            "is_st": False,
            "is_delisting": False,
            "is_suspended": False,
            "industry": "bank",
            "market_cap": 100_000_000,
        }
        for symbol in ("000001", "000002", "000003")
    }


def version(definition=None) -> StrategyVersion:
    return StrategyVersion(
        strategy_version_id="strategy-version-1",
        strategy_id="strategy-1",
        user_id="alice",
        version=1,
        market=Market.CN,
        definition=definition or valid_definition(),
        created_by="alice",
        created_at=VISIBLE_AT,
        change_summary="signal preview",
    )


def by_symbol(result):
    return {item.symbol: item for item in result.signals}


def test_deterministic_ranking_tie_breaking_reasons_and_contributions():
    engine = DeterministicSignalEngine()
    first = engine.evaluate(
        version=version(),
        universe=universe(),
        factor_snapshots=(snapshot(),),
        factor_rows=rows(),
        as_of=VISIBLE_AT,
        metadata_by_symbol=metadata(),
    )
    second = engine.evaluate(
        version=version(),
        universe=universe(),
        factor_snapshots=(snapshot(),),
        factor_rows=rows(),
        as_of=VISIBLE_AT,
        metadata_by_symbol=metadata(),
    )
    assert first == second

    signals = by_symbol(first)
    assert signals["000001"].signal_type == "buy"
    assert signals["000001"].rank == 1
    assert signals["000001"].reason_codes == ("ENTRY_SELECTED",)
    assert "ret_1d" in signals["000001"].input_contributions
    assert signals["000002"].signal_type == "hold"
    assert signals["000002"].rank == 2
    assert signals["000002"].reason_codes == ("RANK_CUTOFF",)
    assert signals["000003"].signal_type == "hold"
    assert signals["000003"].reason_codes == ("ENTRY_CONDITION_FAILED",)
    assert len({item.signal_id for item in first.signals}) == 3


def test_bad_quality_cannot_buy_and_positions_execute_exit_rules():
    engine = DeterministicSignalEngine()
    result = engine.evaluate(
        version=version(),
        universe=universe(),
        factor_snapshots=(snapshot(),),
        factor_rows=rows(quality_overrides={"000001": "stale"}),
        as_of=VISIBLE_AT,
        metadata_by_symbol=metadata(),
        positions={
            "000003": PositionState(
                symbol="000003", return_since_entry=-0.12, holding_periods=5
            )
        },
    )
    signals = by_symbol(result)
    assert signals["000001"].signal_type == "hold"
    assert signals["000001"].reason_codes == ("MISSING_FACTOR",)
    assert signals["000002"].signal_type == "buy"
    assert signals["000003"].signal_type == "sell"
    assert "STOP_LOSS" in signals["000003"].reason_codes


def test_score_weight_never_buys_non_positive_scores():
    definition = valid_definition()
    definition["portfolio"]["weighting"] = "score_weight"
    definition["entry"]["ranking"]["top_n"] = 2
    result = DeterministicSignalEngine().evaluate(
        version=version(definition),
        universe=universe(),
        factor_snapshots=(snapshot(),),
        factor_rows=rows(
            values={"000001": 0.10, "000002": 0.05, "000003": -0.01}
        ),
        as_of=VISIBLE_AT,
        metadata_by_symbol=metadata(),
    )
    signals = by_symbol(result)
    assert signals["000001"].signal_type == "buy"
    assert signals["000001"].score > 0
    assert signals["000002"].signal_type == "hold"
    assert signals["000002"].score < 0
    assert signals["000002"].reason_codes == ("NON_POSITIVE_SCORE",)


def test_rejects_future_unpublished_and_non_owner_snapshots():
    engine = DeterministicSignalEngine()
    future = snapshot(
        as_of=VISIBLE_AT + timedelta(minutes=1),
        published_at=VISIBLE_AT + timedelta(minutes=2),
    )
    with pytest.raises(SignalInputError, match="future factor snapshot as_of"):
        engine.evaluate(
            version=version(),
            universe=universe(),
            factor_snapshots=(future,),
            factor_rows=rows(),
            as_of=VISIBLE_AT,
            metadata_by_symbol=metadata(),
        )

    foreign = snapshot().model_copy(update={"user_id": "bob"})
    with pytest.raises(SignalInputError, match="not owner-visible"):
        engine.evaluate(
            version=version(),
            universe=universe(),
            factor_snapshots=(foreign,),
            factor_rows=rows(),
            as_of=VISIBLE_AT,
            metadata_by_symbol=metadata(),
        )


def test_all_whitelisted_condition_nodes_are_deterministic():
    condition = StrategyEntrySpec.model_validate(
        {
            "condition": {
                "type": "all",
                "children": [
                    {
                        "type": "compare",
                        "left": {"kind": "factor", "factor_id": "ret_1d"},
                        "operator": "gt",
                        "right": {"kind": "constant", "value": 0},
                    },
                    {
                        "type": "cross_up",
                        "left": {"kind": "factor", "factor_id": "ret_1d"},
                        "right": {"kind": "constant", "value": 0.07},
                        "periods": 1,
                    },
                    {
                        "type": "changed",
                        "factor": {"kind": "factor", "factor_id": "ret_1d"},
                        "periods": 1,
                        "operator": "gt",
                        "threshold": 0.05,
                    },
                    {
                        "type": "rank",
                        "factor": {"kind": "factor", "factor_id": "ret_1d"},
                        "mode": "top_n",
                        "top_n": 1,
                    },
                    {
                        "type": "not",
                        "child": {
                            "type": "compare",
                            "left": {
                                "kind": "factor",
                                "factor_id": "hist_vol_20",
                            },
                            "operator": "gt",
                            "right": {"kind": "constant", "value": 0.15},
                        },
                    },
                    {
                        "type": "any",
                        "children": [
                            {
                                "type": "compare",
                                "left": {
                                    "kind": "factor",
                                    "factor_id": "ret_1d",
                                },
                                "operator": "gt",
                                "right": {"kind": "constant", "value": 0.2},
                            },
                            {
                                "type": "compare",
                                "left": {
                                    "kind": "factor",
                                    "factor_id": "hist_vol_20",
                                },
                                "operator": "lt",
                                "right": {"kind": "constant", "value": 0.15},
                            },
                        ],
                    },
                ],
            }
        }
    ).condition
    assert condition is not None
    history = {
        "000001": {"ret_1d": (0.0, 0.1), "hist_vol_20": (0.2, 0.1)},
        "000002": {"ret_1d": (0.0, 0.05), "hist_vol_20": (0.2, 0.2)},
    }
    result = evaluate_condition(
        condition,
        ConditionContext(symbol="000001", history_by_symbol=history),
    )
    assert result.passed
    assert not result.missing_factors
    assert condition_tree_stats(condition).nodes == 10
