from typing import List, Dict, Optional
from app.models.factor import FactorDefinition, FactorCategory
from app.services.factors.definitions.catalog import FACTOR_CATALOG


class FactorRegistry:
    """静态 171 因子注册表"""

    def __init__(self, catalog: Optional[List[FactorDefinition]] = None):
        self._definitions: Dict[str, FactorDefinition] = {}
        items = catalog or FACTOR_CATALOG

        for item in items:
            if item.factor_id in self._definitions:
                raise ValueError(f"Duplicate factor_id detected in catalog: {item.factor_id}")
            self._definitions[item.factor_id] = item

    def get_all(self) -> List[FactorDefinition]:
        return list(self._definitions.values())

    def get_by_id(self, factor_id: str) -> Optional[FactorDefinition]:
        return self._definitions.get(factor_id)

    def get_by_category(self, category: str | FactorCategory) -> List[FactorDefinition]:
        cat_val = category.value if isinstance(category, FactorCategory) else category
        return [f for f in self._definitions.values() if f.category == cat_val or f.category.value == cat_val]

    def get_by_market(self, market: str) -> List[FactorDefinition]:
        mkt = market.upper()
        return [f for f in self._definitions.values() if mkt in f.supported_markets]

    @property
    def count(self) -> int:
        return len(self._definitions)


# 全局单例
global_factor_registry = FactorRegistry()
