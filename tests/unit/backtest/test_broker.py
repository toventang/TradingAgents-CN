from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models.backtest import (
    BrokerOrder,
    BrokerOrderStatus,
    ExecutionPriceModel,
    ExitReason,
    ExitRuleConfig,
    FeeSchedule,
    OrderSide,
    PositionLot,
    ResolvedMarketRules,
    SameBarConflictMode,
    SecurityRuleContext,
    SlippageConfig,
    SlippageModel,
)
from app.models.market_data import DailyBar
from app.models.symbol import Market
from app.services.backtest.broker import SimulatedBroker
from app.services.backtest.execution import ExitRuleService


SIGNAL_DATE = date(2024, 1, 5)
TRADE_DATE = date(2024, 1, 8)


def rules(
    market: Market = Market.CN,
    *,
    symbol: str = "600000",
    trade_date: date = TRADE_DATE,
    lot_size: int | None = None,
    t_plus: int | None = None,
    participation: str = "0.10",
    fees: FeeSchedule | None = None,
    strict_limit: bool = False,
):
    return ResolvedMarketRules(
        rule_version_id=f"{market.value}-rules",
        market=market,
        symbol=symbol,
        trade_date=trade_date,
        lot_size=lot_size or (100 if market == Market.CN else 1),
        t_plus_days=(1 if market == Market.CN else 0) if t_plus is None else t_plus,
        participation_rate=Decimal(participation),
        price_limit_pct=Decimal("0.10") if market == Market.CN else None,
        strict_locked_limit=strict_limit,
        fee_schedule=fees or FeeSchedule(),
    )


def security(market=Market.CN, symbol="600000"):
    return SecurityRuleContext(market=market, symbol=symbol)


def order(
    *,
    side=OrderSide.BUY,
    quantity=100,
    expires_on=date(2024, 1, 10),
    execution=ExecutionPriceModel.NEXT_OPEN,
    slippage=None,
    market=Market.CN,
    symbol="600000",
    filled=0,
    status=BrokerOrderStatus.PENDING,
    attempts=0,
):
    return BrokerOrder(
        order_id="order-1",
        market=market,
        symbol=symbol,
        side=side,
        requested_quantity=quantity,
        filled_quantity=filled,
        created_trade_date=SIGNAL_DATE,
        expires_on=expires_on,
        execution_model=execution,
        slippage=slippage or SlippageConfig(),
        status=status,
        execution_attempts=attempts,
    )


def bar(
    *,
    trade_date=TRADE_DATE,
    market=Market.CN,
    symbol="600000",
    open_price=10,
    high=11,
    low=9,
    close=10.5,
    pre_close=10,
    volume=10000,
    amount=100000,
    suspended=False,
):
    return DailyBar(
        market=market,
        symbol=symbol,
        trade_date=trade_date,
        open=open_price,
        high=high,
        low=low,
        close=close,
        pre_close=pre_close,
        volume=volume,
        amount=amount,
        suspended=suspended,
        source="fixture",
        source_version="bars-v1",
    )


def lot(
    lot_id: str,
    *,
    available: date,
    quantity: int = 100,
    market=Market.CN,
    symbol="600000",
):
    return PositionLot(
        lot_id=lot_id,
        market=market,
        symbol=symbol,
        quantity=quantity,
        remaining_quantity=quantity,
        acquired_trade_date=SIGNAL_DATE if available <= TRADE_DATE else TRADE_DATE,
        available_trade_date=available,
        unit_cost=Decimal("10"),
    )


