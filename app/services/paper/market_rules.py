"""Date-versioned market rules shared by backtests and paper simulation.

The legacy manual API continues to use ``paper.market`` unchanged.  This
module is the stricter deterministic boundary for new simulations.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable, Mapping

from app.models.backtest import (
    FeeBreakdown,
    FeeSchedule,
    MarketRuleVersion,
    OrderSide,
    PositionLot,
    ResolvedMarketRules,
    SecurityRuleContext,
)
from app.models.market_data import DailyBar
from app.models.symbol import Market


MONEY_QUANTUM = Decimal("0.01")


class MarketRuleConfigurationError(ValueError):
    """A dated rule version cannot safely resolve the requested security."""


class DatedMarketRuleService:
    """Resolve immutable rule payloads and perform market-specific checks."""

    def resolve(
        self,
        version: MarketRuleVersion,
        context: SecurityRuleContext,
        *,
        trade_date: date,
        as_of: datetime,
    ) -> ResolvedMarketRules:
        if version.market != context.market:
            raise MarketRuleConfigurationError("market-rule version and security differ")
        if not version.applies_on(trade_date, as_of):
            raise MarketRuleConfigurationError("market-rule version is not visible and effective")
        rules = self._market_payload(version.rules, context.market)
        lot_size = self._lot_size(rules, context)
        price_limit_pct = self._price_limit_pct(rules, context)
        if (
            context.market == Market.CN
            and price_limit_pct is None
            and context.upper_limit_price is None
        ):
            raise MarketRuleConfigurationError(
                "CN rules require a dated price-limit percentage"
            )
        participation_rate = _decimal(
            rules.get("participation_rate", rules.get("max_participation_rate", "0.10")),
            "participation_rate",
        )
        if participation_rate <= 0 or participation_rate > Decimal("0.10"):
            raise MarketRuleConfigurationError(
                "participation_rate must be in (0, 0.10] for first-version simulations"
            )
        price_tick = _decimal(rules.get("price_tick", "0.01"), "price_tick")
        if price_tick <= 0:
            raise MarketRuleConfigurationError("price_tick must be positive")
        t_plus_days = _integer(
            rules.get("t_plus_days", rules.get("t_plus", 1 if context.market == Market.CN else 0)),
            "t_plus_days",
        )
        if t_plus_days not in (0, 1):
            raise MarketRuleConfigurationError(
                "first-version simulation supports only T+0 or T+1"
            )
        return ResolvedMarketRules(
            rule_version_id=version.rule_version_id,
            market=context.market,
            symbol=context.symbol,
            trade_date=trade_date,
            lot_size=lot_size,
            integer_shares=True,
            t_plus_days=t_plus_days,
            participation_rate=participation_rate,
            price_tick=price_tick,
            price_limit_pct=price_limit_pct,
            strict_locked_limit=_boolean(
                rules.get("strict_locked_limit", True), "strict_locked_limit"
            ),
            fee_schedule=self._fee_schedule(rules),
        )

    @staticmethod
    def _market_payload(payload: Mapping[str, Any], market: Market) -> dict[str, Any]:
        markets = payload.get("markets")
        if isinstance(markets, Mapping):
            selected = markets.get(market.value)
            if selected is None:
                selected = markets.get(market.value.lower())
            if selected is None:
                raise MarketRuleConfigurationError(
                    f"rule payload has no {market.value} configuration"
                )
            if not isinstance(selected, Mapping):
                raise MarketRuleConfigurationError("market rule configuration must be an object")
            return dict(selected)
        return dict(payload)

    @staticmethod
    def _lot_size(rules: Mapping[str, Any], context: SecurityRuleContext) -> int:
        if context.lot_size is not None:
            lot_size = context.lot_size
        else:
            symbol_lots = rules.get("symbol_lot_sizes", {})
            lot_size = symbol_lots.get(context.symbol) if isinstance(symbol_lots, Mapping) else None
            if lot_size is None:
                lot_size = rules.get("lot_size")
        if lot_size is None:
            if context.market == Market.CN:
                lot_size = 100
            elif context.market == Market.US:
                lot_size = 1
            else:
                raise MarketRuleConfigurationError(
                    "HK lot_size must come from dated rules or security metadata"
                )
        if isinstance(lot_size, bool) or int(lot_size) != lot_size or int(lot_size) <= 0:
            raise MarketRuleConfigurationError("lot_size must be a positive integer")
        return int(lot_size)

    @staticmethod
    def _price_limit_pct(
        rules: Mapping[str, Any], context: SecurityRuleContext
    ) -> Decimal | None:
        if context.upper_limit_price is not None or context.lower_limit_price is not None:
            return None
        config = rules.get("price_limits", {})
        if config is None:
            config = {}
        if not isinstance(config, Mapping):
            raise MarketRuleConfigurationError("price_limits must be an object")
        value: Any = None
        if context.is_st:
            value = config.get("st", rules.get("st_price_limit_pct"))
        if value is None and context.board is not None:
            boards = config.get("boards", rules.get("board_price_limit_pcts", {}))
            if isinstance(boards, Mapping):
                value = boards.get(context.board)
                if value is None:
                    value = boards.get(context.board.upper())
        if value is None:
            value = config.get("default", rules.get("price_limit_pct"))
        if value is None:
            return None
        result = _decimal(value, "price_limit_pct")
        if result <= 0 or result >= 1:
            raise MarketRuleConfigurationError(
                "price-limit percentages must be decimal fractions between 0 and 1"
            )
        return result

    @staticmethod
    def _fee_schedule(rules: Mapping[str, Any]) -> FeeSchedule:
        raw = rules.get("fees", rules.get("commission", {}))
        if raw is None:
            raw = {}
        if not isinstance(raw, Mapping):
            raise MarketRuleConfigurationError("fee schedule must be an object")

        def rate(*names: str, default: str = "0") -> Decimal:
            for name in names:
                if name in raw:
                    return _decimal(raw[name], name)
            return Decimal(default)

        return FeeSchedule(
            commission_rate=rate("commission_rate", "rate"),
            commission_per_share=rate("commission_per_share", "per_share"),
            minimum_commission=rate("minimum_commission", "min"),
            stamp_duty_rate=rate("stamp_duty_rate", "stamp_tax_rate"),
            transfer_fee_rate=rate("transfer_fee_rate"),
            transaction_levy_rate=rate("transaction_levy_rate"),
            trading_fee_rate=rate("trading_fee_rate"),
            settlement_fee_rate=rate("settlement_fee_rate"),
            sec_fee_rate=rate("sec_fee_rate"),
            minimum_sec_fee=rate("minimum_sec_fee"),
            other_rate=rate("other_rate"),
        )

    @staticmethod
    def validate_requested_quantity(
        quantity: int,
        side: OrderSide,
        rules: ResolvedMarketRules,
        *,
        position_quantity: int = 0,
    ) -> None:
        if isinstance(quantity, bool) or quantity <= 0:
            raise ValueError("order quantity must be a positive integer")
        if quantity % rules.lot_size == 0:
            return
        if side == OrderSide.SELL and quantity == position_quantity:
            return
        raise ValueError(
            f"quantity must be a multiple of lot_size={rules.lot_size}; "
            "only full-position liquidation may sell an odd lot"
        )

    @staticmethod
    def executable_quantity(
        candidate: int,
        side: OrderSide,
        rules: ResolvedMarketRules,
        *,
        remaining_order_quantity: int,
        position_quantity: int = 0,
    ) -> int:
        if isinstance(candidate, bool) or not isinstance(candidate, int):
            raise ValueError("candidate quantity must be an integer")
        candidate = max(0, min(candidate, remaining_order_quantity))
        if (
            side == OrderSide.SELL
            and remaining_order_quantity == position_quantity
            and candidate >= remaining_order_quantity
        ):
            return remaining_order_quantity
        return candidate - candidate % rules.lot_size

    @staticmethod
    def available_sell_quantity(
        lots: Iterable[PositionLot],
        *,
        market: Market,
        symbol: str,
        trade_date: date,
    ) -> int:
        total = 0
        lot_ids: set[str] = set()
        for lot in lots:
            if lot.market != market or lot.symbol != symbol:
                raise ValueError("position lot identity does not match order")
            if lot.lot_id in lot_ids:
                raise ValueError("position lots contain a duplicate lot_id")
            lot_ids.add(lot.lot_id)
            if lot.available_trade_date <= trade_date:
                total += lot.remaining_quantity
        return total

    @staticmethod
    def availability_date(
        rules: ResolvedMarketRules,
        *,
        trade_date: date,
        next_trade_date: date | None = None,
    ) -> date:
        if rules.t_plus_days == 0:
            return trade_date
        if rules.t_plus_days != 1:
            raise MarketRuleConfigurationError(
                "first-version simulation supports only T+0 or T+1"
            )
        if next_trade_date is None or next_trade_date <= trade_date:
            raise ValueError("T+1 availability requires the next trading date")
        return next_trade_date

    @staticmethod
    def locked_limit_reason(
        side: OrderSide,
        bar: DailyBar,
        context: SecurityRuleContext,
        rules: ResolvedMarketRules,
    ) -> str | None:
        if not rules.strict_locked_limit or context.market != Market.CN:
            return None
        upper, lower = DatedMarketRuleService.price_limit_bounds(bar, context, rules)
        tolerance = rules.price_tick / 2
        if side == OrderSide.BUY:
            if bar.low is None:
                raise ValueError("buy limit validation requires daily low")
            if _decimal(bar.low, "low") >= upper - tolerance:
                return "BUY_LOCKED_AT_UPPER_LIMIT"
        else:
            if bar.high is None:
                raise ValueError("sell limit validation requires daily high")
            if _decimal(bar.high, "high") <= lower + tolerance:
                return "SELL_LOCKED_AT_LOWER_LIMIT"
        return None

    @staticmethod
    def execution_price_limit_reason(
        side: OrderSide,
        execution_price: Decimal,
        bar: DailyBar,
        context: SecurityRuleContext,
        rules: ResolvedMarketRules,
    ) -> str | None:
        if not rules.strict_locked_limit or context.market != Market.CN:
            return None
        upper, lower = DatedMarketRuleService.price_limit_bounds(bar, context, rules)
        tolerance = rules.price_tick / 2
        if side == OrderSide.BUY and execution_price >= upper - tolerance:
            return "BUY_AT_UPPER_LIMIT"
        if side == OrderSide.SELL and execution_price <= lower + tolerance:
            return "SELL_AT_LOWER_LIMIT"
        return None

    @staticmethod
    def price_limit_bounds(
        bar: DailyBar,
        context: SecurityRuleContext,
        rules: ResolvedMarketRules,
    ) -> tuple[Decimal, Decimal]:
        upper = context.upper_limit_price
        lower = context.lower_limit_price
        if upper is not None and lower is not None:
            return upper, lower
        if bar.pre_close is None or rules.price_limit_pct is None:
            raise MarketRuleConfigurationError(
                "CN limit validation requires pre_close and a dated price limit"
            )
        pre_close = _decimal(bar.pre_close, "pre_close")
        if pre_close <= 0:
            raise MarketRuleConfigurationError("pre_close must be positive")
        return (
            _round_tick(pre_close * (1 + rules.price_limit_pct), rules.price_tick),
            _round_tick(pre_close * (1 - rules.price_limit_pct), rules.price_tick),
        )

    @staticmethod
    def calculate_fees(
        rules: ResolvedMarketRules,
        side: OrderSide,
        *,
        quantity: int,
        notional: Decimal,
    ) -> FeeBreakdown:
        if isinstance(quantity, bool) or quantity <= 0:
            raise ValueError("fee quantity must be a positive integer")
        if not notional.is_finite() or notional <= 0:
            raise ValueError("fee notional must be finite and positive")
        schedule = rules.fee_schedule
        base_commission = (
            notional * schedule.commission_rate
            + Decimal(quantity) * schedule.commission_per_share
        )
        commission = max(base_commission, schedule.minimum_commission)
        stamp = (
            notional * schedule.stamp_duty_rate
            if rules.market == Market.CN and side == OrderSide.SELL
            else Decimal("0")
        )
        transfer = (
            notional * schedule.transfer_fee_rate
            if rules.market == Market.CN
            else Decimal("0")
        )
        levy = (
            notional * schedule.transaction_levy_rate
            if rules.market == Market.HK
            else Decimal("0")
        )
        trading = (
            notional * schedule.trading_fee_rate
            if rules.market == Market.HK
            else Decimal("0")
        )
        settlement = (
            notional * schedule.settlement_fee_rate
            if rules.market == Market.HK
            else Decimal("0")
        )
        sec_raw = (
            notional * schedule.sec_fee_rate
            if rules.market == Market.US and side == OrderSide.SELL
            else Decimal("0")
        )
        sec_fee = (
            max(sec_raw, schedule.minimum_sec_fee)
            if sec_raw > 0
            else Decimal("0")
        )
        other = notional * schedule.other_rate
        return FeeBreakdown(
            commission=_money(commission),
            stamp_duty=_money(stamp),
            transfer_fee=_money(transfer),
            transaction_levy=_money(levy),
            trading_fee=_money(trading),
            settlement_fee=_money(settlement),
            sec_fee=_money(sec_fee),
            other=_money(other),
        )


# General name for later paper and backtest callers.
MarketRuleService = DatedMarketRuleService


def _decimal(value: Any, name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (ValueError, TypeError) as exc:
        raise MarketRuleConfigurationError(f"{name} must be numeric") from exc
    if not result.is_finite():
        raise MarketRuleConfigurationError(f"{name} must be finite")
    return result


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _round_tick(value: Decimal, tick: Decimal) -> Decimal:
    steps = (value / tick).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return steps * tick


def _integer(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise MarketRuleConfigurationError(f"{name} must be an integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise MarketRuleConfigurationError(f"{name} must be an integer") from exc
    if result != value:
        raise MarketRuleConfigurationError(f"{name} must be an integer")
    return result


def _boolean(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise MarketRuleConfigurationError(f"{name} must be boolean")
    return value
