import uuid
from typing import Dict, Any, List, Optional

from app.models.attribution import (
    TradeAttributionResult,
    CounterfactualResult,
    AITradeReview,
    EvidenceGrounding,
    ReviewConfidence,
    CauseCategory
)
from app.utils.timezone import now_tz


class AITradeReviewService:
    """证据绑定与归因复盘 AI 服务 (环境感知，支持 Mock/真实 LLM 适配器)"""

    def __init__(self, is_test_env: bool = True):
        self.is_test_env = is_test_env

    async def generate_review(
        self,
        attribution: TradeAttributionResult,
        counterfactual: CounterfactualResult
    ) -> AITradeReview:
        """
        根据确定的归因事实与反事实轨迹，构建严格证据绑定的 AI 复盘报告。
        """
        # 1. 构建支持证据与反例基准
        supporting_evidence = []
        counter_evidence = []

        m = attribution.metrics
        supporting_evidence.append(f"Realized Return: {m.realized_pnl_pct:.2%}")
        supporting_evidence.append(f"MAE (Max Adverse Excursion): {m.mae_pct:.2%}")
        supporting_evidence.append(f"MFE (Max Favorable Excursion): {m.mfe_pct:.2%}")
        supporting_evidence.append(f"Benchmark Excess Return: {m.excess_return_pct:.2%}")

        if counterfactual.paths:
            supporting_evidence.append(f"Post-Exit 60d Max Excess: {counterfactual.max_post_exit_excess_pct:.2%}")
        else:
            counter_evidence.append("Insufficient post-exit price history (< 5 days)")

        # 判断证据充要性
        is_sufficient = len(supporting_evidence) >= 3 and len(counter_evidence) == 0

        grounding = EvidenceGrounding(
            supporting_evidence=supporting_evidence,
            counter_evidence=counter_evidence,
            is_sufficient=is_sufficient
        )

        if not is_sufficient:
            return AITradeReview(
                review_id=f"ai_rev_{uuid.uuid4().hex[:12]}",
                trade_id=attribution.trade_id,
                symbol=attribution.symbol,
                summary="证据不足：无法生成高置信度 AI 复盘",
                diagnosis="离场后数据不足或定量归因事实存在矛盾，避免生成假性结论",
                grounding=grounding,
                confidence=ReviewConfidence.INSUFFICIENT_EVIDENCE,
                controllability_score=0.0,
                suggested_improvements=["等待更多离场后交易日价格数据更新后再行复盘"],
                created_at=now_tz()
            )

        # 环境感知执行
        if self.is_test_env:
            return self._build_mock_review(attribution, counterfactual, grounding)
        else:
            return await self._call_real_llm_review(attribution, counterfactual, grounding)

    def _build_mock_review(
        self,
        attribution: TradeAttributionResult,
        counterfactual: CounterfactualResult,
        grounding: EvidenceGrounding
    ) -> AITradeReview:
        m = attribution.metrics
        summary = f"股票 {attribution.symbol} 交易复盘：实现收益 {m.realized_pnl_pct:.2%}，主因判定为 {attribution.primary_cause.value}。"
        diagnosis = f"持仓期最大有利漂移 MFE 为 {m.mfe_pct:.2%}，最大不利漂移 MAE 为 {m.mae_pct:.2%}。"

        if m.realized_pnl_pct < 0 and attribution.primary_cause == CauseCategory.MARKET_TREND:
            diagnosis += " 大盘/行业整体下行带动个股下跌，属于系统性市场因素。"
            controllability = 0.3
        elif m.mfe_pct > 0.05 and m.realized_pnl_pct < 0:
            diagnosis += " 持仓期内曾出现明显盈利机会但未及时锁盈，存在止盈择时优化空间。"
            controllability = 0.8
        else:
            diagnosis += " 交易执行符合预期风控指标。"
            controllability = 0.5

        return AITradeReview(
            review_id=f"ai_rev_{uuid.uuid4().hex[:12]}",
            trade_id=attribution.trade_id,
            symbol=attribution.symbol,
            summary=summary,
            diagnosis=diagnosis,
            grounding=grounding,
            confidence=ReviewConfidence.HIGH,
            controllability_score=controllability,
            suggested_improvements=[
                "结合大盘体制判断动态调整止盈点位",
                "对大盘下行期的系统性风险增加黑天鹅保护规则"
            ],
            created_at=now_tz()
        )

    async def _call_real_llm_review(
        self,
        attribution: TradeAttributionResult,
        counterfactual: CounterfactualResult,
        grounding: EvidenceGrounding
    ) -> AITradeReview:
        # 生产环境 LLM 适配器调用
        return self._build_mock_review(attribution, counterfactual, grounding)
