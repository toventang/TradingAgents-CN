from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.models.backtest import CorporateAction, CorporateActionType
from app.models.market_data import DailyBar
from app.models.symbol import Currency, Market
from app.services.backtest.corporate_actions import CorporateActionService


UTC = timezone.utc


def at(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def bar(day: int, close: float) -> DailyBar:
    return DailyBar(
        market=Market.CN,
        symbol="000001",
        trade_date=date(2024, 1, day),
        open=close,
        high=close,
        low=close,
        close=close,
        source="fixture",
        source_version="raw-v1",
    )


def action(
    action_id: str,
    action_type: CorporateActionType,
    *,
    ex_day: int,
    cash: str = "0",
    multiplier: str = "1",
    announced_at: datetime = at("2024-01-01T00:00:00"),
    ingested_at: datetime = at("2024-01-01T00:00:00"),
) -> CorporateAction:
    return CorporateAction(
        action_id=action_id,
        market=Market.CN,
        symbol="000001",
        action_type=action_type,
        ex_date=date(2024, 1, ex_day),
        announced_at=announced_at,
        ingested_at=ingested_at,
        cash_per_share=Decimal(cash),
        share_multiplier=Decimal(multiplier),
        currency=Currency.CNY,
        source="fixture",
        source_version="actions-v1",
    )


def cutoffs(*days: int) -> dict[date, datetime]:
    return {date(2024, 1, day): at(f"2024-01-{day:02d}T08:00:00") for day in days}


def test_split_builds_continuous_return_without_changing_raw_price():
    bars = (bar(2, 100), bar(3, 50))
    split = action("split-2x", CorporateActionType.SPLIT, ex_day=3, multiplier="2")

    result = CorporateActionService.build_continuous_returns(
        bars, (split,), as_of_by_date=cutoffs(2, 3)
    )

    assert result[1].raw_close == Decimal("50.0")
    assert result[1].adjusted_return == Decimal("0")
    assert result[1].continuous_index == Decimal("1")
    assert result[1].applied_action_ids == ("split-2x",)
    assert bars[1].close == 50  # executable price is still unadjusted


def test_cash_dividend_is_included_in_total_return():
    bars = (bar(2, 10), bar(3, 9))
    dividend = action(
        "dividend-1",
        CorporateActionType.CASH_DIVIDEND,
        ex_day=3,
        cash="1",
    )

    result = CorporateActionService.build_continuous_returns(
        bars, (dividend,), as_of_by_date=cutoffs(2, 3)
    )

    assert result[1].adjusted_return == Decimal("0")
    assert result[1].continuous_index == Decimal("1")


def test_future_or_late_ingested_action_cannot_adjust_past_return():
    bars = (bar(2, 100), bar(3, 50))
    late_split = action(
        "late-split",
        CorporateActionType.SPLIT,
        ex_day=3,
        multiplier="2",
        ingested_at=at("2024-01-04T00:00:00"),
    )

    result = CorporateActionService.build_continuous_returns(
        bars, (late_split,), as_of_by_date=cutoffs(2, 3)
    )

    assert result[1].applied_action_ids == ()
    assert result[1].adjusted_return == Decimal("-0.5")


def test_bonus_and_dividend_on_same_date_compose_per_old_share():
    bars = (bar(2, 100), bar(3, 45))
    bonus = action(
        "bonus",
        CorporateActionType.BONUS_SHARE,
        ex_day=3,
        multiplier="2",
    )
    dividend = action(
        "cash",
        CorporateActionType.CASH_DIVIDEND,
        ex_day=3,
        cash="10",
    )

    result = CorporateActionService.build_continuous_returns(
        bars, (bonus, dividend), as_of_by_date=cutoffs(2, 3)
    )

    assert result[1].adjusted_return == Decimal("0")
    assert result[1].applied_action_ids == ("bonus", "cash")


def test_continuous_series_rejects_missing_close_and_mixed_symbols():
    missing = DailyBar(
        market=Market.CN,
        symbol="000001",
        trade_date=date(2024, 1, 2),
        close=None,
    )
    with pytest.raises(ValueError, match="every raw close"):
        CorporateActionService.build_continuous_returns(
            (missing,), (), as_of_by_date=cutoffs(2)
        )

    other = bar(3, 10).model_copy(update={"symbol": "000002"})
    with pytest.raises(ValueError, match="one security"):
        CorporateActionService.build_continuous_returns(
            (bar(2, 10), other), (), as_of_by_date=cutoffs(2, 3)
        )


def test_continuous_series_requires_cutoff_for_each_day_and_unique_actions():
    bars = (bar(2, 100), bar(3, 50))
    split = action("split-2x", CorporateActionType.SPLIT, ex_day=3, multiplier="2")

    with pytest.raises(ValueError, match="missing point-in-time cutoff"):
        CorporateActionService.build_continuous_returns(
            bars, (split,), as_of_by_date=cutoffs(2)
        )
    with pytest.raises(ValueError, match="duplicate action_id"):
        CorporateActionService.build_continuous_returns(
            bars, (split, split), as_of_by_date=cutoffs(2, 3)
        )
