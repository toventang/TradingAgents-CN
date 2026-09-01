from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.models.backtest import (
    BrokerFill,
    CorporateAction,
    CorporateActionType,
    FeeBreakdown,
    OrderSide,
)
from app.models.symbol import Currency, Market
from app.services.backtest.ledger import (
    BacktestCheckpoint,
    BacktestEquityDailyRecord,
    BacktestEventRecord,
    DailyLedgerBatch,
)
from app.services.backtest.portfolio import (
    PortfolioReconciliationError,
    PortfolioState,
)


DAY1 = date(2024, 1, 8)
DAY2 = date(2024, 1, 9)


def fill(
    *,
    side: OrderSide,
    day: date,
    price: str,
    fees: str,
    quantity: int = 100,
) -> BrokerFill:
    fill_price = Decimal(price)
    return BrokerFill(
        order_id=f"{side.value}-{day}",
        market=Market.CN,
        symbol="600000",
        side=side,
        trade_date=day,
        quantity=quantity,
        raw_price=fill_price,
        slippage_per_share=Decimal("0"),
        fill_price=fill_price,
        notional=fill_price * quantity,
        fees=FeeBreakdown(commission=Decimal(fees)),
    )


def test_fifo_cash_positions_fees_and_equity_reconcile_by_hand():
    portfolio = PortfolioState(market=Market.CN, initial_cash=Decimal("10000"))
    portfolio.apply_fill(
        fill(side=OrderSide.BUY, day=DAY1, price="10", fees="5"),
        trade_id="trade-buy",
        available_trade_date=DAY2,
    )

    assert portfolio.cash == Decimal("8995.00")
    assert portfolio.quantity("600000") == 100
    assert portfolio.available_quantity("600000", DAY1) == 0
    assert portfolio.available_quantity("600000", DAY2) == 100
    assert portfolio.average_cost("600000") == Decimal("10.05")
    assert portfolio.equity({"600000": Decimal("11")}) == Decimal("10095.00")

    realized = portfolio.apply_fill(
        fill(side=OrderSide.SELL, day=DAY2, price="11", fees="6"),
        trade_id="trade-sell",
        available_trade_date=DAY2,
    )

    assert realized == Decimal("89.00")
    assert portfolio.cash == Decimal("10089.00")
    assert portfolio.symbols == ()
    assert portfolio.equity({}) == Decimal("10089.00")
    assert portfolio.total_fees == Decimal("11.00")


def test_dividend_and_split_conserve_shareholder_value():
    portfolio = PortfolioState(market=Market.CN, initial_cash=Decimal("10000"))
    portfolio.apply_fill(
        fill(side=OrderSide.BUY, day=DAY1, price="10", fees="0"),
        trade_id="trade-buy",
        available_trade_date=DAY2,
    )
    dividend = CorporateAction(
        action_id="dividend",
        market=Market.CN,
        symbol="600000",
        action_type=CorporateActionType.CASH_DIVIDEND,
        ex_date=DAY2,
        announced_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        ingested_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        cash_per_share=Decimal("1"),
        currency=Currency.CNY,
        source="fixture",
        source_version="v1",
    )
    split = CorporateAction(
        action_id="split",
        market=Market.CN,
        symbol="600000",
        action_type=CorporateActionType.SPLIT,
        ex_date=DAY2,
        announced_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        ingested_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        share_multiplier=Decimal("2"),
        currency=Currency.CNY,
        source="fixture",
        source_version="v1",
    )

    dividend_result = portfolio.apply_corporate_action(dividend)
    split_result = portfolio.apply_corporate_action(split)

    assert dividend_result["cash_delta"] == Decimal("100.00")
    assert split_result["quantity_after"] == 200
    assert portfolio.cash == Decimal("9100.00")
    assert portfolio.average_cost("600000") == Decimal("5")
    assert portfolio.equity({"600000": Decimal("5")}) == Decimal("10100.00")


def test_fractional_reverse_split_fails_without_cash_in_lieu_data():
    portfolio = PortfolioState(market=Market.CN, initial_cash=Decimal("10000"))
    portfolio.apply_fill(
        fill(
            side=OrderSide.BUY,
            day=DAY1,
            price="10",
            fees="0",
            quantity=100,
        ),
        trade_id="trade-buy",
        available_trade_date=DAY2,
    )
    reverse = CorporateAction(
        action_id="reverse",
        market=Market.CN,
        symbol="600000",
        action_type=CorporateActionType.REVERSE_SPLIT,
        ex_date=DAY2,
        announced_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        ingested_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        share_multiplier=Decimal("0.015"),
        currency=Currency.CNY,
        source="fixture",
        source_version="v1",
    )

    with pytest.raises(PortfolioReconciliationError, match="fractional shares"):
        portfolio.apply_corporate_action(reverse)


def test_daily_batch_requires_all_twelve_steps_and_cash_equity_reconciliation():
    events = tuple(
        BacktestEventRecord(
            event_id=f"event-{step}",
            run_id="run-1",
            user_id="owner",
            trade_date=DAY1,
            sequence=step,
            step=step,
            event_type=f"STEP_{step}",
        )
        for step in range(1, 13)
    )
    equity = BacktestEquityDailyRecord(
        run_id="run-1",
        user_id="owner",
        trade_date=DAY1,
        cash=Decimal("1000"),
        market_value=Decimal("0"),
        equity=Decimal("1000"),
        cumulative_return=Decimal("0"),
        drawdown=Decimal("0"),
    )
    checkpoint = BacktestCheckpoint(
        run_id="run-1",
        user_id="owner",
        trade_date=DAY1,
        portfolio_state={"cash": "1000"},
        pending_orders=(),
        signal_ids={},
        cooldown_until={},
        last_prices={},
        previous_equity=Decimal("1000"),
        peak_equity=Decimal("1000"),
        completed_days=1,
        order_count=0,
        trade_count=0,
    )

    batch = DailyLedgerBatch(
        run_id="run-1",
        user_id="owner",
        trade_date=DAY1,
        equity=equity,
        events=events,
        checkpoint=checkpoint,
    )
    assert batch.equity.cash + batch.equity.market_value == batch.equity.equity

    with pytest.raises(ValidationError, match="every step"):
        DailyLedgerBatch(
            run_id="run-1",
            user_id="owner",
            trade_date=DAY1,
            equity=equity,
            events=events[:-1],
            checkpoint=checkpoint,
        )
    with pytest.raises(ValidationError, match=r"cash \+ market value"):
        BacktestEquityDailyRecord(
            **{
                **equity.model_dump(mode="python"),
                "cash": Decimal("999"),
            }
        )