def test_next_open_fixed_slippage_and_cn_minimum_fee_are_hand_calculated():
    broker = SimulatedBroker()
    fee_schedule = FeeSchedule(
        commission_rate=Decimal("0.0003"), minimum_commission=Decimal("5")
    )
    request = order(
        slippage=SlippageConfig(model=SlippageModel.FIXED_BPS, fixed_bps=Decimal("10"))
    )

    result = broker.execute(
        request,
        bar(),
        security(),
        rules(fees=fee_schedule),
    )

    assert result.status == BrokerOrderStatus.FILLED
    assert result.fill is not None
    assert result.fill.raw_price == Decimal("10")
    assert result.fill.fill_price == Decimal("10.01")
    assert result.fill.slippage_per_share == Decimal("0.01")
    assert result.fill.notional == Decimal("1001.00")
    assert result.fill.fees.commission == Decimal("5.00")

    next_close = broker.execute(
        order(execution=ExecutionPriceModel.NEXT_CLOSE),
        bar(close=10.5),
        security(),
        rules(),
    )
    assert next_close.fill is not None
    assert next_close.fill.raw_price == Decimal("10.5")
    assert next_close.fill.fill_price == Decimal("10.5")


def test_vwap_proxy_volume_impact_is_hand_calculated_and_deterministic():
    broker = SimulatedBroker()
    request = order(
        execution=ExecutionPriceModel.NEXT_VWAP_PROXY,
        slippage=SlippageConfig(
            model=SlippageModel.VOLUME_IMPACT,
            base_bps=Decimal("10"),
            impact_coefficient=Decimal("100"),
        ),
    )
    daily_bar = bar(open_price=9, high=11, low=9, close=10, amount=100000)

    first = broker.execute(request, daily_bar, security(), rules())
    second = broker.execute(request, daily_bar, security(), rules())

    assert first == second
    assert first.fill is not None
    # raw=amount/volume=10; sqrt(1000/100000)=0.1; 10+100*0.1=20 bps
    assert first.fill.raw_price == Decimal("10")
    assert first.fill.fill_price == Decimal("10.02")
    assert "VWAP_PROXY_RESEARCH_ONLY" in first.fill.warnings

    inconsistent_amount = broker.execute(
        order(execution=ExecutionPriceModel.NEXT_VWAP_PROXY),
        bar(open_price=9, high=11, low=9, close=10, amount=120000),
        security(),
        rules(),
    )
    assert inconsistent_amount.fill is not None
    assert inconsistent_amount.fill.raw_price == Decimal("11")
    assert "VWAP_PROXY_CLIPPED_TO_DAILY_RANGE" in inconsistent_amount.fill.warnings


def test_participation_causes_partial_fill_and_expires_remaining_on_last_day():
    broker = SimulatedBroker()
    request = order(quantity=300)
    partial = broker.execute(request, bar(volume=1000), security(), rules())

    assert partial.status == BrokerOrderStatus.PARTIALLY_FILLED
    assert partial.fill is not None and partial.fill.quantity == 100
    assert partial.remaining_quantity == 200
    assert "PARTICIPATION_LIMIT" in partial.warnings

    last_attempt = order(
        quantity=300,
        filled=100,
        status=BrokerOrderStatus.PARTIALLY_FILLED,
        expires_on=date(2024, 1, 9),
    )
    final = broker.execute(
        last_attempt,
        bar(trade_date=date(2024, 1, 9), volume=1000),
        security(),
        rules(trade_date=date(2024, 1, 9)),
    )
    assert final.status == BrokerOrderStatus.EXPIRED
    assert final.fill is not None and final.fill.quantity == 100
    assert final.remaining_quantity == 100


def test_suspension_and_locked_limit_defer_then_expire_without_fill():
    broker = SimulatedBroker()
    pending = broker.execute(
        order(), bar(suspended=True), security(), rules()
    )
    assert pending.status == BrokerOrderStatus.PENDING
    assert pending.reason == "SUSPENDED"

    expired = broker.execute(
        order(expires_on=TRADE_DATE),
        bar(open_price=11, high=11, low=11, close=11),
        security(),
        rules(strict_limit=True),
    )
    assert expired.status == BrokerOrderStatus.EXPIRED
    assert expired.fill is None
    assert expired.reason == "BUY_LOCKED_AT_UPPER_LIMIT"

    # The bar traded below the limit, but a next-open order still cannot buy
    # when its selected execution price is the upper limit.
    at_limit = broker.execute(
        order(),
        bar(open_price=11, high=11, low=10, close=10.5),
        security(),
        rules(strict_limit=True),
    )
    assert at_limit.status == BrokerOrderStatus.PENDING
    assert at_limit.reason == "BUY_AT_UPPER_LIMIT"


