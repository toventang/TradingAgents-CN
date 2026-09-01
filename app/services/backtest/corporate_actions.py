"""Point-in-time corporate-action and continuous-return calculations."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, localcontext
from typing import Iterable

from app.models.backtest import AdjustedReturnPoint, CorporateAction, finite_decimal
from app.models.market_data import DailyBar


class CorporateActionService:
    """Use actions for returns without mutating executable raw prices."""

    @staticmethod
    def visible_on(
        actions: Iterable[CorporateAction], *, trade_date: date, as_of: datetime
    ) -> tuple[CorporateAction, ...]:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        return tuple(
            sorted(
                (
                    item
                    for item in actions
                    if item.ex_date == trade_date and item.visible_at <= as_of
                ),
                key=lambda item: item.action_id,
            )
        )

    @classmethod
    def build_continuous_returns(
        cls,
        bars: Iterable[DailyBar],
        actions: Iterable[CorporateAction],
        *,
        as_of_by_date: dict[date, datetime],
    ) -> tuple[AdjustedReturnPoint, ...]:
        """Build a unit-indexed total-return series from unadjusted closes.

        On an ex-date, one old share becomes ``share_multiplier`` current
        shares and receives ``cash_per_share``.  The executable bar itself is
        never replaced or modified.
        """

        ordered = sorted(bars, key=lambda item: item.trade_date)
        if not ordered:
            return ()
        identities = {(item.market, item.symbol) for item in ordered}
        if len(identities) != 1:
            raise ValueError("one continuous-return series requires one security")
        if len({item.trade_date for item in ordered}) != len(ordered):
            raise ValueError("daily bars contain duplicate trade dates")
        if any(item.close is None for item in ordered):
            raise ValueError("continuous returns require every raw close")

        market, symbol = next(iter(identities))
        action_map: dict[date, list[CorporateAction]] = defaultdict(list)
        action_ids: set[str] = set()
        for action in actions:
            if (action.market, action.symbol) != (market, symbol):
                raise ValueError("corporate action does not match bar identity")
            if action.action_id in action_ids:
                raise ValueError("corporate actions contain a duplicate action_id")
            action_ids.add(action.action_id)
            action_map[action.ex_date].append(action)

        result: list[AdjustedReturnPoint] = []
        previous_close: Decimal | None = None
        continuous_index = Decimal("1")
        for bar in ordered:
            if bar.trade_date not in as_of_by_date:
                raise ValueError(
                    f"missing point-in-time cutoff for {bar.trade_date.isoformat()}"
                )
            close = finite_decimal(bar.close)  # type: ignore[arg-type]
            applied = cls.visible_on(
                action_map.get(bar.trade_date, ()),
                trade_date=bar.trade_date,
                as_of=as_of_by_date[bar.trade_date],
            )
            adjusted_return: Decimal | None = None
            if previous_close is not None:
                multiplier = Decimal("1")
                cash = Decimal("0")
                for action in applied:
                    # Cash is expressed per old share.  Multiple share changes
                    # compound; cash actions add on the same old-share basis.
                    multiplier *= action.share_multiplier
                    cash += action.cash_per_share
                with localcontext() as context:
                    context.prec = 34
                    adjusted_return = (close * multiplier + cash) / previous_close - 1
                    continuous_index *= 1 + adjusted_return
            result.append(
                AdjustedReturnPoint(
                    market=market,
                    symbol=symbol,
                    trade_date=bar.trade_date,
                    raw_close=close,
                    adjusted_return=adjusted_return,
                    continuous_index=continuous_index,
                    applied_action_ids=tuple(item.action_id for item in applied),
                )
            )
            previous_close = close
        return tuple(result)


def build_continuous_returns(
    bars: Iterable[DailyBar],
    actions: Iterable[CorporateAction],
    *,
    as_of_by_date: dict[date, datetime],
) -> tuple[AdjustedReturnPoint, ...]:
    """Functional compatibility wrapper for the service method."""

    return CorporateActionService.build_continuous_returns(
        bars, actions, as_of_by_date=as_of_by_date
    )
