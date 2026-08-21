import numpy as np
import pandas as pd
from typing import Dict, Any, Tuple, List, Optional
from app.models.factor import CompositeFactorSpec, AllowedTransform
from app.services.factors.registry import global_factor_registry
from app.core.database import get_mongo_db
from app.utils.timezone import now_tz


class CompositeFactorService:
    """组合因子 DSL 校验与计算服务（安全闭环，防 Code Injection）"""

    def __init__(self, db=None):
        self._db = db

    def get_db(self):
        return self._db if self._db is not None else get_mongo_db()

    def validate_spec(self, spec: CompositeFactorSpec) -> Dict[str, float]:
        """校验 Spec 合法性并归一化权重"""
        if not spec.base_factors:
            raise ValueError("Composite factor must specify at least one base_factor")

        # 检查基础因子是否存在
        for bf in spec.base_factors:
            if not global_factor_registry.get_by_id(bf):
                raise ValueError(f"Unknown base factor_id: {bf}")

        # 校验变换白名单
        for t in spec.transforms:
            if t not in AllowedTransform:
                raise ValueError(f"Unwhitelisted transform operation: {t}")

        # 权重计算与归一化
        weights = spec.weights or {bf: 1.0 / len(spec.base_factors) for bf in spec.base_factors}
        total_w = sum(abs(w) for w in weights.values())
        if total_w == 0:
            norm_weights = {bf: 1.0 / len(spec.base_factors) for bf in spec.base_factors}
        else:
            norm_weights = {bf: weights[bf] / total_w for bf in spec.base_factors}

        return norm_weights

    def compute_composite(
        self,
        spec: CompositeFactorSpec,
        factor_matrix: pd.DataFrame
    ) -> Tuple[pd.Series, Dict[str, pd.Series]]:
        """基于白名单算子计算组合因子与贡献度分解（绝对不使用 eval/exec）"""
        weights = self.validate_spec(spec)
        contributions: Dict[str, pd.Series] = {}

        for bf in spec.base_factors:
            if bf not in factor_matrix:
                s = pd.Series(np.nan, index=factor_matrix.index)
            else:
                s = factor_matrix[bf].copy()

            # 应用白名单变换
            for t in spec.transforms:
                if t == AllowedTransform.ZSCORE:
                    std = s.std()
                    s = (s - s.mean()) / std if (not pd.isna(std) and std != 0) else pd.Series(np.nan, index=s.index)
                elif t == AllowedTransform.RANK:
                    s = s.rank(pct=True)
                elif t == AllowedTransform.NORMALIZE:
                    s_min, s_max = s.min(), s.max()
                    s = (s - s_min) / (s_max - s_min) if (s_max > s_min) else pd.Series(np.nan, index=s.index)
                elif t == AllowedTransform.WINSORIZE:
                    m, std = s.mean(), s.std()
                    s = s.clip(lower=m - 3.0 * std, upper=m + 3.0 * std)

            w = weights.get(bf, 0.0)
            contributions[bf] = s * w

        composite_series = pd.DataFrame(contributions).sum(axis=1)
        return composite_series, contributions

    async def save_user_composite(self, user_id: str, spec: CompositeFactorSpec) -> Dict[str, Any]:
        """保存用户自定义组合因子定义"""
        self.validate_spec(spec)
        db = self.get_db()

        composite_id = f"composite_{user_id}_{spec.name.replace(' ', '_')}"
        doc = {
            "composite_id": composite_id,
            "user_id": user_id,
            "spec": spec.model_dump(),
            "created_at": now_tz().isoformat()
        }

        await db["user_composite_factors"].update_one(
            {"composite_id": composite_id, "user_id": user_id},
            {"$set": doc},
            upsert=True
        )
        return doc

    async def get_user_composite(self, composite_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        """获取属于特定用户的组合因子"""
        db = self.get_db()
        doc = await db["user_composite_factors"].find_one({"composite_id": composite_id, "user_id": user_id})
        if doc and "_id" in doc:
            doc.pop("_id")
        return doc
