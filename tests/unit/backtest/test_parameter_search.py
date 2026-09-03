from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.models.backtest import BacktestRequest
from app.models.symbol import Market
from app.services.backtest.ledger import BacktestEquityDailyRecord, BacktestRunStatus
from app.services.backtest.parameter_search import (
    EvaluationSegment,
    ParameterCombinationResult,
    ParameterGridAxis,
    ParameterSearchMode,
    ParameterSearchPlanner,
    ParameterSearchRequest,
    ParameterSearchValidationError,
    RESEARCH_ONLY_NOTICE,
    SplitWindowConfig,
    WalkForwardConfig,
    apply_stability_and_ranking,
    calculate_window_performance,
    summarize_window_returns,
)


def base_request(**updates) -> BacktestRequest:
    values = {
        "strategy_version_id": "strategy-v1",
        "market": Market.CN,
        "start_date": date(2024, 1, 1),
        "end_date": date(2024, 6, 30),
        "initial_cash": Decimal("100"),
        "benchmark": "000300",
        "execution_model_id": "next_open",
    }
    values.update(updates)
    return BacktestRequest(**values)


def weekdays(start: date, count: int) -> tuple[date, ...]:
    days = []
    current = start
    while len(days) < count:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return tuple(days)


def split_request(axes: tuple[ParameterGridAxis, ...]) -> ParameterSearchRequest:
    return ParameterSearchRequest(
        base_request=base_request(),
        axes=axes,
        mode=ParameterSearchMode.SPLIT,
        split=SplitWindowConfig(
            train_end=date(2024, 3, 15), validation_end=date(2024, 5, 15)
        ),
    )


def test_one_to_three_axis_grid_is_deterministic_and_bounded():
    request = split_request(
        (
            ParameterGridAxis(name="lookback", values=(10, 20)),
            ParameterGridAxis(name="threshold", values=(Decimal("0.1"), Decimal("0.2"))),
            ParameterGridAxis(name="enabled", values=(False, True)),
        )
    )
    plan = ParameterSearchPlanner().build(request, weekdays(date(2024, 1, 1), 125))

    assert len(plan.combinations) == 8
    assert plan.combinations[0].values == {
        "lookback": 10,
        "threshold": Decimal("0.1"),
        "enabled": False,
    }
    assert plan.combinations[-1].values == {
        "lookback": 20,
        "threshold": Decimal("0.2"),
        "enabled": True,
    }
    assert len({item.checksum for item in plan.combinations}) == 8

    with pytest.raises(ValidationError, match="above requested limit"):
        ParameterSearchRequest(
            base_request=base_request(),
            axes=(ParameterGridAxis(name="value", values=tuple(range(101))),),
            mode="split",
            split={"train_end": "2024-03-15", "validation_end": "2024-05-15"},
        )
    with pytest.raises(ValidationError, match="hard limit of 500"):
        ParameterSearchRequest(
            base_request=base_request(),
            axes=(
                ParameterGridAxis(name="first", values=tuple(range(25))),
                ParameterGridAxis(name="second", values=tuple(range(21))),
            ),
            mode="split",
            split={"train_end": "2024-03-15", "validation_end": "2024-05-15"},
            combination_limit=500,
        )


def test_split_uses_actual_sessions_and_keeps_test_strictly_held_out():
    dates = weekdays(date(2024, 1, 1), 125)
    plan = ParameterSearchPlanner().build(
        split_request((ParameterGridAxis(name="lookback", values=(10,)),)), dates
    )
    train, validation, test = plan.windows

    assert train.segment == EvaluationSegment.TRAIN
    assert validation.segment == EvaluationSegment.VALIDATION
    assert test.segment == EvaluationSegment.TEST
    assert train.end_date < validation.start_date
    assert validation.end_date < test.start_date
    assert sum(item.session_count for item in plan.windows) == len(dates)


def test_walk_forward_has_ordered_non_overlapping_segments_and_bounded_folds():
    dates = weekdays(date(2024, 1, 1), 105)
    request = ParameterSearchRequest(
        base_request=base_request(),
        axes=(ParameterGridAxis(name="lookback", values=(10, 20)),),
        mode="walk_forward",
        walk_forward=WalkForwardConfig(
            train_sessions=40,
            validation_sessions=10,
            test_sessions=10,
            step_sessions=15,
            max_folds=3,
        ),
    )
    plan = ParameterSearchPlanner().build(request, dates)

    assert len(plan.windows) == 9
    for fold in range(3):
        train, validation, test = plan.windows[fold * 3 : fold * 3 + 3]
        assert train.end_date < validation.start_date < test.start_date
        assert (train.session_count, validation.session_count, test.session_count) == (40, 10, 10)
    with pytest.raises(ParameterSearchValidationError, match="requires 60"):
        ParameterSearchPlanner().build(request, dates[:59])


def test_window_metrics_use_prior_equity_and_never_cross_window_boundaries():
    dates = weekdays(date(2024, 1, 1), 125)
    plan = ParameterSearchPlanner().build(
        split_request((ParameterGridAxis(name="lookback", values=(10,)),)), dates
    )
    equity = []
    value = Decimal("100")
    for index, day in enumerate(dates):
        value *= Decimal("1.01") if index < 80 else Decimal("0.99")
        equity.append(
            BacktestEquityDailyRecord(
                run_id="run",
                user_id="owner",
                trade_date=day,
                cash=value,
                market_value=Decimal("0"),
                equity=value,
                cumulative_return=value / Decimal("100") - 1,
                drawdown=Decimal("0"),
            )
        )
    metrics = calculate_window_performance(
        equity, plan.windows, initial_equity=Decimal("100")
    )

    assert all(item.observations == window.session_count for item, window in zip(metrics, plan.windows))
    assert summarize_window_returns(metrics, EvaluationSegment.TRAIN) is not None
    assert metrics[2].total_return is not None and metrics[2].total_return < 0


def test_ranking_uses_validation_not_test_or_train_and_reports_stability():
    axes = (ParameterGridAxis(name="lookback", values=(10, 20, 30)),)

    def result(index: int, validation: str, test: str) -> ParameterCombinationResult:
        return ParameterCombinationResult(
            search_id="search",
            user_id="owner",
            combination_index=index,
            parameters={"lookback": axes[0].values[index]},
            child_run_id=f"run-{index}",
            status=BacktestRunStatus.SUCCEEDED,
            train_mean_return=Decimal("9") if index == 0 else Decimal("0"),
            validation_mean_return=Decimal(validation),
            test_mean_return=Decimal(test),
        )

    ranked = apply_stability_and_ranking(
        (result(0, "0.10", "0.50"), result(1, "0.12", "-0.10"), result(2, "0.11", "0.01")),
        axes,
    )

    assert ranked[1].selected_candidate is True
    assert ranked[1].validation_rank == 1
    assert ranked[0].validation_rank == 3
    assert ranked[1].test_mean_return == Decimal("-0.10")
    assert ranked[1].stability is not None
    assert ranked[1].stability.neighboring_combinations == 2
    assert "NO_AUTOMATIC_PUBLICATION" in RESEARCH_ONLY_NOTICE
    assert all("publish" not in item.model_dump() for item in ranked)