def test_cn_t1_blocks_today_lot_but_can_partially_sell_available_lot():
    broker = SimulatedBroker()
    request = order(side=OrderSide.SELL, quantity=200)
    old = lot("old", available=TRADE_DATE)
    today = lot("today", available=date(2024, 1, 9))

    result = broker.execute(
        request,
        bar(),
        security(),
        rules(),
        position_lots=(old, today),
        position_quantity=200,
    )

    assert result.status == BrokerOrderStatus.PARTIALLY_FILLED
    assert result.fill is not None and result.fill.quantity == 100
    assert result.remaining_quantity == 100
    assert "T_PLUS_ONE_OR_POSITION_UNAVAILABLE" in result.warnings


def test_hk_and_us_use_security_lots_and_integer_shares():
    broker = SimulatedBroker()
    hk = broker.execute(
        order(market=Market.HK, symbol="00700", quantity=200),
        bar(market=Market.HK, symbol="00700", volume=10000),
        security(Market.HK, "00700"),
        rules(Market.HK, symbol="00700", lot_size=200),
    )
    us = broker.execute(
        order(market=Market.US, symbol="AAPL", quantity=3),
        bar(market=Market.US, symbol="AAPL", volume=1000),
        security(Market.US, "AAPL"),
        rules(Market.US, symbol="AAPL"),
    )

    assert hk.status == BrokerOrderStatus.FILLED
    assert hk.fill is not None and hk.fill.quantity == 200
    assert us.status == BrokerOrderStatus.FILLED
    assert us.fill is not None and us.fill.quantity == 3


def test_invalid_volume_and_missing_t1_lots_fail_closed():
    broker = SimulatedBroker()
    no_volume = broker.execute(
        order(), bar(volume=0), security(), rules()
    )
    no_lots = broker.execute(
        order(side=OrderSide.SELL),
        bar(),
        security(),
        rules(),
        position_quantity=100,
    )
    assert no_volume.status == BrokerOrderStatus.REJECTED
    assert no_volume.reason == "INVALID_OR_MISSING_VOLUME"
    assert no_lots.status == BrokerOrderStatus.REJECTED
    assert no_lots.reason == "SETTLEMENT_LOTS_REQUIRED"


def test_order_expires_after_third_execution_day_even_if_date_expiry_is_later():
    broker = SimulatedBroker()
    result = broker.execute(
        order(attempts=2),
        bar(suspended=True),
        security(),
        rules(),
    )

    assert result.status == BrokerOrderStatus.EXPIRED
    assert result.execution_attempts == 3
    assert result.reason == "SUSPENDED"

    previously_partial = broker.execute(
        order(
            quantity=300,
            filled=100,
            status=BrokerOrderStatus.PARTIALLY_FILLED,
            attempts=1,
        ),
        bar(suspended=True),
        security(),
        rules(),
    )
    assert previously_partial.status == BrokerOrderStatus.PARTIALLY_FILLED
    assert previously_partial.fill is None
    assert previously_partial.cumulative_filled_quantity == 100
    assert previously_partial.remaining_quantity == 200


