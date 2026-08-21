from typing import List, Set, Dict
from app.services.factors.registry import global_factor_registry, FactorRegistry


class FactorDAGPlanner:
    """因子依赖 DAG 规划器"""

    def __init__(self, registry: FactorRegistry = global_factor_registry):
        self.registry = registry

    def plan_execution_order(self, factor_ids: List[str]) -> List[str]:
        """规划因子的依赖拓扑排序"""
        visited: Set[str] = set()
        order: List[str] = []

        def visit(fid: str, path: Set[str]):
            if fid in path:
                raise ValueError(f"Circular dependency detected in factor DAG: {fid}")
            if fid not in visited:
                path.add(fid)
                defn = self.registry.get_by_id(fid)
                if defn:
                    for dep in getattr(defn, "dependencies", []):
                        visit(dep, path)
                path.remove(fid)
                visited.add(fid)
                order.append(fid)

        for fid in factor_ids:
            visit(fid, set())

        return order
