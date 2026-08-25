import pytest
from app.services.config.capacity_budget import (
    CapacityBudgetService,
    CapacityBudgetExceededError,
    CapacityBudgetConfig
)


def test_capacity_budget_factor_symbols_limit():
    # Valid chunk size (<= 100)
    CapacityBudgetService.validate_factor_symbols(100)

    # Exceeded chunk size (> 100) -> Raises CapacityBudgetExceededError
    with pytest.raises(CapacityBudgetExceededError) as exc:
        CapacityBudgetService.validate_factor_symbols(101)

    assert exc.value.resource == "factor_symbols"
    assert exc.value.limit_val == 100


def test_capacity_budget_backtest_days_limit():
    # Valid backtest days (<= 500)
    CapacityBudgetService.validate_backtest_days(500)

    # Exceeded backtest days (> 500) -> Raises CapacityBudgetExceededError
    with pytest.raises(CapacityBudgetExceededError) as exc:
        CapacityBudgetService.validate_backtest_days(501)

    assert exc.value.resource == "backtest_days"
    assert exc.value.limit_val == 500


def test_capacity_budget_active_campaigns_limit():
    # Valid campaign count (< 10)
    CapacityBudgetService.validate_active_campaign_count(9)

    # Reached or exceeded limit (>= 10) -> Raises CapacityBudgetExceededError
    with pytest.raises(CapacityBudgetExceededError) as exc:
        CapacityBudgetService.validate_active_campaign_count(10)

    assert exc.value.resource == "active_campaigns"
    assert exc.value.limit_val == 10