@pytest.mark.parametrize(
    ("mode", "expected", "research_only"),
    [
        (SameBarConflictMode.CONSERVATIVE, ExitReason.FIXED_STOP_LOSS, False),
        (SameBarConflictMode.OPTIMISTIC, ExitReason.FIXED_TAKE_PROFIT, True),
        (SameBarConflictMode.OPEN_PATH, ExitReason.FIXED_STOP_LOSS, True),
    ],
)
def test_same_bar_stop_take_conflicts_are_explicit(mode, expected, research_only):
    decision = ExitRuleService.evaluate(
        bar(open_price=100, high=115, low=85, close=105),
        average_cost=Decimal("100"),
        highest_observed_price=Decimal("110"),
        holding_days=5,
        config=ExitRuleConfig(
            fixed_stop_loss_pct=Decimal("0.10"),
            fixed_take_profit_pct=Decimal("0.10"),
            conflict_mode=mode,
        ),
    )

    assert decision.reason == expected
    assert decision.same_bar_conflict is True
    assert decision.research_only_assumption is research_only
    assert decision.assumption_warning == f"SAME_BAR_EXIT_CONFLICT:{mode.value}"


def test_atr_trailing_time_signal_and_drawdown_exit_semantics():
    atr_stop = ExitRuleService.evaluate(
        bar(open_price=100, high=103, low=95, close=101),
        average_cost=Decimal("100"),
        highest_observed_price=Decimal("110"),
        holding_days=2,
        entry_atr=Decimal("2"),
        current_atr=Decimal("2"),
        config=ExitRuleConfig(
            atr_stop_multiple=Decimal("2"),
            trailing_stop_pct=Decimal("0.10"),
        ),
    )
    # Trailing stop 99 is tighter than ATR stop 96.
    assert atr_stop.reason == ExitReason.TRAILING_STOP
    assert atr_stop.trigger_price == Decimal("99.0")

    quiet_bar = bar(open_price=100, high=102, low=99, close=101)
    config = ExitRuleConfig(maximum_holding_days=5)
    drawdown = ExitRuleService.evaluate(
        quiet_bar,
        average_cost=Decimal("100"),
        highest_observed_price=Decimal("102"),
        holding_days=5,
        config=config,
        signal_exit=True,
        portfolio_drawdown_liquidation=True,
    )
    signal = ExitRuleService.evaluate(
        quiet_bar,
        average_cost=Decimal("100"),
        highest_observed_price=Decimal("102"),
        holding_days=5,
        config=config,
        signal_exit=True,
    )
    timed = ExitRuleService.evaluate(
        quiet_bar,
        average_cost=Decimal("100"),
        highest_observed_price=Decimal("102"),
        holding_days=5,
        config=config,
    )
    assert drawdown.reason == ExitReason.PORTFOLIO_DRAWDOWN
    assert signal.reason == ExitReason.SIGNAL_EXIT
    assert timed.reason == ExitReason.TIME_EXIT

    conflict = ExitRuleService.resolve_signal_priority(
        exit_decision=timed, buy_signal=True, cooldown_active=False
    )
    cooldown = ExitRuleService.resolve_signal_priority(
        exit_decision=type(timed)(triggered=False),
        buy_signal=True,
        cooldown_active=True,
    )
    buy = ExitRuleService.resolve_signal_priority(
        exit_decision=type(timed)(triggered=False),
        buy_signal=True,
        cooldown_active=False,
    )
    assert conflict.exit_selected is True and conflict.buy_allowed is False
    assert conflict.reason == "EXIT_PRIORITY"
    assert cooldown.buy_allowed is False and cooldown.reason == "COOLDOWN_ACTIVE"
    assert buy.buy_allowed is True and buy.reason == "BUY_SIGNAL"


def test_slippage_is_clipped_to_observed_range_with_warning():
    broker = SimulatedBroker()
    result = broker.execute(
        order(
            slippage=SlippageConfig(
                model=SlippageModel.FIXED_BPS, fixed_bps=Decimal("100")
            )
        ),
        bar(open_price=10, high=10.05, low=9.5, close=10),
        security(),
        rules(),
    )
    assert result.fill is not None
    assert result.fill.fill_price == Decimal("10.05")
    assert "SLIPPAGE_CLIPPED_TO_DAILY_RANGE" in result.fill.warnings
