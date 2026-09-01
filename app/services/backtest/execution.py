"""Deterministic price, slippage, and exit-trigger calculations."""

from __future__ import annotations

from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, localcontext

from app.models.backtest import (
    BrokerOrder,
    ExecutionPriceModel,
    ExitDecision,
    ExitReason,
    ExitRuleConfig,
    OrderSide,
    ResolvedMarketRules,
    SameBarConflictMode,
    SignalConflictDecision,
    SlippageModel,
    finite_decimal,
)
from app.models.market_data import DailyBar


class ExecutionPriceService:
    """Select an unadjusted execution reference from a daily bar."""

    @staticmethod
    def raw_price(order: BrokerOrder, bar: DailyBar) -> tuple[Decimal, tuple[str, ...]]:
        if bar.trade_date <= order.created_trade_date:
            raise ValueError("daily-close signals cannot execute on the same or an earlier date")
        low = finite_decimal(_required(bar.low, "low"))
        high = finite_decimal(_required(bar.high, "high"))
        if high < low:
            raise ValueError("daily high cannot be below daily low")
        if order.execution_model == ExecutionPriceModel.NEXT_OPEN:
            price = finite_decimal(_required(bar.open, "open"))
            if not low <= price <= high:
                raise ValueError("daily open is outside low..high")
            return price, ()
        if order.execution_model == ExecutionPriceModel.NEXT_CLOSE:
            price = finite_decimal(_required(bar.close, "close"))
            if not low <= price <= high:
                raise ValueError("daily close is outside low..high")
            return price, ()

        volume = finite_decimal(_required(bar.volume, "volume"))
        warnings = ["VWAP_PROXY_RESEARCH_ONLY"]
        if bar.amount is not None and bar.amount > 0:
            price = finite_decimal(bar.amount) / volume
        else:
            values = tuple(
                finite_decimal(_required(value, name))
                for value, name in (
                    (bar.open, "open"),
                    (bar.high, "high"),
                    (bar.low, "low"),
                    (bar.close, "close"),
                )
            )
            price = sum(values, Decimal("0")) / Decimal("4")
            warnings.append("VWAP_PROXY_OHLC4_FALLBACK")
        clipped = min(max(price, low), high)
        if clipped != price:
            warnings.append("VWAP_PROXY_CLIPPED_TO_DAILY_RANGE")
        price = clipped
        return price, tuple(warnings)


class SlippageService:
    """Apply adverse deterministic slippage and clip to observed OHLC."""

    @staticmethod
    def apply(
        order: BrokerOrder,
        bar: DailyBar,
        raw_price: Decimal,
        *,
        quantity: int,
        rules: ResolvedMarketRules,
    ) -> tuple[Decimal, Decimal, tuple[str, ...]]:
        config = order.slippage
        if config.model == SlippageModel.FIXED_BPS:
            bps = config.fixed_bps
        else:
            daily_amount = finite_decimal(_required(bar.amount, "daily amount"))
            raw_notional = raw_price * quantity
            with localcontext() as context:
                context.prec = 34
                participation = raw_notional / daily_amount
                bps = config.base_bps + config.impact_coefficient * participation.sqrt()
        if bps >= Decimal("10000"):
            raise ValueError("slippage must remain below 10000 bps")
        direction = Decimal("1") if order.side == OrderSide.BUY else Decimal("-1")
        theoretical = raw_price * (Decimal("1") + direction * bps / Decimal("10000"))
        rounded = _adverse_tick(theoretical, rules.price_tick, order.side)
        low = finite_decimal(_required(bar.low, "low"))
        high = finite_decimal(_required(bar.high, "high"))
        if high < low:
            raise ValueError("daily high cannot be below daily low")
        warnings: list[str] = []
        fill_price = min(max(rounded, low), high)
        if fill_price != rounded:
            warnings.append("SLIPPAGE_CLIPPED_TO_DAILY_RANGE")
        return fill_price, fill_price - raw_price, tuple(warnings)


