"""Long-only cash and FIFO position state for deterministic backtests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

from app.models.backtest import (
    BrokerFill,
    CorporateAction,
    CorporateActionType,
    OrderSide,
    PositionLot,
)
from app.models.symbol import Market


MONEY_QUANTUM = Decimal("0.01")


class PortfolioReconciliationError(RuntimeError):
    """Cash, lots, or valuation fail a conservation invariant."""


class InsufficientCash(PortfolioReconciliationError):
    pass


class InsufficientAvailablePosition(PortfolioReconciliationError):
    pass


class PortfolioState:
    def __init__(
        self,
        *,
        market: Market,
        initial_cash: Decimal,
        cash: Decimal | None = None,
        lots: Iterable[PositionLot] = (),
        realized_pnl: Decimal = Decimal("0"),
        total_fees: Decimal = Decimal("0"),
    ):
        if not initial_cash.is_finite() or initial_cash <= 0:
            raise ValueError("initial_cash must be finite and positive")
        self.market = market
        self.initial_cash = _money(initial_cash)
        if self.initial_cash <= 0:
            raise ValueError("initial_cash is below currency precision")
        self.cash = _money(initial_cash if cash is None else cash)
        if self.cash < 0:
            raise ValueError("cash cannot be negative")
        self.realized_pnl = _money(realized_pnl)
        self.total_fees = _money(total_fees)
        self._lots: dict[str, list[PositionLot]] = {}
        seen: set[str] = set()
        for lot in lots:
            if lot.market != market:
                raise ValueError("position lot market differs from portfolio")
            if lot.lot_id in seen:
                raise ValueError("portfolio contains a duplicate lot_id")
            seen.add(lot.lot_id)
            self._lots.setdefault(lot.symbol, []).append(lot)
        self._sort_lots()

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(sorted(symbol for symbol, lots in self._lots.items() if lots))

    def lots_for(self, symbol: str) -> tuple[PositionLot, ...]:
        return tuple(self._lots.get(symbol, ()))

    def quantity(self, symbol: str) -> int:
        return sum(item.remaining_quantity for item in self._lots.get(symbol, ()))

    def available_quantity(self, symbol: str, trade_date: date) -> int:
        return sum(
            item.remaining_quantity
            for item in self._lots.get(symbol, ())
            if item.available_trade_date <= trade_date
        )

    def average_cost(self, symbol: str) -> Decimal:
        lots = self._lots.get(symbol, ())
        quantity = sum(item.remaining_quantity for item in lots)
        if quantity <= 0:
            raise KeyError(f"no position for {symbol}")
        cost = sum(
            (item.unit_cost * item.remaining_quantity for item in lots),
            Decimal("0"),
        )
        return cost / quantity

    def apply_fill(
        self,
        fill: BrokerFill,
        *,
        trade_id: str,
        available_trade_date: date,
    ) -> Decimal | None:
        if fill.market != self.market:
            raise ValueError("fill market differs from portfolio")
        if fill.side == OrderSide.BUY:
            total_cost = fill.notional + fill.fees.total
            if total_cost > self.cash:
                raise InsufficientCash("fill cost exceeds available cash")
            unit_cost = total_cost / fill.quantity
            self.cash = _money(self.cash - total_cost)
            self.total_fees = _money(self.total_fees + fill.fees.total)
            self._lots.setdefault(fill.symbol, []).append(
                PositionLot(
                    lot_id=f"lot:{trade_id}",
                    market=fill.market,
                    symbol=fill.symbol,
                    quantity=fill.quantity,
                    remaining_quantity=fill.quantity,
                    acquired_trade_date=fill.trade_date,
                    available_trade_date=available_trade_date,
                    unit_cost=unit_cost,
                )
            )
            self._sort_lots()
            return None

        available = self.available_quantity(fill.symbol, fill.trade_date)
        if fill.quantity > available:
            raise InsufficientAvailablePosition(
                "sell fill exceeds settled available quantity"
            )
        remaining = fill.quantity
        cost_basis = Decimal("0")
        updated: list[PositionLot] = []
        for lot in self._lots.get(fill.symbol, ()):
            if remaining and lot.available_trade_date <= fill.trade_date:
                consumed = min(remaining, lot.remaining_quantity)
                cost_basis += lot.unit_cost * consumed
                remaining -= consumed
                lot_remaining = lot.remaining_quantity - consumed
                if lot_remaining:
                    updated.append(
                        lot.model_copy(update={"remaining_quantity": lot_remaining})
                    )
            else:
                updated.append(lot)
        if remaining:
            raise PortfolioReconciliationError("FIFO consumption did not satisfy sell")
        if updated:
            self._lots[fill.symbol] = updated
        else:
            self._lots.pop(fill.symbol, None)
        proceeds = fill.notional - fill.fees.total
        realized = proceeds - cost_basis
        self.cash = _money(self.cash + proceeds)
        self.total_fees = _money(self.total_fees + fill.fees.total)
        self.realized_pnl = _money(self.realized_pnl + realized)
        return realized

    def apply_corporate_action(self, action: CorporateAction) -> dict[str, Decimal | int]:
        if action.market != self.market:
            raise ValueError("corporate action market differs from portfolio")
        quantity = self.quantity(action.symbol)
        if quantity == 0:
            return {"quantity_before": 0, "quantity_after": 0, "cash_delta": Decimal("0")}
        if action.action_type == CorporateActionType.CASH_DIVIDEND:
            cash_delta = _money(action.cash_per_share * quantity)
            self.cash = _money(self.cash + cash_delta)
            return {
                "quantity_before": quantity,
                "quantity_after": quantity,
                "cash_delta": cash_delta,
            }
        updated: list[PositionLot] = []
        for lot in self._lots[action.symbol]:
            original = Decimal(lot.quantity) * action.share_multiplier
            remaining = Decimal(lot.remaining_quantity) * action.share_multiplier
            if original != original.to_integral_value() or remaining != remaining.to_integral_value():
                raise PortfolioReconciliationError(
                    "corporate action produces fractional shares without cash-in-lieu data"
                )
            updated.append(
                lot.model_copy(
                    update={
                        "quantity": int(original),
                        "remaining_quantity": int(remaining),
                        "unit_cost": lot.unit_cost / action.share_multiplier,
                    }
                )
            )
        self._lots[action.symbol] = updated
        return {
            "quantity_before": quantity,
            "quantity_after": self.quantity(action.symbol),
            "cash_delta": Decimal("0"),
        }

    def market_values(self, prices: dict[str, Decimal]) -> dict[str, Decimal]:
        missing = set(self.symbols) - set(prices)
        if missing:
            raise PortfolioReconciliationError(
                f"missing valuation prices for {sorted(missing)}"
            )
        return {
            symbol: _money(prices[symbol] * self.quantity(symbol))
            for symbol in self.symbols
        }

    def equity(self, prices: dict[str, Decimal]) -> Decimal:
        values = self.market_values(prices)
        return _money(self.cash + sum(values.values(), Decimal("0")))

    def to_snapshot(self) -> dict:
        return {
            "market": self.market.value,
            "initial_cash": str(self.initial_cash),
            "cash": str(self.cash),
            "realized_pnl": str(self.realized_pnl),
            "total_fees": str(self.total_fees),
            "lots": [
                item.model_dump(mode="json")
                for symbol in self.symbols
                for item in self._lots[symbol]
            ],
        }

    @classmethod
    def from_snapshot(cls, value: dict) -> "PortfolioState":
        return cls(
            market=Market(value["market"]),
            initial_cash=Decimal(value["initial_cash"]),
            cash=Decimal(value["cash"]),
            realized_pnl=Decimal(value.get("realized_pnl", "0")),
            total_fees=Decimal(value.get("total_fees", "0")),
            lots=(PositionLot.model_validate(item) for item in value.get("lots", ())),
        )

    def _sort_lots(self) -> None:
        for lots in self._lots.values():
            lots.sort(key=lambda item: (item.acquired_trade_date, item.lot_id))


def _money(value: Decimal) -> Decimal:
    if not value.is_finite():
        raise PortfolioReconciliationError("money value must be finite")
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
