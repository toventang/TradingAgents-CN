import uuid
from app.models.backtest import CostSlippageModel, TradeFill
from app.utils.timezone import now_tz


class CostModelService:
    """可配置券商/账户交易成本与滑点计算服务"""

    @classmethod
    def calculate_fill(
        self,
        backtest_id: str,
        trade_date: str,
        symbol: str,
        side: str,
        quantity: int,
        price: float,
        cost_model: CostSlippageModel
    ) -> TradeFill:
        """
        计算实际成交价与各项手续费/滑点成本。
        - 买入：买入成本加滑点，价格上浮；
        - 卖出：卖出收益减滑点，价格下浮；卖出时收取印花税。
        """
        side_lower = side.lower()
        if side_lower == "buy":
            execution_price = price * (1.0 + cost_model.slippage_rate)
            stamp_duty = 0.0
        else:
            execution_price = price * (1.0 - cost_model.slippage_rate)
            stamp_duty = (execution_price * quantity) * cost_model.stamp_duty_rate

        turnover = round(execution_price * quantity, 2)

        # 佣金计算：百分比佣金，不足最低佣金的按最低佣金收取
        raw_commission = turnover * cost_model.commission_rate
        commission = round(max(raw_commission, cost_model.min_commission), 2)

        # 过户费
        transfer_fee = round(turnover * cost_model.transfer_fee_rate, 2)

        # 总成本
        total_cost = round(commission + stamp_duty + transfer_fee, 2)

        return TradeFill(
            fill_id=f"fill_{uuid.uuid4().hex[:12]}",
            backtest_id=backtest_id,
            trade_date=trade_date,
            symbol=symbol,
            side=side_lower,
            quantity=quantity,
            price=price,
            execution_price=round(execution_price, 4),
            turnover=turnover,
            commission=commission,
            stamp_duty=round(stamp_duty, 2),
            transfer_fee=transfer_fee,
            total_cost=total_cost,
            created_at=now_tz()
        )