class ExitRuleService:
    """Evaluate long-only OHLC exits without inferring intraday data."""

    @classmethod
    def evaluate(
        cls,
        bar: DailyBar,
        *,
        average_cost: Decimal,
        highest_observed_price: Decimal,
        holding_days: int,
        config: ExitRuleConfig,
        entry_atr: Decimal | None = None,
        current_atr: Decimal | None = None,
        signal_exit: bool = False,
        portfolio_drawdown_liquidation: bool = False,
    ) -> ExitDecision:
        if average_cost <= 0 or highest_observed_price <= 0:
            raise ValueError("exit evaluation requires positive cost and high watermark")
        if holding_days < 0:
            raise ValueError("holding_days cannot be negative")
        open_price = finite_decimal(_required(bar.open, "open"))
        high = finite_decimal(_required(bar.high, "high"))
        low = finite_decimal(_required(bar.low, "low"))
        close = finite_decimal(_required(bar.close, "close"))
        if not low <= min(open_price, close) <= max(open_price, close) <= high:
            raise ValueError("daily OHLC values are inconsistent")

        stop_candidates: list[tuple[Decimal, ExitReason]] = []
        if config.fixed_stop_loss_pct is not None:
            stop_candidates.append(
                (
                    average_cost * (1 - config.fixed_stop_loss_pct),
                    ExitReason.FIXED_STOP_LOSS,
                )
            )
        if config.atr_stop_multiple is not None:
            if entry_atr is None or entry_atr <= 0:
                raise ValueError("ATR stop requires a positive entry_atr")
            stop_candidates.append(
                (
                    average_cost - config.atr_stop_multiple * entry_atr,
                    ExitReason.ATR_STOP,
                )
            )
        if config.trailing_stop_pct is not None:
            stop_candidates.append(
                (
                    highest_observed_price * (1 - config.trailing_stop_pct),
                    ExitReason.TRAILING_STOP,
                )
            )
        if config.trailing_atr_multiple is not None:
            if current_atr is None or current_atr <= 0:
                raise ValueError("ATR trailing stop requires a positive current_atr")
            stop_candidates.append(
                (
                    highest_observed_price - config.trailing_atr_multiple * current_atr,
                    ExitReason.TRAILING_STOP,
                )
            )
        stop_candidates = [item for item in stop_candidates if item[0] > 0]
        stop = max(stop_candidates, key=lambda item: (item[0], item[1].value), default=None)
        take_price = (
            average_cost * (1 + config.fixed_take_profit_pct)
            if config.fixed_take_profit_pct is not None
            else None
        )
        stop_hit = stop is not None and low <= stop[0]
        take_hit = take_price is not None and high >= take_price
        if stop_hit and take_hit:
            return cls.resolve_same_bar_conflict(
                open_price=open_price,
                stop_price=stop[0],
                stop_reason=stop[1],
                take_price=take_price,
                mode=config.conflict_mode,
            )
        if stop_hit and stop is not None:
            return ExitDecision(
                triggered=True,
                reason=stop[1],
                trigger_price=min(open_price, stop[0]),
            )
        if take_hit and take_price is not None:
            return ExitDecision(
                triggered=True,
                reason=ExitReason.FIXED_TAKE_PROFIT,
                trigger_price=max(open_price, take_price),
            )
        # Close-observable exits are evaluated only after intraday price exits.
        if portfolio_drawdown_liquidation:
            return ExitDecision(
                triggered=True,
                reason=ExitReason.PORTFOLIO_DRAWDOWN,
                trigger_price=close,
            )
        if signal_exit:
            return ExitDecision(
                triggered=True,
                reason=ExitReason.SIGNAL_EXIT,
                trigger_price=close,
            )
        if (
            config.maximum_holding_days is not None
            and holding_days >= config.maximum_holding_days
        ):
            return ExitDecision(
                triggered=True,
                reason=ExitReason.TIME_EXIT,
                trigger_price=close,
            )
        return ExitDecision(triggered=False)

    @staticmethod
    def resolve_same_bar_conflict(
        *,
        open_price: Decimal,
        stop_price: Decimal,
        stop_reason: ExitReason,
        take_price: Decimal,
        mode: SameBarConflictMode,
    ) -> ExitDecision:
        if not (open_price > 0 and stop_price > 0 and take_price > stop_price):
            raise ValueError("same-bar conflict prices are invalid")
        warning = f"SAME_BAR_EXIT_CONFLICT:{mode.value}"
        if mode == SameBarConflictMode.CONSERVATIVE:
            return ExitDecision(
                triggered=True,
                reason=stop_reason,
                trigger_price=min(open_price, stop_price),
                same_bar_conflict=True,
                assumption_warning=warning,
            )
        if mode == SameBarConflictMode.OPTIMISTIC:
            return ExitDecision(
                triggered=True,
                reason=ExitReason.FIXED_TAKE_PROFIT,
                trigger_price=max(open_price, take_price),
                same_bar_conflict=True,
                assumption_warning=warning,
                research_only_assumption=True,
            )
        if open_price <= stop_price:
            reason, price = stop_reason, open_price
        elif open_price >= take_price:
            reason, price = ExitReason.FIXED_TAKE_PROFIT, open_price
        elif open_price - stop_price <= take_price - open_price:
            reason, price = stop_reason, stop_price
        else:
            reason, price = ExitReason.FIXED_TAKE_PROFIT, take_price
        return ExitDecision(
            triggered=True,
            reason=reason,
            trigger_price=price,
            same_bar_conflict=True,
            assumption_warning=warning,
            research_only_assumption=True,
        )

    @staticmethod
    def resolve_signal_priority(
        *,
        exit_decision: ExitDecision,
        buy_signal: bool,
        cooldown_active: bool,
    ) -> SignalConflictDecision:
        if exit_decision.triggered:
            return SignalConflictDecision(
                exit_selected=True,
                buy_allowed=False,
                reason="EXIT_PRIORITY",
            )
        if cooldown_active:
            return SignalConflictDecision(
                exit_selected=False,
                buy_allowed=False,
                reason="COOLDOWN_ACTIVE",
            )
        return SignalConflictDecision(
            exit_selected=False,
            buy_allowed=buy_signal,
            reason="BUY_SIGNAL" if buy_signal else "NO_ACTION",
        )


ExecutionService = ExecutionPriceService


def _required(value: float | None, name: str) -> float:
    if value is None:
        raise ValueError(f"execution requires daily {name}")
    return value


def _adverse_tick(value: Decimal, tick: Decimal, side: OrderSide) -> Decimal:
    rounding = ROUND_CEILING if side == OrderSide.BUY else ROUND_FLOOR
    steps = (value / tick).quantize(Decimal("1"), rounding=rounding)
    return steps * tick
