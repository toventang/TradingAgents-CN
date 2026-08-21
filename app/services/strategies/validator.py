from typing import Tuple
from typing import Dict, Any, List, Optional, Set
from pydantic import BaseModel, Field
from app.services.factors.registry import global_factor_registry


class DSLValidationError(Exception):
    """Strategy DSL 校验错误"""
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


ALLOWED_LOGICAL_OPS = {"AND", "OR", "NOT"}
ALLOWED_COMPARISON_OPS = {">", ">=", "<", "<=", "==", "!=", "in", "between", "percentile_gte", "zscore_gte"}


class StrategyDSLValidator:
    """封闭化策略 DSL 校验器：保障选股精准度、语法安全性与参数合法性"""

    def __init__(self, max_depth: int = 10, max_nodes: int = 200):
        self.max_depth = max_depth
        self.max_nodes = max_nodes

    def validate_strategy_spec(self, spec: Dict[str, Any]) -> Set[str]:
        """
        校验完整 Strategy Spec 字典。
        返回该 Strategy Spec 引用的所有因子 ID 集合（用于上游依赖检查）。
        """
        if not isinstance(spec, dict):
            raise DSLValidationError("Strategy spec must be a dictionary")

        referenced_factors: Set[str] = set()

        # 1. 校验权重/因子定义 (weights)
        weights = spec.get("weights")
        if weights:
            if not isinstance(weights, dict):
                raise DSLValidationError("spec.weights must be a dictionary of factor_id -> weight")
            for factor_id, w in weights.items():
                if not isinstance(w, (int, float)):
                    raise DSLValidationError(f"Weight for factor '{factor_id}' must be a number, got {type(w)}")
                self._check_factor_registered(factor_id)
                referenced_factors.add(factor_id)

        # 2. 校验条件树 (conditions)
        conditions = spec.get("conditions")
        if conditions:
            tree_factors, node_count, depth = self._validate_condition_node(conditions, current_depth=1)
            if depth > self.max_depth:
                raise DSLValidationError(f"Condition tree depth {depth} exceeds max limit {self.max_depth}")
            if node_count > self.max_nodes:
                raise DSLValidationError(f"Condition tree node count {node_count} exceeds max limit {self.max_nodes}")
            referenced_factors.update(tree_factors)

        # 3. 校验风控与选股参数 (rules/parameters)
        rules = spec.get("rules", {})
        if not isinstance(rules, dict):
            raise DSLValidationError("spec.rules must be a dictionary")

        top_k = rules.get("top_k")
        if top_k is not None and (not isinstance(top_k, int) or top_k <= 0):
            raise DSLValidationError(f"top_k must be a positive integer, got {top_k}")

        top_percent = rules.get("top_percent")
        if top_percent is not None and (not isinstance(top_percent, (int, float)) or not (0.0 < top_percent <= 1.0)):
            raise DSLValidationError(f"top_percent must be a float between 0.0 and 1.0, got {top_percent}")

        return referenced_factors

    def _validate_condition_node(self, node: Dict[str, Any], current_depth: int) -> Tuple[Set[str], int, int]:
        """
        递归校验条件节点。
        返回: (referenced_factors, node_count, max_depth_reached)
        """
        if not isinstance(node, dict):
            raise DSLValidationError(f"Condition node must be a dict, got {type(node)}")

        op = node.get("op")
        if not op or not isinstance(op, str):
            raise DSLValidationError("Condition node missing string 'op' field")

        op_upper = op.upper()
        factors: Set[str] = set()
        node_count = 1
        max_depth = current_depth

        if op_upper in ALLOWED_LOGICAL_OPS:
            children = node.get("children")
            if not isinstance(children, list) or len(children) == 0:
                raise DSLValidationError(f"Logical node '{op_upper}' must contain a non-empty 'children' list")

            if op_upper == "NOT" and len(children) != 1:
                raise DSLValidationError("Logical 'NOT' node must contain exactly one child")

            for child in children:
                child_factors, child_nodes, child_depth = self._validate_condition_node(child, current_depth + 1)
                factors.update(child_factors)
                node_count += child_nodes
                max_depth = max(max_depth, child_depth)

            return factors, node_count, max_depth

        elif op in ALLOWED_COMPARISON_OPS:
            factor_id = node.get("factor_id")
            if not factor_id or not isinstance(factor_id, str):
                raise DSLValidationError(f"Comparison node '{op}' missing string 'factor_id'")

            self._check_factor_registered(factor_id)
            factors.add(factor_id)

            val = node.get("value")
            if val is None:
                raise DSLValidationError(f"Comparison node '{op}' missing 'value'")

            if op == "between":
                if not isinstance(val, (list, tuple)) or len(val) != 2:
                    raise DSLValidationError("Operator 'between' requires a value list of [min, max]")
                if not (isinstance(val[0], (int, float)) and isinstance(val[1], (int, float))):
                    raise DSLValidationError("Operator 'between' range limits must be numeric")
                if val[0] > val[1]:
                    raise DSLValidationError(f"Impossible condition: min ({val[0]}) > max ({val[1]}) in 'between'")
            elif op == "in":
                if not isinstance(val, (list, tuple)):
                    raise DSLValidationError("Operator 'in' requires a list of values")
            else:
                if not isinstance(val, (int, float)):
                    raise DSLValidationError(f"Operator '{op}' value must be numeric, got {type(val)}")

            return factors, node_count, max_depth

        else:
            raise DSLValidationError(f"Unsupported or unwhitelisted operator '{op}'")

    def _check_factor_registered(self, factor_id: str):
        defn = global_factor_registry.get_by_id(factor_id)
        if not defn:
            raise DSLValidationError(f"Factor '{factor_id}' is not registered in the factor catalog")
