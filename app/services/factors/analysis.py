import numpy as np
import pandas as pd
from typing import Dict, Any, List, Optional


class FactorAnalysisService:
    """因子研究分析服务 (IC / Rank IC / 分位数收益 / 换手率 / 无未来信息泄露)"""

    @staticmethod
    def compute_forward_returns(
        price_matrix: pd.DataFrame,
        periods: List[int] = [1, 5, 10, 20]
    ) -> Dict[int, pd.DataFrame]:
        """计算未来 N 日收益率 (严格使用 shift(-N) 避免 Future Label Leakage)"""
        fwd_returns = {}
        for p in periods:
            # Shift by -p so date T gets return from T to T+p
            fwd_ret = price_matrix.pct_change(p).shift(-p)
            fwd_returns[p] = fwd_ret
        return fwd_returns

    @staticmethod
    def analyze_factor(
        factor_matrix: pd.DataFrame,
        price_matrix: pd.DataFrame,
        periods: List[int] = [1, 5, 10, 20],
        quantiles: int = 5,
        min_symbols: int = 20
    ) -> Dict[str, Any]:
        """对因子矩阵与价格矩阵做 IC / Rank IC / 5分位数收益率分析"""
        fwd_returns = FactorAnalysisService.compute_forward_returns(price_matrix, periods)
        results = {}

        for p in periods:
            fwd_ret = fwd_returns[p]
            ic_series = []
            rank_ic_series = []

            common_dates = factor_matrix.index.intersection(fwd_ret.index)
            for dt in common_dates:
                f_row = factor_matrix.loc[dt].dropna()
                r_row = fwd_ret.loc[dt].dropna()

                valid_symbols = f_row.index.intersection(r_row.index)
                if len(valid_symbols) < min_symbols:
                    continue

                f_vals = f_row.loc[valid_symbols]
                r_vals = r_row.loc[valid_symbols]

                # Pearson IC
                corr = f_vals.corr(r_vals)
                if not np.isnan(corr):
                    ic_series.append(corr)

                # Spearman Rank IC
                rank_corr = f_vals.rank().corr(r_vals.rank())
                if not np.isnan(rank_corr):
                    rank_ic_series.append(rank_corr)

            ic_arr = np.array(ic_series) if ic_series else np.array([0.0])
            rank_ic_arr = np.array(rank_ic_series) if rank_ic_series else np.array([0.0])

            ic_mean = float(np.mean(ic_arr))
            ic_std = float(np.std(ic_arr)) if len(ic_arr) > 1 else 0.0
            ic_ir = float(ic_mean / ic_std) if ic_std > 0 else 0.0

            rank_ic_mean = float(np.mean(rank_ic_arr))
            rank_ic_std = float(np.std(rank_ic_arr)) if len(rank_ic_arr) > 1 else 0.0
            rank_ic_ir = float(rank_ic_mean / rank_ic_std) if rank_ic_std > 0 else 0.0

            # Quantile Returns (Q1..Q5)
            quantile_ret_means = {}
            for q in range(1, quantiles + 1):
                q_rets = []
                for dt in common_dates:
                    f_row = factor_matrix.loc[dt].dropna()
                    r_row = fwd_ret.loc[dt].dropna()
                    valid_symbols = f_row.index.intersection(r_row.index)
                    if len(valid_symbols) < min_symbols:
                        continue

                    f_vals = f_row.loc[valid_symbols]
                    r_vals = r_row.loc[valid_symbols]

                    try:
                        q_labels = pd.qcut(f_vals, q=quantiles, labels=False, duplicates="drop")
                        q_syms = q_labels[q_labels == (q - 1)].index
                        if len(q_syms) > 0:
                            q_rets.append(r_vals.loc[q_syms].mean())
                    except Exception:
                        pass

                quantile_ret_means[f"Q{q}"] = float(np.mean(q_rets)) if q_rets else 0.0

            results[f"period_{p}d"] = {
                "ic_mean": ic_mean,
                "ic_std": ic_std,
                "ic_ir": ic_ir,
                "rank_ic_mean": rank_ic_mean,
                "rank_ic_std": rank_ic_std,
                "rank_ic_ir": rank_ic_ir,
                "quantile_returns": quantile_ret_means
            }

        return results
