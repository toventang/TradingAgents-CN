"""Immediate-fill execution orchestration over legacy paper collections."""

from typing import Optional
from uuid import uuid4

from app.models.paper import PaperExecutionResult, PaperSymbol
from app.services.paper.accounts import MongoPaperAccountService
from app.services.paper.consistency import PaperConsistencyBoundary
from app.services.paper.errors import (
    PaperConsistencyError,
    PaperValidationError,
)
from app.services.paper.market import (
    LegacyImmediateMarketCalendarService,
    MongoPaperMarketRuleService,
)
from app.services.paper.orders import MongoPaperOrderService
from app.services.paper.positions import MongoPaperPositionService
from app.services.paper.prices import MongoPriceSnapshotService


class PaperExecutionService:
    def __init__(
        self,
        *,
        accounts: MongoPaperAccountService,
        market_rules: MongoPaperMarketRuleService,
        calendar: LegacyImmediateMarketCalendarService,
        prices: MongoPriceSnapshotService,
        positions: MongoPaperPositionService,
        orders: MongoPaperOrderService,
        consistency: PaperConsistencyBoundary,
    ):
        self.accounts = accounts
        self.market_rules = market_rules
        self.calendar = calendar
        self.prices = prices
        self.positions = positions
        self.orders = orders
        self.consistency = consistency

    async def execute_market_order(
        self,
        *,
        user_id: str,
        identity: PaperSymbol,
        side: str,
        quantity: int,
        analysis_id: Optional[str] = None,
    ) -> PaperExecutionResult:
        account = await self.accounts.get_or_create(user_id)
        snapshot = await self.prices.get_snapshot(identity)
        if snapshot is None or snapshot.price <= 0:
            raise PaperValidationError(
                f"无法获取股票 {identity.code} "
                f"({identity.market.value}) 的最新价格"
            )
        requested_at = self.accounts.clock()
        execution_at = self.calendar.next_execution_time(
            identity.market,
            requested_at,
        )
        timestamp = execution_at.isoformat()
        price = snapshot.price
        notional = round(price * quantity, 2)
        rules = await self.market_rules.get_rules(identity.market)
        commission = (
            self.market_rules.calculate_commission(
                identity.market,
                side,
                notional,
                rules,
            )
            if rules
            else 0.0
        )
        position = await self.positions.get_position(user_id, identity)
        realized_pnl = 0.0

        if side == "buy":
            available_cash = self.accounts.available_cash(
                account,
                identity.currency,
            )
            total_cost = notional + commission
            if available_cash < total_cost:
                raise PaperValidationError(
                    f"可用{identity.currency.value}不足："
                    f"需要 {total_cost:.2f}，可用 {available_cash:.2f}"
                )
        else:
            available = await self.positions.available_quantity(
                user_id,
                identity,
            )
            if available < quantity:
                raise PaperValidationError(
                    f"可用持仓不足：需要 {quantity}，可用 {available}"
                )
            assert position is not None
            average_cost = float(position.get("avg_cost", 0.0))
            realized_pnl = round((price - average_cost) * quantity, 2)

        order, trade = self.orders.fill_documents(
            user_id=user_id,
            identity=identity,
            side=side,
            quantity=quantity,
            price=price,
            amount=notional,
            commission=commission,
            realized_pnl=realized_pnl,
            timestamp=timestamp,
            analysis_id=analysis_id,
        )
        execution_id = str(uuid4())
        completed: list[str] = []
        failed_stage = "account"
        try:
            if side == "buy":
                available_cash = self.accounts.available_cash(
                    account,
                    identity.currency,
                )
                await self.accounts.debit(
                    user_id,
                    identity.currency,
                    round(available_cash - notional - commission, 2),
                    timestamp,
                )
            else:
                await self.accounts.credit_sale(
                    user_id,
                    identity.currency,
                    notional - commission,
                    realized_pnl,
                    timestamp,
                )
            completed.append("account")

            failed_stage = "position"
            if side == "buy":
                await self.positions.apply_buy(
                    user_id,
                    identity,
                    position,
                    quantity,
                    price,
                    timestamp,
                )
            else:
                assert position is not None
                await self.positions.apply_sell(
                    position,
                    quantity,
                    timestamp,
                )
            completed.append("position")

            failed_stage = "order"
            await self.orders.insert_order(order)
            completed.append("order")

            failed_stage = "trade"
            await self.orders.insert_trade(trade)
            completed.append("trade")
        except Exception as exc:
            recovery_id = await self.consistency.record_failure(
                execution_id=execution_id,
                user_id=user_id,
                operation=side,
                failed_stage=failed_stage,
                completed_stages=completed,
                error=exc,
                identity=identity,
                quantity=quantity,
                price=price,
                created_at=timestamp,
            )
            raise PaperConsistencyError(
                "模拟交易写入不完整，已创建恢复记录",
                recovery_id=recovery_id,
            ) from exc

        return PaperExecutionResult(
            order={
                key: value
                for key, value in order.items()
                if key != "_id"
            }
        )
