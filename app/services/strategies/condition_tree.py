from typing import Dict, Any, List
import numpy as np
import pandas as pd


class ConditionTreeEvaluator:
    """向量化条件树计算器：安全无 exec/eval 评测 DataFrame"""

    @classmethod
    def evaluate(cls, df: pd.DataFrame, condition_node: Dict[str, Any]) -> pd.Series:
        """
        根据条件树节点，计算返回 boolean pd.Series (索引与 df 保持一致)。
        缺失值处理：凡因子值为 NaN 的，计算结果默认为 False。
        """
        if df.empty:
            return pd.Series(dtype=bool)

        if not condition_node:
            return pd.Series(True, index=df.index)

        op = condition_node.get("op", "").upper()

        if op in ("AND", "OR", "NOT"):
            children = condition_node.get("children", [])
            if op == "AND":
                res = pd.Series(True, index=df.index)
                for child in children:
                    res = res & cls.evaluate(df, child)
                return res
            elif op == "OR":
                res = pd.Series(False, index=df.index)
                for child in children:
                    res = res | cls.evaluate(df, child)
                return res
            elif op == "NOT":
                child_res = cls.evaluate(df, children[0])
                return ~child_res

        raw_op = condition_node.get("op")
        factor_id = condition_node.get("factor_id")
        val = condition_node.get("value")

        if not factor_id or factor_id not in df.columns:
            # 因子不存在时该条件直接判定为 False
            return pd.Series(False, index=df.index)

        series = df[factor_id]

        if raw_op == ">":
            res = series > val
        elif raw_op == ">=":
            res = series >= val
        elif raw_op == "<":
            res = series < val
        elif raw_op == "<=":
            res = series <= val
        elif raw_op == "==":
            res = series == val
        elif raw_op == "!=":
            res = series != val
        elif raw_op == "between":
            res = (series >= val[0]) & (series <= val[1])
        elif raw_op == "in":
            res = series.isin(val)
        elif raw_op == "percentile_gte":
            # 截面百分位计算
            pct = series.rank(pct=True, ascending=True)
            res = pct >= val
        elif raw_op == "zscore_gte":
            # 截面 Z-score 计算
            mean = series.mean()
            std = series.std(ddof=0)
            if std == 0 or np.isnan(std):
                z = pd.Series(0.0, index=series.index)
            else:
                z = (series - mean) / std
            res = z >= val
        else:
            res = pd.Series(False, index=df.index)

        # 任何涉及 NaN 值的评估结果均置为 False
        return res.fillna(False).astype(bool)
