import uuid
from typing import List, Dict, Any, Optional
import numpy as np
import pandas as pd

from app.models.risk import (
    RiskConfig,
    RiskEvaluationResult,
    RiskViolation,
    RiskDecision,
    RiskSeverity,
    RiskAction
)
from app.utils.timezone import now_tz


class RiskEvaluationEngine:
    """100% 确定性、无 LLM 随机性的仓位与组合风险评估引擎"""

    def evaluate_portfolio(
        self,
        config: RiskConfig,
        total_equity: float,
        cash: float,
        positions: Dict[str, Dict[str, Any]],     # symbol -> {quantity, market_value, cost_price, current_price, sector, t_plus_1_available_qty, adv_5d, is_limit_up, is_limit_down}
        proposed_trades: Optional[List[Dict[str, Any]]] = None, # [{symbol, side, quantity, price, sector}]
        historical_returns: Optional[List[float]] = None,
        current_drawdown: float = 0.0
    ) -> RiskEvaluationResult:
        """
        评估组合持仓与拟执行订单的风控合规性。
        """
        violations: List[RiskViolation] = []
        trades = proposed_trades or []

        # 1. 组合层最大回撤评估
        if current_drawdown > config.max_drawdown_limit:
            violations.append(RiskViolation(
                rule_id="RULE_MAX_DRAWDOWN",
                rule_name="组合最大回撤限制",
                severity=RiskSeverity.CRITICAL,
                current_value=round(current_drawdown, 4),
                limit_threshold=config.max_drawdown_limit,
                action_required=RiskAction.HALT_PORTFOLIO,
                message=f"组合当前回撤 {current_drawdown:.2%} 超过风控上限 {config.max_drawdown_limit:.2%}"
            ))

        # 2. 计算估计每日 VaR 95%
        if historical_returns and len(historical_returns) >= 10:
            returns_arr = np.array(historical_returns)
            var_95 = float(-np.percentile(returns_arr, 5))
            if var_95 > config.max_var_95_limit:
                violations.append(RiskViolation(
                    rule_id="RULE_VAR_95",
                    rule_name="组合 95% VaR 风险限制",
                    severity=RiskSeverity.WARNING,
                    current_value=round(var_95, 4),
                    limit_threshold=config.max_var_95_limit,
                    action_required=RiskAction.BLOCK_BUY,
                    message=f"组合日度 VaR(95%) {var_95:.2%} 超过阈值 {config.max_var_95_limit:.2%}"
                ))

        # 构建模拟订单执行后的持仓快照
        simulated_positions = {sym: dict(data) for sym, data in positions.items()}
        simulated_cash = cash

        for t in trades:
            sym = t["symbol"]
            side = t["side"].lower()
            qty = t["quantity"]
            price = t.get("price", 0.0)
            sector = t.get("sector", "Unknown")

            # 3. 涨跌停与 T+1 订单直接评估
            pos_data = positions.get(sym, {})
            is_limit_up = t.get("is_limit_up", pos_data.get("is_limit_up", False))
            is_limit_down = t.get("is_limit_down", pos_data.get("is_limit_down", False))
            adv_5d = t.get("adv_5d", pos_data.get("adv_5d", 0))

            if side == "buy" and config.block_limit_up_buy and is_limit_up:
                violations.append(RiskViolation(
                    rule_id="RULE_LIMIT_UP_BUY",
                    rule_name="涨停板买入拦截",
                    severity=RiskSeverity.CRITICAL,
                    symbol=sym,
                    current_value=1.0,
                    limit_threshold=0.0,
                    action_required=RiskAction.BLOCK_BUY,
                    message=f"股票 {sym} 当前处于涨停板，禁止买入下单"
                ))

            if side == "sell" and config.block_limit_down_sell and is_limit_down:
                violations.append(RiskViolation(
                    rule_id="RULE_LIMIT_DOWN_SELL",
                    rule_name="跌停板卖出拦截",
                    severity=RiskSeverity.CRITICAL,
                    symbol=sym,
                    current_value=1.0,
                    limit_threshold=0.0,
                    action_required=RiskAction.BLOCK_BUY,
                    message=f"股票 {sym} 当前处于跌停板，无法正常卖出"
                ))

            # 4. T+1 可卖数量约束
            if side == "sell" and config.enforce_t_plus_1:
                avail_qty = pos_data.get("t_plus_1_available_qty", pos_data.get("quantity", 0))
                if qty > avail_qty:
                    violations.append(RiskViolation(
                        rule_id="RULE_T_PLUS_1",
                        rule_name="A 股 T+1 结算卖出限制",
                        severity=RiskSeverity.CRITICAL,
                        symbol=sym,
                        current_value=float(qty),
                        limit_threshold=float(avail_qty),
                        action_required=RiskAction.BLOCK_BUY,
                        message=f"股票 {sym} 拟卖出数量 {qty} 超过 T+1 可卖数量 {avail_qty}"
                    ))

            # 5. 成交量 ADV 参与度上限
            if adv_5d > 0 and (qty / adv_5d) > config.max_adv_participation_rate:
                violations.append(RiskViolation(
                    rule_id="RULE_ADV_PARTICIPATION",
                    rule_name="日均成交量 ADV 参与度上限",
                    severity=RiskSeverity.WARNING,
                    symbol=sym,
                    current_value=round(qty / adv_5d, 4),
                    limit_threshold=config.max_adv_participation_rate,
                    action_required=RiskAction.FORCE_REDUCE,
                    message=f"股票 {sym} 拟交易量占 5 日 ADV 比例 {qty / adv_5d:.2%} 超过上限 {config.max_adv_participation_rate:.2%}"
                ))

            # 更新模拟持仓
            curr_pos = simulated_positions.get(sym, {"quantity": 0, "market_value": 0.0, "sector": sector})
            if side == "buy":
                new_qty = curr_pos["quantity"] + qty
                new_mv = curr_pos["market_value"] + (qty * price)
                simulated_positions[sym] = {"quantity": new_qty, "market_value": new_mv, "sector": sector}
            elif side == "sell":
                new_qty = max(0, curr_pos["quantity"] - qty)
                new_mv = max(0.0, curr_pos["market_value"] - (qty * price))
                simulated_positions[sym] = {"quantity": new_qty, "market_value": new_mv, "sector": sector}

        # 6. 个股集中度与行业集中度上限评估
        sim_total_mv = sum(p.get("market_value", 0.0) for p in simulated_positions.values())
        eval_equity = max(total_equity, sim_total_mv) if total_equity > 0 else 1.0

        sector_mv_map: Dict[str, float] = {}

        for sym, p in simulated_positions.items():
            mv = p.get("market_value", 0.0)
            stock_weight = mv / eval_equity if eval_equity > 0 else 0.0

            if stock_weight > config.max_stock_weight:
                violations.append(RiskViolation(
                    rule_id="RULE_STOCK_CONCENTRATION",
                    rule_name="单股持仓集中度上限",
                    severity=RiskSeverity.WARNING,
                    symbol=sym,
                    current_value=round(stock_weight, 4),
                    limit_threshold=config.max_stock_weight,
                    action_required=RiskAction.FORCE_REDUCE,
                    message=f"股票 {sym} 权重 {stock_weight:.2%} 超过单股持仓上限 {config.max_stock_weight:.2%}"
                ))

            sec = p.get("sector", "Unknown")
            sector_mv_map[sec] = sector_mv_map.get(sec, 0.0) + mv

        for sec, sec_mv in sector_mv_map.items():
            sector_weight = sec_mv / eval_equity if eval_equity > 0 else 0.0
            if sector_weight > config.max_sector_weight:
                violations.append(RiskViolation(
                    rule_id="RULE_SECTOR_CONCENTRATION",
                    rule_name="单行业持仓集中度上限",
                    severity=RiskSeverity.WARNING,
                    symbol=f"SECTOR_{sec}",
                    current_value=round(sector_weight, 4),
                    limit_threshold=config.max_sector_weight,
                    action_required=RiskAction.FORCE_REDUCE,
                    message=f"行业 {sec} 总权重 {sector_weight:.2%} 超过行业持仓上限 {config.max_sector_weight:.2%}"
                ))

        # 决策生成
        if any(v.severity == RiskSeverity.CRITICAL for v in violations):
            decision = RiskDecision.REJECTED
        elif violations:
            decision = RiskDecision.APPROVED_WITH_WARNINGS
        else:
            decision = RiskDecision.APPROVED

        return RiskEvaluationResult(
            evaluation_id=f"risk_eval_{uuid.uuid4().hex[:12]}",
            portfolio_id=config.portfolio_id,
            decision=decision,
            violations=violations,
            evaluated_at=now_tz()
        )
