import pytest
from app.models.attribution import TradeReviewInput, CauseCategory
from app.services.learning.attribution import TradeAttributionService


def test_trade_attribution_mae_mfe_and_causes():
    inp = TradeReviewInput(
        trade_id="tr_001",
        symbol="600000.SH",
        entry_date="2026-01-01",
        exit_date="2026-01-05",
        entry_price=10.0,
        exit_price=9.0,               # -10% realized loss
        quantity=1000,
        daily_prices=[10.0, 10.8, 8.5, 9.2, 9.0],      # max=10.8 (+8% MFE), min=8.5 (-15% MAE)
        daily_benchmark_prices=[1000.0, 980.0, 930.0, 940.0, 920.0], # -8% benchmark drop
        execution_slippage=0.01
    )

    res = TradeAttributionService.analyze_trade(inp)

    assert res.trade_id == "tr_001"
    assert res.metrics.realized_pnl_pct == -0.10
    assert res.metrics.mfe_pct == 0.08
    assert res.metrics.mae_pct == -0.15
    assert res.metrics.benchmark_return_pct == -0.08
    assert res.metrics.excess_return_pct == -0.02
    assert res.primary_cause == CauseCategory.MARKET_TREND


def test_trade_attribution_no_future_leakage():
    # Verify holding period price bounds only
    inp = TradeReviewInput(
        trade_id="tr_002",
        symbol="000001.SZ",
        entry_date="2026-01-01",
        exit_date="2026-01-03",
        entry_price=10.0,
        exit_price=12.0,              # +20% profit
        quantity=1000,
        daily_prices=[10.0, 11.0, 12.0], # Holding prices only
        daily_benchmark_prices=[1000.0, 1010.0, 1020.0]
    )

    res = TradeAttributionService.analyze_trade(inp)

    assert res.metrics.mfe_pct == 0.20
    assert res.metrics.mae_pct == 0.0
    assert res.metrics.realized_pnl_pct == 0.20
