"""Compatibility models for the extracted manual paper-trading domain."""

from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.models.symbol import Currency, Market


class PaperSymbol(BaseModel):
    """Canonical identity plus the legacy collection code representation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    market: Market
    symbol: str
    currency: Currency
    code: str


class PriceSnapshot(BaseModel):
    """A reusable quote contract; current APIs expose only its price."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    market: Market
    symbol: str
    price: float = Field(gt=0)
    quote_time: Optional[str] = None
    source: str
    quality: str = "valid"
    latency_ms: Optional[int] = Field(default=None, ge=0)


class PaperExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order: dict[str, Any]


class PaperRecoveryRecord(BaseModel):
    """Pending reconciliation work after a non-transactional partial write."""

    model_config = ConfigDict(extra="forbid")

    recovery_id: str = Field(default_factory=lambda: str(uuid4()))
    execution_id: str
    user_id: str
    operation: str
    failed_stage: str
    completed_stages: list[str]
    market: Optional[Market] = None
    symbol: Optional[str] = None
    quantity: Optional[int] = None
    price: Optional[float] = None
    error_type: str
    status: str = "pending"
    created_at: str
