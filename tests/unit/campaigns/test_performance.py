import pytest
from app.models.backtest import EquityPoint
from app.services.campaigns.performance_service import CampaignPerformanceService


@pytest.mark.asyncio
async def test_campaign_performance_and_opportunity_cost():
    service = CampaignPerformanceService()

    equity_curve = [
        EquityPoint(trade_date="2026-01-01", cash=100000.0, market_value=0.0, total_equity=100000.0, benchmark_equity=1000.0, daily_return=0.0, benchmark_return=0.0),
        EquityPoint(trade_date="2026-01-02", cash=100000.0, market_value=10000.0, total_equity=110000.0, benchmark_equity=1020.0, daily_return=0.10, benchmark_return=0.02)
    ]

    res = await service.calculate_campaign_performance(
        campaign_id="camp_perf_1",
        portfolio_id="p1",
        initial_capital=100000.0,
        daily_equity_curve=equity_curve
    )

    assert "metrics" in res
    assert "opportunity_cost" in res
    assert res["opportunity_cost"]["benchmark_excess"] == 0.08
    assert res["opportunity_cost"]["cash_baseline_excess"] == 0.10
