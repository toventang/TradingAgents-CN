"""Reusable deterministic simulated broker for one daily execution attempt."""

from __future__ import annotations

from decimal import Decimal, ROUND_FLOOR
from typing import Iterable

from app.models.backtest import (
    BrokerExecutionResult,
    BrokerFill,
    BrokerOrder,
    BrokerOrderStatus,
    OrderSide,
    PositionLot,
    ResolvedMarketRules,
    SecurityRuleContext,
)
from app.models.market_data import DailyBar
from app.services.backtest.execution import ExecutionPriceService, SlippageService
from app.services.paper.market_rules import DatedMarketRuleService


class SimulatedBroker:
    """Execute an existing order against exactly one unadjusted daily bar.

    The broker calculates fills and fees but owns no cash, position, or ledger
    state.  J32 applies the returned immutable result transactionally.
    """

    def __init__(
        self,
        *,
        market_rules: DatedMarketRuleService | None = None,
        prices: type[ExecutionPriceService] = ExecutionPriceService,
        slippage: type[SlippageService] = SlippageService,
    ):
        self._market_rules = market_rules or DatedMarketRuleService()
        self._prices = prices
        self._slippage = slippage

    def execute(
        self,
        order: BrokerOrder,
        bar: DailyBar,
        context: SecurityRuleContext,
        rules: ResolvedMarketRules,
        *,
        position_lots: Iterable[PositionLot] = (),
        position_quantity: int | None = None,
    ) -> BrokerExecutionResult:
        if order.status not in {
            BrokerOrderStatus.PENDING,
            BrokerOrderStatus.PARTIALLY_FILLED,
        }:
            raise ValueError("only pending or partially-filled orders can execute")
        if bar.market != order.market or bar.symbol != order.symbol:
            raise ValueError("daily bar identity does not match order")
        if context.market != order.market or context.symbol != order.symbol:
            raise ValueError("security rule context does not match order")
        if rules.market != order.market or rules.symbol != order.symbol:
            raise ValueError("resolved market rules do not match order")
        if rules.trade_date != bar.trade_date:
            raise ValueError("resolved market rules do not match bar date")
        if order.execution_attempts >= order.maximum_execution_days:
            return self._no_fill(
                order,
                bar,
                BrokerOrderStatus.EXPIRED,
                "MAXIMUM_EXECUTION_DAYS_REACHED",
                execution_attempts=order.execution_attempts,
            )
        if bar.trade_date > order.expires_on:
            return self._no_fill(
                order,
                bar,
                BrokerOrderStatus.EXPIRED,
                "ORDER_EXPIRED",
                execution_attempts=order.execution_attempts,
            )
        if bar.trade_date <= order.created_trade_date:
            return self._no_fill(
                order,
                bar,
                BrokerOrderStatus.REJECTED,
                "SAME_DAY_EXECUTION_FORBIDDEN",
                execution_attempts=order.execution_attempts,
            )
        attempt_number = order.execution_attempts + 1
        if bar.suspended:
            return self._defer(order, bar, "SUSPENDED", attempt_number)

        lots = tuple(position_lots)
        lot_total = sum(item.remaining_quantity for item in lots)
        if position_quantity is None:
            position_quantity = lot_total
        if position_quantity < 0:
            raise ValueError("position_quantity cannot be negative")
        if lots and position_quantity != lot_total:
            raise ValueError("position_quantity does not reconcile with position lots")
        try:
            self._market_rules.validate_requested_quantity(
                order.remaining_quantity,
                order.side,
                rules,
                position_quantity=position_quantity,
            )
            limit_reason = self._market_rules.locked_limit_reason(
                order.side, bar, context, rules
            )
        except ValueError as exc:
            return self._no_fill(
                order,
                bar,
                BrokerOrderStatus.REJECTED,
                f"INVALID_MARKET_RULE_OR_ORDER:{exc}",
                execution_attempts=attempt_number,
            )
        if limit_reason is not None:
            return self._defer(order, bar, limit_reason, attempt_number)
        if bar.volume is None or bar.volume <= 0:
            return self._no_fill(
                order,
                bar,
                BrokerOrderStatus.REJECTED,
                "INVALID_OR_MISSING_VOLUME",
                execution_attempts=attempt_number,
            )

        participation_cap = int(
            (Decimal(str(bar.volume)) * rules.participation_rate).to_integral_value(
                rounding=ROUND_FLOOR
            )
        )
        candidate = min(order.remaining_quantity, participation_cap)
        constraints: list[str] = []
        if participation_cap < order.remaining_quantity:
            constraints.append("PARTICIPATION_LIMIT")
        if order.side == OrderSide.SELL:
            if rules.t_plus_days > 0 and not lots and position_quantity > 0:
                return self._no_fill(
                    order,
                    bar,
                    BrokerOrderStatus.REJECTED,
                    "SETTLEMENT_LOTS_REQUIRED",
                    execution_attempts=attempt_number,
                )
            available = (
                self._market_rules.available_sell_quantity(
                    lots,
                    market=order.market,
                    symbol=order.symbol,
                    trade_date=bar.trade_date,
                )
                if lots
                else position_quantity
            )
            if available < candidate:
                constraints.append("T_PLUS_ONE_OR_POSITION_UNAVAILABLE")
            candidate = min(candidate, available)
        fill_quantity = self._market_rules.executable_quantity(
            candidate,
            order.side,
            rules,
            remaining_order_quantity=order.remaining_quantity,
            position_quantity=position_quantity,
        )
        if fill_quantity <= 0:
            return self._defer(
                order,
                bar,
                constraints[-1] if constraints else "BELOW_MINIMUM_LOT",
                attempt_number,
            )

        try:
            raw_price, price_warnings = self._prices.raw_price(order, bar)
            execution_limit_reason = self._market_rules.execution_price_limit_reason(
                order.side, raw_price, bar, context, rules
            )
            if execution_limit_reason is not None:
                return self._defer(
                    order, bar, execution_limit_reason, attempt_number
                )
            fill_price, slippage_per_share, slippage_warnings = self._slippage.apply(
                order,
                bar,
                raw_price,
                quantity=fill_quantity,
                rules=rules,
            )
            final_limit_reason = self._market_rules.execution_price_limit_reason(
                order.side, fill_price, bar, context, rules
            )
            if final_limit_reason is not None:
                return self._defer(order, bar, final_limit_reason, attempt_number)
        except ValueError as exc:
            return self._no_fill(
                order,
                bar,
                BrokerOrderStatus.REJECTED,
                f"INVALID_EXECUTION_DATA:{exc}",
                execution_attempts=attempt_number,
            )
        notional = fill_price * fill_quantity
        fees = self._market_rules.calculate_fees(
            rules,
            order.side,
            quantity=fill_quantity,
            notional=notional,
        )
        warnings = tuple(dict.fromkeys((*price_warnings, *slippage_warnings, *constraints)))
        fill = BrokerFill(
            order_id=order.order_id,
            market=order.market,
            symbol=order.symbol,
            side=order.side,
            trade_date=bar.trade_date,
            quantity=fill_quantity,
            raw_price=raw_price,
            slippage_per_share=slippage_per_share,
            fill_price=fill_price,
            notional=notional,
            fees=fees,
            warnings=warnings,
        )
        cumulative = order.filled_quantity + fill_quantity
        remaining = order.requested_quantity - cumulative
        if remaining == 0:
            status = BrokerOrderStatus.FILLED
        elif (
            bar.trade_date >= order.expires_on
            or attempt_number >= order.maximum_execution_days
        ):
            status = BrokerOrderStatus.EXPIRED
        else:
            status = BrokerOrderStatus.PARTIALLY_FILLED
        return BrokerExecutionResult(
            order_id=order.order_id,
            trade_date=bar.trade_date,
            status=status,
            requested_quantity=order.requested_quantity,
            cumulative_filled_quantity=cumulative,
            remaining_quantity=remaining,
            execution_attempts=attempt_number,
            fill=fill,
            reason=constraints[0] if remaining and constraints else None,
            warnings=warnings,
        )

    @classmethod
    def _defer(
        cls,
        order: BrokerOrder,
        bar: DailyBar,
        reason: str,
        execution_attempts: int,
    ) -> BrokerExecutionResult:
        status = (
            BrokerOrderStatus.EXPIRED
            if (
                bar.trade_date >= order.expires_on
                or execution_attempts >= order.maximum_execution_days
            )
            else order.status
        )
        return cls._no_fill(
            order,
            bar,
            status,
            reason,
            execution_attempts=execution_attempts,
        )

    @staticmethod
    def _no_fill(
        order: BrokerOrder,
        bar: DailyBar,
        status: BrokerOrderStatus,
        reason: str,
        *,
        execution_attempts: int,
    ) -> BrokerExecutionResult:
        return BrokerExecutionResult(
            order_id=order.order_id,
            trade_date=bar.trade_date,
            status=status,
            requested_quantity=order.requested_quantity,
            cumulative_filled_quantity=order.filled_quantity,
            remaining_quantity=order.remaining_quantity,
            execution_attempts=execution_attempts,
            reason=reason,
        )


BacktestBroker = SimulatedBroker
