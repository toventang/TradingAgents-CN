import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional
import numpy as np
import pandas as pd

from app.models.strategy import StrategyVersion, StrategySignal, UniverseSnapshot
from app.services.strategies.validator import StrategyDSLValidator
from app.services.strategies.condition_tree import ConditionTreeEvaluator
from app.utils.timezone import now_tz


class DeterministicSignalEngine:
    """确定性选股与信号引擎：无未来函数 (No Look-Ahead)、去极值标准化、确定性排序与理由码"""

    def __init__(self, validator: Optional[StrategyDSLValidator] = None):
        self.validator = validator or StrategyDSLValidator()

    def generate_signals(
        self,
        version: StrategyVersion,
        user_id: str,
        as_of: datetime,
        factor_values_df: pd.DataFrame
    ) -> List[StrategySignal]:
        """
        根据策略版本与特定 as_of 时间点的因子矩阵计算选股信号。

        factor_values_df 格式要求:
        - index: symbol (如 '600000.SH', '000001.SZ')
        - columns: 各种 factor_id (如 'close', 'macd_hist', 'pe_ratio')
        """
        if factor_values_df.empty:
            return []

        spec = {
            "weights": version.parameters.get("weights", {}),
            "conditions": version.rules.get("conditions", {}),
            "rules": version.rules
        }

        # 1. 校验 spec DSL
        self.validator.validate_strategy_spec(spec)

        df = factor_values_df.copy()
        symbols = list(df.index)

        # 限制只在选股宇宙内的 symbol 评测
        if version.universe and version.universe.symbols:
            univ_set = set(version.universe.symbols)
            df = df[df.index.isin(univ_set)]

        if df.empty:
            return []

        # 2. 条件过滤 (Condition Evaluation)
        conditions = version.rules.get("conditions")
        if conditions:
            passed_mask = ConditionTreeEvaluator.evaluate(df, conditions)
        else:
            passed_mask = pd.Series(True, index=df.index)

        # 3. 极值处理与标准化 (Winsorization & Z-Score normalization)
        weights = version.parameters.get("weights", {})
        scores = pd.Series(0.0, index=df.index)

        if weights:
            normalized_df = pd.DataFrame(index=df.index)
            for factor_id, w in weights.items():
                if factor_id in df.columns:
                    s = df[factor_id].copy()
                    # 去极值 (Quantile Winsorization 1% - 99%)
                    q_low = s.quantile(0.01)
                    q_high = s.quantile(0.99)
                    s_clipped = s.clip(lower=q_low, upper=q_high)

                    # Z-Score 标准化
                    mean = s_clipped.mean()
                    std = s_clipped.std(ddof=0)
                    if std > 0 and not np.isnan(std):
                        norm_s = (s_clipped - mean) / std
                    else:
                        norm_s = pd.Series(0.0, index=df.index)

                    normalized_df[factor_id] = norm_s
                    scores += norm_s.fillna(0.0) * w

        # 4. 排序与确定性 Tie-Breaking
        # 结果 DataFrame: symbol, score, passed
        res_df = pd.DataFrame({
            "score": scores,
            "passed": passed_mask
        }, index=df.index)

        # 确定性排序: score DESC, symbol ASC
        res_df["symbol_str"] = res_df.index.astype(str)
        res_df.sort_values(by=["score", "symbol_str"], ascending=[False, True], inplace=True)

        top_k = version.rules.get("top_k")
        top_percent = version.rules.get("top_percent")

        total_univ = len(res_df)
        if top_k is not None:
            max_selected = top_k
        elif top_percent is not None:
            max_selected = max(1, int(total_univ * top_percent))
        else:
            max_selected = total_univ

        signals: List[StrategySignal] = []
        selected_count = 0

        for rank, (symbol, row) in enumerate(res_df.iterrows(), start=1):
            sc = float(row["score"])
            passed = bool(row["passed"])

            if not passed:
                sig_type = "hold"
                reason = "CONDITION_FAILED"
                target_weight = 0.0
            elif selected_count < max_selected:
                sig_type = "buy"
                reason = "OK"
                selected_count += 1
                target_weight = round(1.0 / max_selected, 4)
            else:
                sig_type = "hold"
                reason = "RANK_CUTOFF"
                target_weight = 0.0

            sig = StrategySignal(
                signal_id=f"sig_{uuid.uuid4().hex[:12]}",
                strategy_id=version.strategy_id,
                version_num=version.version_num,
                user_id=user_id,
                symbol=str(symbol),
                market=version.universe.market if version.universe else "CN",
                score=round(sc, 6),
                rank=rank,
                target_weight=target_weight,
                signal_type=sig_type,
                reason_code=reason,
                created_at=as_of
            )
            signals.append(sig)

        return signals
