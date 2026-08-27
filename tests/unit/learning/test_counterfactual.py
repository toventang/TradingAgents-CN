import pytest
from app.models.attribution import PostExitWindow, MissedUpsideSeverity
from app.services.learning.counterfactual import CounterfactualService


def test_counterfactual_service_window_analysis():
    # Simulate 60-day post exit price trend (stock rises +30% in 60d while benchmark rises +5%)
    post_exit_prices = [10.0 + (i * 0.05) for i in range(1, 61)]  # Day 5 = 10.25, Day 10 = 10.50, Day 20 = 11.0, Day 60 = 13.0
    post_exit_bm = [1000.0 + (i * 0.83) for i in range(1, 61)]   # Day 60 = 1050.0 (+5%)

    res = CounterfactualService.analyze_post_exit_paths(
        trade_id="tr_cf_1",
        symbol="600000.SH",
        exit_price=10.0,
        post_exit_prices=post_exit_prices,
        post_exit_bm_prices=post_exit_bm
    )

    assert res.trade_id == "tr_cf_1"
    assert res.is_legal_tradeable is True
    assert len(res.paths) == 4
    assert res.severity == MissedUpsideSeverity.SEVERE_MISSED_UPSIDE

    path_60d = res.paths[PostExitWindow.DAYS_60]
    assert path_60d.post_exit_price == 13.0
    assert path_60d.return_after_exit_pct == 0.30
    assert path_60d.excess_return_pct == 0.25
