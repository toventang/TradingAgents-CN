import pytest
from app.models.attribution import (
    TradeReviewInput,
    ReviewConfidence,
    CauseCategory
)
from app.services.learning.attribution import TradeAttributionService
from app.services.learning.counterfactual import CounterfactualService
from app.services.learning.ai_review import AITradeReviewService


@pytest.mark.asyncio
async def test_ai_trade_review_generation():
    inp = TradeReviewInput(
        trade_id="tr_ai_1",
        symbol="600000.SH",
        entry_date="2026-01-01",
        exit_date="2026-01-05",
        entry_price=10.0,
        exit_price=8.5,
        quantity=1000,
        daily_prices=[10.0, 10.5, 9.0, 8.5, 8.5],
        daily_benchmark_prices=[1000.0, 990.0, 950.0, 920.0, 900.0]
    )

    attr_res = TradeAttributionService.analyze_trade(inp)
    cf_res = CounterfactualService.analyze_post_exit_paths(
        trade_id="tr_ai_1",
        symbol="600000.SH",
        exit_price=8.5,
        post_exit_prices=[8.5, 8.6, 8.7, 8.8, 8.9],
        post_exit_bm_prices=[900.0, 905.0, 910.0, 915.0, 920.0]
    )

    service = AITradeReviewService(is_test_env=True)
    review = await service.generate_review(attr_res, cf_res)

    assert review.trade_id == "tr_ai_1"
    assert review.confidence == ReviewConfidence.HIGH
    assert review.grounding.is_sufficient is True
    assert len(review.grounding.supporting_evidence) >= 3


@pytest.mark.asyncio
async def test_ai_trade_review_insufficient_evidence():
    inp = TradeReviewInput(
        trade_id="tr_ai_2",
        symbol="000001.SZ",
        entry_date="2026-01-01",
        exit_date="2026-01-02",
        entry_price=10.0,
        exit_price=10.0,
        quantity=1000,
        daily_prices=[10.0],
        daily_benchmark_prices=[1000.0]
    )

    attr_res = TradeAttributionService.analyze_trade(inp)
    cf_res = CounterfactualService.analyze_post_exit_paths(
        trade_id="tr_ai_2",
        symbol="000001.SZ",
        exit_price=10.0,
        post_exit_prices=[],         # No post exit prices
        post_exit_bm_prices=[]
    )

    service = AITradeReviewService(is_test_env=True)
    review = await service.generate_review(attr_res, cf_res)

    assert review.confidence == ReviewConfidence.INSUFFICIENT_EVIDENCE
    assert review.grounding.is_sufficient is False
    assert "无法生成高置信度 AI 复盘" in review.summary
