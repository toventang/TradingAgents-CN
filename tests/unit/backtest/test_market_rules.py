from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.models.backtest import (
    MarketRuleVersion,
    OrderSide,
    PositionLot,
    SecurityRuleContext,
)
from app.models.market_data import DailyBar
from app.models.symbol import Market
from app.services.paper.market_rules import (
    DatedMarketRuleService,
    MarketRuleConfigurationError,
)


UTC = timezone.utc
TRADE_DATE = date(2024, 1, 8)
AS_OF = datetime(2024, 1, 8, 7, tzinfo=UTC)


def version(market: Market, rules: dict, *, published_at: datetime | None = None):
    return MarketRuleVersion(
        rule_version_id=f"{market.value.lower()}-2024",
        market=market,
        effective_from=date(2024, 1, 1),
        published_at=published_at or datetime(2023, 12, 1, tzinfo=UTC),
        rules=rules,
    )


def context(market: Market, symbol: str, **values):
    return SecurityRuleContext(market=market, symbol=symbol, **values)


def test_cn_fees_lots_t1_and_locked_price_limits_are_hand_calculated():
    service = DatedMarketRuleService()
    resolved = service.resolve(
        version(
            Market.CN,
            {
                "lot_size": 100,
                "t_plus": 1,
                "price_limit_pct": "0.10",
                "fees": {
                    "commission_rate": "0.0003",
                    "minimum_commission": "5",
                    "stamp_duty_rate": "0.001",
                    "transfer_fee_rate": "0.00001",
                },
            },
        ),
        context(Market.CN, "600000"),
        trade_date=TRADE_DATE,
        as_of=AS_OF,
    )

    assert resolved.lot_size == 100
    assert resolved.t_plus_days == 1
    buy = service.calculate_fees(
        resolved, OrderSide.BUY, quantity=1000, notional=Decimal("10000")
    )
    sell = service.calculate_fees(
        resolved, OrderSide.SELL, quantity=1000, notional=Decimal("10000")
    )
    assert buy.commission == Decimal("5.00")
    assert buy.transfer_fee == Decimal("0.10")
    assert buy.total == Decimal("5.10")
    assert sell.stamp_duty == Decimal("10.00")
    assert sell.total == Decimal("15.10")

    upper_locked = DailyBar(
        market=Market.CN,
        symbol="600000",
        trade_date=TRADE_DATE,
        open=11,
        high=11,
        low=11,
        close=11,
        pre_close=10,
        volume=10000,
    )
    lower_locked = upper_locked.model_copy(
        update={"open": 9, "high": 9, "low": 9, "close": 9}
    )
    security = context(Market.CN, "600000")
    assert (
        service.locked_limit_reason(OrderSide.BUY, upper_locked, security, resolved)
        == "BUY_LOCKED_AT_UPPER_LIMIT"
    )
    assert (
        service.locked_limit_reason(OrderSide.SELL, lower_locked, security, resolved)
        == "SELL_LOCKED_AT_LOWER_LIMIT"
    )


def test_cn_board_and_st_limits_are_resolved_from_dated_payload():
    service = DatedMarketRuleService()
    rules = version(
        Market.CN,
        {
            "lot_size": 100,
            "price_limits": {
                "default": "0.10",
                "st": "0.05",
                "boards": {"STAR": "0.20"},
            },
        },
    )
    star = service.resolve(
        rules,
        context(Market.CN, "688001", board="STAR"),
        trade_date=TRADE_DATE,
        as_of=AS_OF,
    )
    special_treatment = service.resolve(
        rules,
        context(Market.CN, "600001", is_st=True),
        trade_date=TRADE_DATE,
        as_of=AS_OF,
    )

    assert star.price_limit_pct == Decimal("0.20")
    assert special_treatment.price_limit_pct == Decimal("0.05")


def test_hk_lot_and_all_fee_components_are_hand_calculated():
    service = DatedMarketRuleService()
    resolved = service.resolve(
        version(
            Market.HK,
            {
                "fees": {
                    "rate": "0.0003",
                    "min": "5",
                    "transaction_levy_rate": "0.000027",
                    "trading_fee_rate": "0.0000565",
                    "settlement_fee_rate": "0.00002",
                }
            },
        ),
        context(Market.HK, "00700", lot_size=200),
        trade_date=TRADE_DATE,
        as_of=AS_OF,
    )

    fees = service.calculate_fees(
        resolved, OrderSide.BUY, quantity=200, notional=Decimal("10000")
    )
    assert resolved.lot_size == 200
    assert resolved.t_plus_days == 0
    assert fees.commission == Decimal("5.00")
    assert fees.transaction_levy == Decimal("0.27")
    assert fees.trading_fee == Decimal("0.57")
    assert fees.settlement_fee == Decimal("0.20")
    assert fees.total == Decimal("6.04")


