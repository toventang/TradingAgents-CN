"""Durable, restart-safe twelve-step daily backtest engine."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Awaitable, Callable, Mapping, Protocol

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from app.models.backtest import (
    BacktestInputBundle,
    BrokerExecutionResult,
    BrokerOrder,
    BrokerOrderStatus,
    DailyBacktestInput,
    ExecutionPriceModel,
    OrderSide,
    SecurityRuleContext,
    SlippageConfig,
    finite_decimal,
)
from app.repositories.backtest_repository import BacktestRepository
from app.services.backtest.broker import SimulatedBroker
from app.services.backtest.ledger import (
    BacktestCheckpoint,
    BacktestEquityDailyRecord,
    BacktestEventRecord,
    BacktestOrderRecord,
    BacktestPositionDailyRecord,
    BacktestRunRecord,
    BacktestTradeRecord,
    DailyLedgerBatch,
)
from app.services.backtest.portfolio import InsufficientCash, PortfolioState
from app.services.domain_tasks import (
    CancellationChecker,
    ProgressCallback,
    TaskCancellationRequested,
)
from app.services.paper.market_rules import DatedMarketRuleService


class BacktestEngineError(RuntimeError):
    def __init__(self, message: str, *, code: str = "BACKTEST_ENGINE_INVALID"):
        super().__init__(message)
        self.code = code


class OrderIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    signal_id: str = Field(min_length=1, max_length=128)
    symbol: str = Field(min_length=1, max_length=64)
    side: OrderSide
    quantity: StrictInt | None = Field(default=None, gt=0)
    execution_model: ExecutionPriceModel = ExecutionPriceModel.NEXT_OPEN
    slippage: SlippageConfig = Field(default_factory=SlippageConfig)
    cooldown_sessions: StrictInt = Field(default=0, ge=0, le=252)

    @model_validator(mode="after")
    def validate_intent(self) -> "OrderIntent":
        if self.side == OrderSide.BUY and self.quantity is None:
            raise ValueError("buy intent requires quantity")
        return self


class StrategyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    exit_orders: tuple[OrderIntent, ...] = ()
    entry_orders: tuple[OrderIntent, ...] = ()
    stop_new_buys: bool = False
    reason_codes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_sides(self) -> "StrategyDecision":
        if any(item.side != OrderSide.SELL for item in self.exit_orders):
            raise ValueError("exit_orders must contain sells")
        if any(item.side != OrderSide.BUY for item in self.entry_orders):
            raise ValueError("entry_orders must contain buys")
        return self


class StrategyPolicy(Protocol):
    async def evaluate(
        self, day: DailyBacktestInput, portfolio: PortfolioState
    ) -> StrategyDecision: ...


class NoOpStrategyPolicy:
    async def evaluate(
        self, day: DailyBacktestInput, portfolio: PortfolioState
    ) -> StrategyDecision:
        del day, portfolio
        return StrategyDecision()


@dataclass(frozen=True)
class BacktestRunPlan:
    bundle: BacktestInputBundle
    initial_cash: Decimal
    policy: StrategyPolicy = field(default_factory=NoOpStrategyPolicy)
    security_contexts: Mapping[str, SecurityRuleContext] = field(default_factory=dict)


PlanLoader = Callable[[BacktestRunRecord], Awaitable[BacktestRunPlan]]


class BacktestEngine:
    def __init__(
        self,
        repository: BacktestRepository,
        *,
        plan_loader: PlanLoader,
        broker: SimulatedBroker | None = None,
        market_rules: DatedMarketRuleService | None = None,
    ):
        self.repository = repository
        self.plan_loader = plan_loader
        self.market_rules = market_rules or DatedMarketRuleService()
        self.broker = broker or SimulatedBroker(market_rules=self.market_rules)

    async def run(
        self,
        *,
        run_id: str,
        user_id: str,
        task_id: str,
        report_progress: ProgressCallback,
        is_cancelled: CancellationChecker,
    ) -> BacktestRunRecord:
        run = await self.repository.mark_run_running(
            run_id, user_id=user_id, task_id=task_id
        )
        if await is_cancelled():
            await self.repository.mark_run_cancelled(run_id, user_id=user_id)
            raise TaskCancellationRequested("backtest was cancelled before execution")
        plan = await self.plan_loader(run)
        self._validate_plan(run, plan)
        checkpoint = await self.repository.latest_checkpoint(run_id, user_id=user_id)
        if checkpoint is None:
            portfolio = PortfolioState(
                market=plan.bundle.market, initial_cash=plan.initial_cash
            )
            pending_orders: dict[str, BrokerOrder] = {}
            signal_ids: dict[str, str] = {}
            cooldown_until: dict[str, date] = {}
            last_prices: dict[str, Decimal] = {}
            previous_equity: Decimal | None = None
            peak_equity = portfolio.initial_cash
            benchmark_base: Decimal | None = None
            completed_days = order_count = trade_count = 0
            start_index = 0
        else:
            portfolio = PortfolioState.from_snapshot(checkpoint.portfolio_state)
            pending_orders = {
                item.order_id: item
                for item in (
                    BrokerOrder.model_validate(value)
                    for value in checkpoint.pending_orders
                )
            }
            signal_ids = dict(checkpoint.signal_ids)
            cooldown_until = dict(checkpoint.cooldown_until)
            last_prices = dict(checkpoint.last_prices)
            previous_equity = checkpoint.previous_equity
            peak_equity = checkpoint.peak_equity
            benchmark_base = checkpoint.benchmark_base_close
            completed_days = checkpoint.completed_days
            order_count = checkpoint.order_count
            trade_count = checkpoint.trade_count
            dates = [item.trade_date for item in plan.bundle.days]
            if checkpoint.trade_date not in dates:
                raise BacktestEngineError(
                    "checkpoint date is outside the immutable input bundle",
                    code="BACKTEST_CHECKPOINT_INPUT_MISMATCH",
                )
            start_index = dates.index(checkpoint.trade_date) + 1

        days = plan.bundle.days
        all_dates = tuple(item.trade_date for item in days)
        for index in range(start_index, len(days)):
            if await is_cancelled():
                await self.repository.mark_run_cancelled(run_id, user_id=user_id)
                raise TaskCancellationRequested("backtest was cancelled between days")
            day = days[index]
            next_date = days[index + 1].trade_date if index + 1 < len(days) else None
            batch, cancel_after_commit = await self._run_day(
                run=run,
                plan=plan,
                day=day,
                day_index=index,
                all_dates=all_dates,
                next_trade_date=next_date,
                portfolio=portfolio,
                pending_orders=pending_orders,
                signal_ids=signal_ids,
                cooldown_until=cooldown_until,
                last_prices=last_prices,
                previous_equity=previous_equity,
                peak_equity=peak_equity,
                benchmark_base=benchmark_base,
                completed_days=completed_days,
                order_count=order_count,
                trade_count=trade_count,
                is_cancelled=is_cancelled,
            )
            await self.repository.commit_day(batch)
            checkpoint = batch.checkpoint
            previous_equity = checkpoint.previous_equity
            peak_equity = checkpoint.peak_equity
            benchmark_base = checkpoint.benchmark_base_close
            completed_days = checkpoint.completed_days
            order_count = checkpoint.order_count
            trade_count = checkpoint.trade_count
            await report_progress(
                completed_days / len(days),
                "backtest_day_committed",
                f"committed {day.trade_date.isoformat()}",
            )
            if cancel_after_commit:
                await self.repository.mark_run_cancelled(run_id, user_id=user_id)
                raise TaskCancellationRequested("backtest cancellation acknowledged")

        if checkpoint is None:
            raise BacktestEngineError("backtest input bundle contains no trading days")
        final_equity = portfolio.equity(last_prices)
        return await self.repository.mark_run_succeeded(
            run_id,
            user_id=user_id,
            summary={
                "completed_days": completed_days,
                "order_count": order_count,
                "trade_count": trade_count,
                "final_cash": str(portfolio.cash),
                "final_equity": str(final_equity),
                "position_count": len(portfolio.symbols),
                "total_fees": str(portfolio.total_fees),
            },
        )

    async def _run_day(
        self,
        *,
        run: BacktestRunRecord,
        plan: BacktestRunPlan,
        day: DailyBacktestInput,
        day_index: int,
        all_dates: tuple[date, ...],
        next_trade_date: date | None,
        portfolio: PortfolioState,
        pending_orders: dict[str, BrokerOrder],
        signal_ids: dict[str, str],
        cooldown_until: dict[str, date],
        last_prices: dict[str, Decimal],
        previous_equity: Decimal | None,
        peak_equity: Decimal,
        benchmark_base: Decimal | None,
        completed_days: int,
        order_count: int,
        trade_count: int,
        is_cancelled: CancellationChecker,
    ) -> tuple[DailyLedgerBatch, bool]:
        event_buckets: dict[int, list[tuple[str, str | None, dict]]] = {
            step: [] for step in range(1, 13)
        }

        def emit(step: int, event_type: str, symbol=None, **data) -> None:
            event_buckets[step].append((event_type, symbol, data))

        bar_by_symbol = {item.symbol: item for item in day.bars}
        emit(
            1,
            "INPUTS_LOADED",
            symbols=len(day.universe),
            bars=len(day.bars),
            input_checksum=day.input_checksum,
            bias_warning_count=len(day.bias_warnings),
        )
        for bar in day.bars:
            if bar.close is not None and bar.close > 0:
                last_prices[bar.symbol] = finite_decimal(bar.close)

        action_count = 0
        for action in day.corporate_actions:
            result = portfolio.apply_corporate_action(action)
            action_count += int(result["quantity_before"] != 0)
            emit(2, "CORPORATE_ACTION_APPLIED", action.symbol, action_id=action.action_id, **result)
        emit(2, "CORPORATE_ACTIONS_COMPLETE", applied=action_count)

        released = sum(
            lot.remaining_quantity
            for symbol in portfolio.symbols
            for lot in portfolio.lots_for(symbol)
            if lot.available_trade_date == day.trade_date
        )
        emit(3, "SETTLEMENT_RELEASED", quantity=released)
        emit(4, "PENDING_ORDERS_SELECTED", count=len(pending_orders))

        order_records: dict[str, BacktestOrderRecord] = {}
        trade_records: list[BacktestTradeRecord] = []
        validation_results: list[tuple[str, str]] = []
        execution_results: list[tuple[str, str]] = []
        fee_total = Decimal("0")
        realized_total = Decimal("0")
        attempted_ids = tuple(sorted(pending_orders))
        for order_id in attempted_ids:
            order = pending_orders[order_id]
            signal_id = signal_ids[order_id]
            bar = bar_by_symbol.get(order.symbol)
            if bar is None or day.market_rule is None:
                reason = "MISSING_EXECUTION_BAR" if bar is None else "MISSING_MARKET_RULE"
                updated = self._terminal_order(order, reason)
                pending_orders.pop(order_id, None)
                signal_ids.pop(order_id, None)
                order_records[order_id] = self._order_record(
                    run, updated, signal_id, reject_reason=reason
                )
                validation_results.append((order_id, reason))
                execution_results.append((order_id, "rejected"))
                continue
            context = self._security_context(plan, day, order.symbol)
            try:
                resolved = self.market_rules.resolve(
                    day.market_rule,
                    context,
                    trade_date=day.trade_date,
                    as_of=day.signal_as_of,
                )
            except ValueError as exc:
                reason = f"MARKET_RULE_INVALID:{exc}"
                updated = self._terminal_order(order, reason)
                pending_orders.pop(order_id, None)
                signal_ids.pop(order_id, None)
                order_records[order_id] = self._order_record(
                    run, updated, signal_id, reject_reason=reason
                )
                validation_results.append((order_id, reason))
                execution_results.append((order_id, "rejected"))
                continue
            validation_results.append((order_id, resolved.rule_version_id))
            result = self.broker.execute(
                order,
                bar,
                context,
                resolved,
                position_lots=portfolio.lots_for(order.symbol),
                position_quantity=portfolio.quantity(order.symbol),
            )
            realized: Decimal | None = None
            if result.fill is not None:
                trade_id = self._identifier(
                    "trade",
                    run.run_id,
                    order_id,
                    day.trade_date.isoformat(),
                    str(result.cumulative_filled_quantity),
                )
                availability = (
                    day.trade_date
                    if resolved.t_plus_days == 0
                    else next_trade_date or date.max
                )
                try:
                    realized = portfolio.apply_fill(
                        result.fill,
                        trade_id=trade_id,
                        available_trade_date=availability,
                    )
                except InsufficientCash:
                    result = BrokerExecutionResult(
                        order_id=order.order_id,
                        trade_date=day.trade_date,
                        status=BrokerOrderStatus.REJECTED,
                        requested_quantity=order.requested_quantity,
                        cumulative_filled_quantity=order.filled_quantity,
                        remaining_quantity=order.remaining_quantity,
                        execution_attempts=result.execution_attempts,
                        reason="INSUFFICIENT_CASH",
                    )
                else:
                    fee_total += result.fill.fees.total
                    if realized is not None:
                        realized_total += realized
                    trade_records.append(
                        BacktestTradeRecord(
                            trade_id=trade_id,
                            order_id=order_id,
                            run_id=run.run_id,
                            user_id=run.user_id,
                            market=order.market,
                            symbol=order.symbol,
                            side=order.side,
                            quantity=result.fill.quantity,
                            raw_price=result.fill.raw_price,
                            slippage=result.fill.slippage_per_share,
                            fill_price=result.fill.fill_price,
                            notional=result.fill.notional,
                            fees=result.fill.fees,
                            trade_date=day.trade_date,
                            realized_pnl=realized,
                        )
                    )
            updated = self._updated_order(order, result)
            order_records[order_id] = self._order_record(
                run, updated, signal_id, reject_reason=result.reason
            )
            execution_results.append((order_id, result.status.value))
            if result.status in {
                BrokerOrderStatus.PENDING,
                BrokerOrderStatus.PARTIALLY_FILLED,
            }:
                pending_orders[order_id] = updated
            else:
                pending_orders.pop(order_id, None)
                signal_ids.pop(order_id, None)

        for order_id, result in validation_results:
            emit(5, "ORDER_VALIDATED", order_id=order_id, result=result)
        emit(5, "MARKET_VALIDATION_COMPLETE", count=len(validation_results))
        for order_id, status in execution_results:
            emit(6, "ORDER_EXECUTION_RESULT", order_id=order_id, status=status)
        emit(6, "EXECUTION_COMPLETE", count=len(execution_results))
        emit(7, "FEES_DEDUCTED", total=str(_money(fee_total)))
        emit(
            8,
            "PORTFOLIO_UPDATED",
            cash=str(portfolio.cash),
            position_count=len(portfolio.symbols),
            realized_pnl=str(_money(realized_total)),
        )

        decision = await plan.policy.evaluate(day, portfolio)
        emit(
            9,
            "SIGNALS_EVALUATED",
            exits=len(decision.exit_orders),
            entries=len(decision.entry_orders),
            reason_codes=list(decision.reason_codes),
        )
        future_dates = all_dates[day_index + 1 : day_index + 4]
        exit_symbols = {item.symbol for item in decision.exit_orders}
        new_orders = 0
        for intent in (*decision.exit_orders, *decision.entry_orders):
            block_reason: str | None = None
            quantity = intent.quantity
            if intent.side == OrderSide.SELL:
                quantity = quantity or portfolio.quantity(intent.symbol)
                if quantity <= 0:
                    block_reason = "NO_POSITION_TO_EXIT"
                if intent.cooldown_sessions > 0:
                    target = min(
                        day_index + intent.cooldown_sessions,
                        len(all_dates) - 1,
                    )
                    cooldown_until[intent.symbol] = all_dates[target]
            else:
                if intent.symbol in exit_symbols:
                    block_reason = "EXIT_PRIORITY"
                elif decision.stop_new_buys:
                    block_reason = "RISK_STOP_NEW_BUYS"
                elif cooldown_until.get(intent.symbol, date.min) >= day.trade_date:
                    block_reason = "COOLDOWN_ACTIVE"
                elif intent.symbol not in bar_by_symbol:
                    block_reason = "UNSAFE_OR_MISSING_SIGNAL_BAR"
            if not future_dates:
                block_reason = block_reason or "NO_FUTURE_EXECUTION_DATE"
            if any(
                item.symbol == intent.symbol and item.side == intent.side
                for item in pending_orders.values()
            ):
                block_reason = block_reason or "DUPLICATE_PENDING_ORDER"
            if block_reason is not None:
                emit(10, "ORDER_INTENT_BLOCKED", intent.symbol, reason=block_reason)
                continue
            assert quantity is not None
            order_id = self._identifier(
                "order",
                run.run_id,
                intent.signal_id,
                intent.symbol,
                intent.side.value,
                day.trade_date.isoformat(),
            )
            if order_id in pending_orders:
                raise BacktestEngineError("deterministic order ID collision")
            created = BrokerOrder(
                order_id=order_id,
                market=day.market,
                symbol=intent.symbol,
                side=intent.side,
                requested_quantity=quantity,
                created_trade_date=day.trade_date,
                expires_on=future_dates[-1],
                execution_model=intent.execution_model,
                slippage=intent.slippage,
            )
            pending_orders[order_id] = created
            signal_ids[order_id] = intent.signal_id
            order_records[order_id] = self._order_record(
                run, created, intent.signal_id
            )
            new_orders += 1
            emit(10, "ORDER_CREATED", intent.symbol, order_id=order_id)
        if next_trade_date is None and pending_orders:
            for order_id in tuple(sorted(pending_orders)):
                pending = pending_orders.pop(order_id)
                signal_id = signal_ids.pop(order_id)
                expired = BrokerOrder.model_validate(
                    {
                        **pending.model_dump(mode="python"),
                        "status": BrokerOrderStatus.EXPIRED,
                    }
                )
                order_records[order_id] = self._order_record(
                    run, expired, signal_id, reject_reason="BACKTEST_END"
                )
                emit(10, "ORDER_EXPIRED_AT_BACKTEST_END", pending.symbol, order_id=order_id)
        emit(10, "ORDER_GENERATION_COMPLETE", created=new_orders)

        prices = {
            symbol: last_prices[symbol]
            for symbol in portfolio.symbols
            if symbol in last_prices
        }
        current_valuation_symbols = {
            bar.symbol
            for bar in day.bars
            if bar.close is not None and bar.close > 0
        }
        for symbol in portfolio.symbols:
            if symbol not in current_valuation_symbols:
                emit(
                    11,
                    "VALUATION_STALE",
                    symbol,
                    price=str(prices.get(symbol, "")),
                    reason="CURRENT_CLOSE_UNAVAILABLE",
                )
        values = portfolio.market_values(prices)
        equity = portfolio.equity(prices)
        position_records: list[BacktestPositionDailyRecord] = []
        for symbol in portfolio.symbols:
            quantity = portfolio.quantity(symbol)
            avg_cost = portfolio.average_cost(symbol)
            acquired = min(
                item.acquired_trade_date for item in portfolio.lots_for(symbol)
            )
            holding_days = sum(
                1 for item in all_dates if acquired <= item <= day.trade_date
            )
            position_records.append(
                BacktestPositionDailyRecord(
                    run_id=run.run_id,
                    user_id=run.user_id,
                    trade_date=day.trade_date,
                    market=day.market,
                    symbol=symbol,
                    quantity=quantity,
                    available_qty=portfolio.available_quantity(symbol, day.trade_date),
                    avg_cost=avg_cost,
                    close=prices[symbol],
                    market_value=values[symbol],
                    unrealized_pnl=_money(values[symbol] - avg_cost * quantity),
                    weight=(values[symbol] / equity),
                    holding_days=holding_days,
                )
            )
        market_value = sum(values.values(), Decimal("0"))
        new_peak = max(peak_equity, equity)
        daily_return = (
            None if previous_equity is None else equity / previous_equity - 1
        )
        cumulative_return = equity / portfolio.initial_cash - 1
        drawdown = equity / new_peak - 1
        traded_notional = sum(
            (item.notional for item in trade_records), Decimal("0")
        )
        turnover_base = previous_equity or portfolio.initial_cash
        benchmark_close = day.benchmark.close if day.benchmark is not None else None
        new_benchmark_base = benchmark_base or benchmark_close
        benchmark_equity = (
            None
            if benchmark_close is None or new_benchmark_base is None
            else portfolio.initial_cash * benchmark_close / new_benchmark_base
        )
        equity_record = BacktestEquityDailyRecord(
            run_id=run.run_id,
            user_id=run.user_id,
            trade_date=day.trade_date,
            cash=portfolio.cash,
            market_value=market_value,
            equity=equity,
            daily_return=daily_return,
            cumulative_return=cumulative_return,
            drawdown=drawdown,
            benchmark_equity=benchmark_equity,
            turnover=traded_notional / turnover_base,
            gross_exposure=market_value / equity,
            net_exposure=market_value / equity,
        )
        emit(
            11,
            "EQUITY_RECONCILED",
            cash=str(portfolio.cash),
            market_value=str(market_value),
            equity=str(equity),
        )
        cancel_after_commit = await is_cancelled()
        if cancel_after_commit and pending_orders:
            for order_id in tuple(sorted(pending_orders)):
                pending = pending_orders.pop(order_id)
                signal_id = signal_ids.pop(order_id)
                cancelled = BrokerOrder.model_validate(
                    {
                        **pending.model_dump(mode="python"),
                        "status": BrokerOrderStatus.CANCELLED,
                    }
                )
                order_records[order_id] = self._order_record(
                    run, cancelled, signal_id, reject_reason="RUN_CANCELLED"
                )
                emit(12, "PENDING_ORDER_CANCELLED", pending.symbol, order_id=order_id)
        emit(
            12,
            "CANCEL_REQUESTED" if cancel_after_commit else "DAY_COMMIT_READY",
        )

        events = self._events(run, day.trade_date, event_buckets)
        checkpoint = BacktestCheckpoint(
            run_id=run.run_id,
            user_id=run.user_id,
            trade_date=day.trade_date,
            portfolio_state=portfolio.to_snapshot(),
            pending_orders=tuple(
                pending_orders[key].model_dump(mode="json")
                for key in sorted(pending_orders)
            ),
            signal_ids={key: signal_ids[key] for key in sorted(signal_ids)},
            cooldown_until=dict(sorted(cooldown_until.items())),
            last_prices=dict(sorted(last_prices.items())),
            previous_equity=equity,
            peak_equity=new_peak,
            benchmark_base_close=new_benchmark_base,
            completed_days=completed_days + 1,
            order_count=order_count + new_orders,
            trade_count=trade_count + len(trade_records),
        )
        return (
            DailyLedgerBatch(
                run_id=run.run_id,
                user_id=run.user_id,
                trade_date=day.trade_date,
                orders=tuple(order_records[key] for key in sorted(order_records)),
                trades=tuple(trade_records),
                positions=tuple(position_records),
                equity=equity_record,
                events=events,
                checkpoint=checkpoint,
            ),
            cancel_after_commit,
        )

    @staticmethod
    def _validate_plan(run: BacktestRunRecord, plan: BacktestRunPlan) -> None:
        if plan.bundle.market != run.market:
            raise BacktestEngineError("run and input bundle market differ")
        if not plan.bundle.days:
            raise BacktestEngineError("input bundle contains no trading days")
        if plan.initial_cash <= 0:
            raise BacktestEngineError("initial cash must be positive")

    @staticmethod
    def _security_context(
        plan: BacktestRunPlan, day: DailyBacktestInput, symbol: str
    ) -> SecurityRuleContext:
        membership = next((item for item in day.universe if item.symbol == symbol), None)
        base = plan.security_contexts.get(symbol)
        if base is None:
            return SecurityRuleContext(
                market=day.market,
                symbol=symbol,
                is_st=membership.is_st if membership is not None else False,
            )
        if base.market != day.market or base.symbol != symbol:
            raise BacktestEngineError("security context identity differs from input")
        return SecurityRuleContext.model_validate(
            {
                **base.model_dump(mode="python"),
                "is_st": membership.is_st if membership is not None else base.is_st,
            }
        )

    @staticmethod
    def _updated_order(
        order: BrokerOrder, result: BrokerExecutionResult
    ) -> BrokerOrder:
        return BrokerOrder.model_validate(
            {
                **order.model_dump(mode="python"),
                "filled_quantity": result.cumulative_filled_quantity,
                "status": result.status,
                "execution_attempts": result.execution_attempts,
            }
        )

    @staticmethod
    def _terminal_order(order: BrokerOrder, reason: str) -> BrokerOrder:
        del reason
        return BrokerOrder.model_validate(
            {
                **order.model_dump(mode="python"),
                "status": BrokerOrderStatus.REJECTED,
                "execution_attempts": min(
                    order.maximum_execution_days, order.execution_attempts + 1
                ),
            }
        )

    @staticmethod
    def _order_record(
        run: BacktestRunRecord,
        order: BrokerOrder,
        signal_id: str,
        *,
        reject_reason: str | None = None,
    ) -> BacktestOrderRecord:
        return BacktestOrderRecord(
            order_id=order.order_id,
            run_id=run.run_id,
            user_id=run.user_id,
            signal_id=signal_id,
            market=order.market,
            symbol=order.symbol,
            side=order.side,
            requested_qty=order.requested_quantity,
            filled_qty=order.filled_quantity,
            remaining_qty=order.remaining_quantity,
            order_type=order.execution_model.value,
            created_trade_date=order.created_trade_date,
            expire_date=order.expires_on,
            status=order.status,
            execution_attempts=order.execution_attempts,
            reject_reason=reject_reason,
        )

    @classmethod
    def _events(
        cls,
        run: BacktestRunRecord,
        trade_date: date,
        buckets: dict[int, list[tuple[str, str | None, dict]]],
    ) -> tuple[BacktestEventRecord, ...]:
        result: list[BacktestEventRecord] = []
        sequence = 0
        for step in range(1, 13):
            for event_type, symbol, data in buckets[step]:
                sequence += 1
                result.append(
                    BacktestEventRecord(
                        event_id=cls._identifier(
                            "event",
                            run.run_id,
                            trade_date.isoformat(),
                            str(sequence),
                            event_type,
                        ),
                        run_id=run.run_id,
                        user_id=run.user_id,
                        trade_date=trade_date,
                        sequence=sequence,
                        step=step,
                        event_type=event_type,
                        symbol=symbol,
                        data=data,
                    )
                )
        return tuple(result)

    @staticmethod
    def _identifier(prefix: str, *parts: str) -> str:
        digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
        return f"{prefix}:{digest[:40]}"


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
