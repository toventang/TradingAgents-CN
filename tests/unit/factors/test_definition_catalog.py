import pytest
from app.services.factors.registry import global_factor_registry
from app.models.factor import FactorCategory

def test_exact_171_factor_catalog_count():
    assert global_factor_registry.count == 171

def test_group_factor_counts():
    counts = {
        FactorCategory.PRICE: 18,
        FactorCategory.TREND: 23,
        FactorCategory.MOMENTUM: 18,
        FactorCategory.VOLATILITY: 20,
        FactorCategory.LIQUIDITY: 19,
        FactorCategory.VALUATION: 15,
        FactorCategory.QUALITY: 20,
        FactorCategory.GROWTH: 16,
        FactorCategory.SENTIMENT: 12,
        FactorCategory.CROSS_SECTIONAL: 10,
    }

    for cat, expected in counts.items():
        factors = global_factor_registry.get_by_category(cat)
        assert len(factors) == expected, f"Category {cat.value} expected {expected}, got {len(factors)}"

    total_sum = sum(len(global_factor_registry.get_by_category(cat)) for cat in FactorCategory)
    assert total_sum == 171
