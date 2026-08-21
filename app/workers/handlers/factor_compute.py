import uuid
import hashlib
import json
import logging
import pandas as pd
from typing import Dict, Any
from app.models.domain_task import TaskType
from app.services.domain_tasks.handler_registry import (
    TaskContext,
    ProgressCallback,
    CancellationChecker,
    global_handler_registry
)
from app.services.factors.engine import FactorExecutionEngine
from app.repositories.factor_repository import FactorRepository

logger = logging.getLogger("app.workers.handlers.factor_compute")


class FactorComputeHandler:
    """因子计算任务 Handler"""

    def __init__(self, engine: FactorExecutionEngine = None, repo: FactorRepository = None):
        self.engine = engine or FactorExecutionEngine()
        self.repo = repo or FactorRepository()

    async def execute(
        self,
        payload: Dict[str, Any],
        context: TaskContext,
        progress: ProgressCallback,
        is_cancelled: CancellationChecker
    ) -> Dict[str, Any]:
        """执行因子计算逻辑并持久化快照"""
        symbols = payload.get("symbols", [])
        market = payload.get("market", "CN")
        factor_ids = payload.get("factor_ids", ["ret_1d", "sma_5"])

        await progress(0.05, "init", f"Initializing factor compute for {len(symbols)} symbols")

        if is_cancelled():
            return {}

        async def dummy_data_provider(sym: str, mkt: str) -> pd.DataFrame:
            # 基础模拟 K 线数据
            dates = pd.date_range("2025-01-01", periods=30, freq="B")
            close = pd.Series([10.0 + i * 0.1 for i in range(30)], index=dates)
            return pd.DataFrame({
                "open": close - 0.05,
                "high": close + 0.2,
                "low": close - 0.2,
                "close": close,
                "volume": 10000.0,
                "amount": 100000.0,
                "pct_chg": 1.0
            })

        async def engine_progress(prog: float, stage: str, msg: str):
            await progress(0.05 + prog * 0.85, stage, msg)

        results = await self.engine.compute_universe_batch(
            symbols=symbols,
            market=market,
            factor_ids=factor_ids,
            data_provider=dummy_data_provider,
            progress_cb=engine_progress,
            is_cancelled=is_cancelled
        )

        if is_cancelled():
            return {}

        await progress(0.95, "saving_snapshot", "Saving immutable factor snapshot")

        # Serialized result map for snapshot
        serialized_data = {}
        for sym, fdict in results.items():
            serialized_data[sym] = {
                fid: s.tolist() if hasattr(s, "tolist") else list(s)
                for fid, s in fdict.items()
            }

        snapshot_id = f"snap_{uuid.uuid4().hex[:16]}"
        raw_bytes = json.dumps(serialized_data, sort_keys=True, default=str).encode("utf-8")
        checksum = hashlib.sha256(raw_bytes).hexdigest()

        await self.repo.save_snapshot(
            snapshot_id=snapshot_id,
            user_id=context.user_id,
            market=market,
            factor_ids=factor_ids,
            data=serialized_data,
            checksum=checksum,
            status="ready"
        )

        await progress(1.0, "succeeded", "Factor compute completed")

        return {
            "snapshot_id": snapshot_id,
            "factor_count": len(factor_ids),
            "symbol_count": len(symbols),
            "checksum": checksum
        }


# Register with global registry
factor_compute_handler = FactorComputeHandler()
global_handler_registry.register(TaskType.FACTOR_COMPUTE, factor_compute_handler)
