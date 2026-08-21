"""Documented consistency boundary for legacy multi-collection writes."""

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.models.paper import PaperRecoveryRecord, PaperSymbol

logger = logging.getLogger("paper_trading")


class PaperConsistencyBoundary:
    """Persist recovery work when Mongo transactions are not available.

    The legacy collections are updated in their historical order. Every failure
    is raised to the caller. If one or more earlier stages succeeded, a pending
    record in paper_consistency_recovery identifies the exact boundary that
    needs reconciliation; no endpoint reports success after a partial write.
    """

    COLLECTION = "paper_consistency_recovery"

    def __init__(self, database: Any):
        self.database = database

    async def record_failure(
        self,
        *,
        execution_id: str,
        user_id: str,
        operation: str,
        failed_stage: str,
        completed_stages: list[str],
        error: Exception,
        identity: Optional[PaperSymbol] = None,
        quantity: Optional[int] = None,
        price: Optional[float] = None,
        created_at: Optional[str] = None,
    ) -> str:
        record = PaperRecoveryRecord(
            execution_id=execution_id,
            user_id=user_id,
            operation=operation,
            failed_stage=failed_stage,
            completed_stages=list(completed_stages),
            market=identity.market if identity else None,
            symbol=identity.symbol if identity else None,
            quantity=quantity,
            price=price,
            error_type=type(error).__name__,
            created_at=created_at
            or datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
        )
        document = record.model_dump(mode="python", exclude_none=True)
        if "market" in document:
            document["market"] = record.market.value
        try:
            await self.database[self.COLLECTION].insert_one(document)
        except Exception as recovery_error:
            logger.error(
                "Paper recovery record failed (type=%s)",
                type(recovery_error).__name__,
            )
        return record.recovery_id