def test_us_integer_shares_and_sell_sec_fee_are_hand_calculated():
    service = DatedMarketRuleService()
    resolved = service.resolve(
        version(
            Market.US,
            {
                "fees": {
                    "commission_per_share": "0.005",
                    "minimum_commission": "1",
                    "sec_fee_rate": "0.000008",
                    "minimum_sec_fee": "0.01",
                }
            },
        ),
        context(Market.US, "AAPL"),
        trade_date=TRADE_DATE,
        as_of=AS_OF,
    )

    fees = service.calculate_fees(
        resolved, OrderSide.SELL, quantity=100, notional=Decimal("10000")
    )
    assert resolved.lot_size == 1
    assert resolved.integer_shares is True
    assert fees.commission == Decimal("1.00")
    assert fees.sec_fee == Decimal("0.08")
    assert fees.total == Decimal("1.08")


def test_t1_uses_explicit_lot_availability_and_odd_lot_only_for_liquidation():
    service = DatedMarketRuleService()
    rules = service.resolve(
        version(
            Market.CN,
            {"lot_size": 100, "t_plus": 1, "price_limit_pct": "0.10"},
        ),
        context(Market.CN, "600000"),
        trade_date=TRADE_DATE,
        as_of=AS_OF,
    )
    lots = (
        PositionLot(
            lot_id="old",
            market=Market.CN,
            symbol="600000",
            quantity=100,
            remaining_quantity=100,
            acquired_trade_date=date(2024, 1, 5),
            available_trade_date=TRADE_DATE,
            unit_cost=Decimal("10"),
        ),
        PositionLot(
            lot_id="today",
            market=Market.CN,
            symbol="600000",
            quantity=100,
            remaining_quantity=100,
            acquired_trade_date=TRADE_DATE,
            available_trade_date=date(2024, 1, 9),
            unit_cost=Decimal("10"),
        ),
    )
    assert service.available_sell_quantity(
        lots, market=Market.CN, symbol="600000", trade_date=TRADE_DATE
    ) == 100
    assert service.availability_date(
        rules, trade_date=TRADE_DATE, next_trade_date=date(2024, 1, 9)
    ) == date(2024, 1, 9)
    service.validate_requested_quantity(
        150, OrderSide.SELL, rules, position_quantity=150
    )
    with pytest.raises(ValueError, match="lot_size=100"):
        service.validate_requested_quantity(
            50, OrderSide.SELL, rules, position_quantity=150
        )


def test_unsafe_or_incomplete_rule_versions_fail_closed():
    service = DatedMarketRuleService()
    with pytest.raises(MarketRuleConfigurationError, match="price-limit"):
        service.resolve(
            version(Market.CN, {"lot_size": 100}),
            context(Market.CN, "600000"),
            trade_date=TRADE_DATE,
            as_of=AS_OF,
        )
    with pytest.raises(MarketRuleConfigurationError, match="HK lot_size"):
        service.resolve(
            version(Market.HK, {}),
            context(Market.HK, "00700"),
            trade_date=TRADE_DATE,
            as_of=AS_OF,
        )
    with pytest.raises(MarketRuleConfigurationError, match="participation_rate"):
        service.resolve(
            version(Market.US, {"participation_rate": "0.11"}),
            context(Market.US, "AAPL"),
            trade_date=TRADE_DATE,
            as_of=AS_OF,
        )
    with pytest.raises(MarketRuleConfigurationError, match="not visible"):
        service.resolve(
            version(
                Market.US,
                {},
                published_at=datetime(2024, 2, 1, tzinfo=UTC),
            ),
            context(Market.US, "AAPL"),
            trade_date=TRADE_DATE,
            as_of=AS_OF,
        )

    explicit_limits = service.resolve(
        version(Market.CN, {"lot_size": 100}),
        context(
            Market.CN,
            "600000",
            upper_limit_price=Decimal("11"),
            lower_limit_price=Decimal("9"),
        ),
        trade_date=TRADE_DATE,
        as_of=AS_OF,
    )
    assert explicit_limits.price_limit_pct is None
