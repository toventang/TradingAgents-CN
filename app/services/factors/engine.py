import asyncio
import hashlib
import json
import logging
import numpy as np
import pandas as pd
from typing import List, Dict, Any, Optional, Callable, Awaitable
from app.services.factors.registry import global_factor_registry
from app.services.factors.calculators.price import calculate_price_factors
from app.services.factors.calculators.trend import calculate_trend_factors
from app.services.factors.calculators.momentum import calculate_momentum_factors
from app.services.factors.calculators.volatility import calculate_volatility_factors
from app.services.factors.calculators.liquidity import calculate_liquidity_factors
from app.services.factors.calculators.fundamental import calculate_fundamental_factors
from app.services.factors.calculators.sentiment import calculate_sentiment_factors
from app.services.factors.calculators.cross_section import calculate_cross_sectional_factors

logger = logging.getLogger("app.services.factors.engine")


class FactorExecutionEngine:
    """分块、并发因子计算引擎"""

    def __init__(self, chunk_size: int = 100):
        self.chunk_size = chunk_size

    def compute_single_symbol_factors(
        self,
        df: pd.DataFrame,
        factor_ids: Optional[List[str]] = None,
        financial_data: Optional[Dict[str, Any]] = None,
        sentiment_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, pd.Series]:
        """对单个股票的时间序列数据计算所有或指定因子"""
        if df.empty:
            return {}

        results: Dict[str, pd.Series] = {}

        # 逐组计算
        results.update(calculate_price_factors(df))
        results.update(calculate_trend_factors(df))
        results.update(calculate_momentum_factors(df))
        results.update(calculate_volatility_factors(df))
        results.update(calculate_liquidity_factors(df))
        results.update(calculate_fundamental_factors(df, financial_data=financial_data))
        results.update(calculate_sentiment_factors(df, sentiment_data=sentiment_data))

        if factor_ids:
            return {fid: results[fid] for fid in factor_ids if fid in results}

        return results

    async def compute_universe_batch(
        self,
        symbols: List[str],
        market: str,
        factor_ids: List[str],
        data_provider: Callable[[str, str], Awaitable[pd.DataFrame]],
        progress_cb: Optional[Callable[[float, str, str], Awaitable[None]]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None
    ) -> Dict[str, Dict[str, pd.Series]]:
        """按 100 股分块并行计算 Universe 因子，支持进度与取消"""
        all_results: Dict[str, Dict[str, pd.Series]] = {}
        total_symbols = len(symbols)

        if total_symbols == 0:
            return {}

        # 分块 (Chunks of 100)
        chunks = [symbols[i : i + self.chunk_size] for i in range(0, total_symbols, self.chunk_size)]
        completed_count = 0

        for chunk_idx, chunk in enumerate(chunks):
            if is_cancelled and is_cancelled():
                logger.info("🛑 Factor compute engine task cancelled by user")
                break

            for sym in chunk:
                if is_cancelled and is_cancelled():
                    break
                df = await data_provider(sym, market)
                sym_factors = self.compute_single_symbol_factors(df, factor_ids=factor_ids)
                all_results[sym] = sym_factors
                completed_count += 1

            if progress_cb:
                prog = round(completed_count / total_symbols, 2)
                await progress_cb(prog, f"chunk_{chunk_idx+1}", f"Computed {completed_count}/{total_symbols} symbols")

        # 横截面因子二次计算（若存在且 valid 股票满足要求）
        cross_factor_ids = [fid for fid in factor_ids if global_factor_registry.get_by_id(fid) and global_factor_registry.get_by_id(fid).category.value == "cross_sectional"]
        if cross_factor_ids and all_results:
            # 提取横截面截面数据
            latest_rows = {}
            for sym, fdict in all_results.items():
                latest_rows[sym] = {fid: (s.iloc[-1] if len(s) > 0 else np.nan) for fid, s in fdict.items()}

            matrix_df = pd.DataFrame.from_dict(latest_rows, orient="index")
            cs_results = calculate_cross_sectional_factors(matrix_df)

            for sym in all_results.keys():
                for cs_fid in cross_factor_ids:
                    if cs_fid in cs_results:
                        val = cs_results[cs_fid].get(sym, np.nan)
                        all_results[sym][cs_fid] = pd.Series([val])

        return all_results
