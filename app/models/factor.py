"""Static, executable-free factor definition models."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    field_validator,
    model_validator,
)

from app.models.symbol import Market


class FactorCategory(str, Enum):
    PRICE = "price"
    TREND = "trend"
    MOMENTUM = "momentum"
    VOLATILITY = "volatility"
    LIQUIDITY = "liquidity"
    VALUATION = "valuation"
    QUALITY = "quality"
    GROWTH = "growth"
    SENTIMENT = "sentiment"
    EVENT = "event"
    CROSS_SECTION = "cross_section"
    CROSS_SECTIONAL = "cross_section"
    COMPOSITE = "composite"


class FactorGroup(str, Enum):
    RETURN_PRICE = "return_price"
    TREND = "trend"
    MOMENTUM = "momentum"
    VOLATILITY_RISK = "volatility_risk"
    LIQUIDITY = "liquidity"
    VALUATION = "valuation"
    QUALITY = "quality"
    GROWTH = "growth"
    SENTIMENT_EVENT = "sentiment_event"
    CROSS_COMPOSITE = "cross_composite"


class FactorFrequency(str, Enum):
    DAILY = "daily"
    INTRADAY = "intraday"
    QUARTERLY = "quarterly"


class FactorDirection(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


class WinsorizeMethod(str, Enum):
    NONE = "none"
    MAD = "mad"
    QUANTILE = "quantile"


class NormalizeMethod(str, Enum):
    NONE = "none"
    ZSCORE = "zscore"
    RANK = "rank"
    ROBUST_ZSCORE = "robust_zscore"


class MissingValuePolicy(str, Enum):
    DROP = "drop"
    NEUTRAL = "neutral"
    INDUSTRY_MEDIAN = "industry_median"
    ZERO = "zero"


class FactorStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"


class ParameterType(str, Enum):
    INTEGER = "integer"
    NUMBER = "number"
    STRING = "string"
    BOOLEAN = "boolean"
    OBJECT = "object"


class ParameterSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: ParameterType
    required: bool = False
    minimum: float | None = None
    maximum: float | None = None
    min_properties: int | None = Field(default=None, ge=0)
    choices: tuple[Any, ...] = ()
    description: str = ""

    @model_validator(mode="after")
    def validate_bounds(self) -> "ParameterSpec":
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("parameter minimum cannot exceed maximum")
        if self.type not in {ParameterType.INTEGER, ParameterType.NUMBER} and (
            self.minimum is not None or self.maximum is not None
        ):
            raise ValueError("only numeric parameters may declare bounds")
        if self.min_properties is not None and self.type != ParameterType.OBJECT:
            raise ValueError("min_properties is only valid for object parameters")
        if len(set(map(_stable_json, self.choices))) != len(self.choices):
            raise ValueError("parameter choices must be unique")
        return self

    def accepts(self, value: Any) -> bool:
        if self.type == ParameterType.INTEGER:
            valid = isinstance(value, int) and not isinstance(value, bool)
        elif self.type == ParameterType.NUMBER:
            valid = isinstance(value, (int, float)) and not isinstance(value, bool)
        elif self.type == ParameterType.STRING:
            valid = isinstance(value, str)
        elif self.type == ParameterType.BOOLEAN:
            valid = isinstance(value, bool)
        else:
            valid = isinstance(value, dict)
        if not valid:
            return False
        if self.type in {ParameterType.INTEGER, ParameterType.NUMBER} and not math.isfinite(
            float(value)
        ):
            return False
        if self.minimum is not None and value < self.minimum:
            return False
        if self.maximum is not None and value > self.maximum:
            return False
        if self.min_properties is not None and len(value) < self.min_properties:
            return False
        return not self.choices or value in self.choices


class FactorSpec(BaseModel):
    """Validated metadata binding an ID to a static formula registry key."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    factor_id: str = Field(pattern=r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
    version: StrictInt = Field(default=1, ge=1)
    name: str = Field(min_length=1)
    display_name: str | None = None
    description: str = Field(min_length=1)
    category: FactorCategory
    catalog_group: FactorGroup | None = None
    frequency: FactorFrequency = FactorFrequency.DAILY
    required_columns: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    params_schema: dict[str, ParameterSpec] = Field(default_factory=dict)
    default_params: dict[str, Any] = Field(default_factory=dict)
    min_history: StrictInt = Field(default=1, ge=1)
    formula_ref: str | None = None
    output_column: str | None = None
    direction: FactorDirection = FactorDirection.NEUTRAL
    winsorize_default: WinsorizeMethod = WinsorizeMethod.MAD
    normalize_default: NormalizeMethod = NormalizeMethod.ZSCORE
    missing_policy: MissingValuePolicy = MissingValuePolicy.DROP
    supported_markets: tuple[Market, ...] = (Market.CN, Market.HK, Market.US)
    point_in_time_required: bool = False
    status: FactorStatus = FactorStatus.ACTIVE

    @model_validator(mode="before")
    @classmethod
    def fill_derived_defaults(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        result = dict(values)
        factor_id = result.get("factor_id")
        result.setdefault("display_name", result.get("name"))
        category = result.get("category")
        if category is not None and "catalog_group" not in result:
            normalized_category = FactorCategory(category)
            result["catalog_group"] = {
                FactorCategory.PRICE: FactorGroup.RETURN_PRICE,
                FactorCategory.TREND: FactorGroup.TREND,
                FactorCategory.MOMENTUM: FactorGroup.MOMENTUM,
                FactorCategory.VOLATILITY: FactorGroup.VOLATILITY_RISK,
                FactorCategory.LIQUIDITY: FactorGroup.LIQUIDITY,
                FactorCategory.VALUATION: FactorGroup.VALUATION,
                FactorCategory.QUALITY: FactorGroup.QUALITY,
                FactorCategory.GROWTH: FactorGroup.GROWTH,
                FactorCategory.SENTIMENT: FactorGroup.SENTIMENT_EVENT,
                FactorCategory.EVENT: FactorGroup.SENTIMENT_EVENT,
                FactorCategory.CROSS_SECTION: FactorGroup.CROSS_COMPOSITE,
                FactorCategory.COMPOSITE: FactorGroup.CROSS_COMPOSITE,
            }[normalized_category]
        if factor_id:
            result.setdefault("formula_ref", f"builtin.{factor_id}")
            result.setdefault("output_column", factor_id)
        return result

    @model_validator(mode="after")
    def validate_definition(self) -> "FactorSpec":
        if not self.display_name:
            raise ValueError("display_name cannot be empty")
        if self.catalog_group is None:
            raise ValueError("catalog_group cannot be empty")
        if not self.formula_ref or not re.fullmatch(
            r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+", self.formula_ref
        ):
            raise ValueError("formula_ref must be a static dotted registry name")
        if not self.output_column or not re.fullmatch(
            r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", self.output_column
        ):
            raise ValueError("output_column must be lower snake case")
        if len(set(self.required_columns)) != len(self.required_columns):
            raise ValueError("required_columns must be unique")
        if len(set(self.dependencies)) != len(self.dependencies):
            raise ValueError("dependencies must be unique")
        if self.factor_id in self.dependencies:
            raise ValueError("a factor cannot depend on itself")
        if not self.supported_markets or len(set(self.supported_markets)) != len(self.supported_markets):
            raise ValueError("supported_markets must be non-empty and unique")
        for key in self.params_schema:
            if not re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", key):
                raise ValueError(f"invalid parameter name: {key}")
        unknown = set(self.default_params) - set(self.params_schema)
        if unknown:
            raise ValueError(f"default_params contain unknown parameters: {sorted(unknown)}")
        illegal = {
            key for key, value in self.default_params.items()
            if not self.params_schema[key].accepts(value)
        }
        if illegal:
            raise ValueError(f"illegal parameter defaults: {sorted(illegal)}")
        return self

    def resolve_params(self, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        resolved = {**self.default_params, **(overrides or {})}
        unknown = set(resolved) - set(self.params_schema)
        if unknown:
            raise ValueError(f"unknown parameters: {sorted(unknown)}")
        missing = {
            key for key, schema in self.params_schema.items()
            if schema.required and key not in resolved
        }
        if missing:
            raise ValueError(f"required parameters missing: {sorted(missing)}")
        illegal = {
            key for key, value in resolved.items()
            if not self.params_schema[key].accepts(value)
        }
        if illegal:
            raise ValueError(f"illegal parameters: {sorted(illegal)}")
        return resolved


class FactorDefinition(FactorSpec):
    """Checksummed immutable metadata mirrored to MongoDB."""

    checksum: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_or_set_checksum(self) -> "FactorDefinition":
        expected = self.content_checksum()
        if self.checksum is not None and self.checksum != expected:
            raise ValueError("checksum does not match factor definition content")
        object.__setattr__(self, "checksum", expected)
        return self

    def content_checksum(self) -> str:
        payload = self.model_dump(mode="json", exclude={"checksum"})
        return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()


class FactorJobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class FactorSnapshotStatus(str, Enum):
    BUILDING = "building"
    READY = "ready"
    FAILED = "failed"
    SUPERSEDED = "superseded"


class FactorVersionRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    factor_id: str = Field(pattern=r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
    version: StrictInt = Field(default=1, ge=1)
    params: dict[str, Any] = Field(default_factory=dict)


class FactorUniverseMember(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    market: Market
    symbol: str = Field(min_length=1, max_length=64)

    @field_validator("symbol")
    @classmethod
    def require_canonical_symbol(cls, value: str) -> str:
        if not value.strip() or value != value.strip():
            raise ValueError("symbol must be non-blank and trimmed")
        return value


def _default_factor_workers() -> int:
    return min(max((os.cpu_count() or 2) - 1, 1), 8)


class FactorComputeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    universe_snapshot_id: str = Field(min_length=1, max_length=200)
    members: tuple[FactorUniverseMember, ...] = Field(min_length=1)
    start_date: date | None = None
    trade_date: date
    as_of: datetime
    factors: tuple[FactorVersionRef, ...] = Field(min_length=1)
    source_versions: dict[str, str] = Field(min_length=1)
    adjustment: str = Field(default="qfq", pattern=r"^(qfq|hfq|none)$")
    chunk_size: StrictInt = Field(default=100, ge=1, le=1000)
    workers: StrictInt = Field(default_factory=_default_factor_workers, ge=1, le=16)
    request_nonce: str | None = Field(default=None, min_length=1, max_length=120)

    @field_validator("as_of")
    @classmethod
    def require_aware_as_of(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        return value.astimezone(timezone.utc)

    @field_validator("universe_snapshot_id")
    @classmethod
    def non_whitespace_universe(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("universe_snapshot_id cannot be blank")
        return value

    @model_validator(mode="after")
    def validate_request_identity(self) -> "FactorComputeRequest":
        member_keys = [(item.market, item.symbol) for item in self.members]
        if len(set(member_keys)) != len(member_keys):
            raise ValueError("universe members must be unique")
        markets = {item.market for item in self.members}
        if len(markets) != 1:
            raise ValueError("one factor snapshot must contain exactly one market")
        factor_keys = [(item.factor_id, item.version) for item in self.factors]
        if len(set(factor_keys)) != len(factor_keys):
            raise ValueError("requested factor versions must be unique")
        if self.trade_date > self.as_of.date():
            raise ValueError("trade_date cannot be after as_of")
        if self.start_date is not None and self.start_date > self.trade_date:
            raise ValueError("start_date cannot be after trade_date")
        if self.request_nonce is not None and self.request_nonce != self.request_nonce.strip():
            raise ValueError("request_nonce must be trimmed")
        if any(not key.strip() or not value.strip() for key, value in self.source_versions.items()):
            raise ValueError("source_versions keys and values cannot be blank")
        return self

    @property
    def market(self) -> Market:
        return self.members[0].market

    def semantic_payload(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json", exclude={"chunk_size", "workers"})
        payload["start_date"] = payload["start_date"] or payload["trade_date"]
        payload["members"] = sorted(
            payload["members"], key=lambda item: (item["market"], item["symbol"])
        )
        payload["factors"] = sorted(
            payload["factors"], key=lambda item: (item["factor_id"], item["version"])
        )
        payload["source_versions"] = dict(sorted(payload["source_versions"].items()))
        return payload

    @property
    def request_checksum(self) -> str:
        return hashlib.sha256(
            _stable_json(self.semantic_payload()).encode("utf-8")
        ).hexdigest()

    @property
    def factor_set_checksum(self) -> str:
        factors = [item.model_dump(mode="json") for item in self.factors]
        factors.sort(key=lambda item: (item["factor_id"], item["version"]))
        return hashlib.sha256(_stable_json(factors).encode("utf-8")).hexdigest()


class FactorJob(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    user_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    request_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: FactorJobStatus = FactorJobStatus.QUEUED
    request: FactorComputeRequest
    snapshot_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    completed_symbols: int = Field(default=0, ge=0)
    total_symbols: int = Field(ge=1)
    error: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("created_at", "updated_at")
    @classmethod
    def normalize_timestamps(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_progress_identity(self) -> "FactorJob":
        if self.completed_symbols > self.total_symbols:
            raise ValueError("completed_symbols cannot exceed total_symbols")
        if self.total_symbols != len(self.request.members):
            raise ValueError("total_symbols must match the fixed universe")
        if self.request_checksum != self.request.request_checksum:
            raise ValueError("job request checksum does not match request content")
        if self.status == FactorJobStatus.SUCCEEDED and (
            self.snapshot_id is None or self.completed_symbols != self.total_symbols
        ):
            raise ValueError("succeeded jobs require a snapshot and complete progress")
        if self.status in {FactorJobStatus.FAILED, FactorJobStatus.CANCELLED} and not self.error:
            raise ValueError("failed and cancelled jobs require an error summary")
        return self


class FactorSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    user_id: str = Field(min_length=1)
    job_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    market: Market
    trade_date: date
    as_of: datetime
    universe_snapshot_id: str = Field(min_length=1)
    factor_set_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: FactorSnapshotStatus = FactorSnapshotStatus.BUILDING
    expected_row_count: int = Field(ge=1)
    expected_factor_count: int = Field(ge=1)
    row_count: int = Field(default=0, ge=0)
    factor_count: int = Field(default=0, ge=0)
    source_versions: dict[str, str]
    values_checksum: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    error: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    published_at: datetime | None = None

    @field_validator("as_of", "created_at", "updated_at", "published_at")
    @classmethod
    def normalize_timestamps(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_publication_state(self) -> "FactorSnapshot":
        if self.row_count > self.expected_row_count:
            raise ValueError("snapshot row_count exceeds its fixed universe")
        if self.factor_count > self.expected_factor_count:
            raise ValueError("snapshot factor_count exceeds its requested factor set")
        if self.status in {FactorSnapshotStatus.READY, FactorSnapshotStatus.SUPERSEDED}:
            if (
                self.row_count != self.expected_row_count
                or self.factor_count != self.expected_factor_count
                or self.values_checksum is None
                or self.published_at is None
            ):
                raise ValueError("published snapshots require complete counts and checksum")
        if self.status == FactorSnapshotStatus.FAILED and not self.error:
            raise ValueError("failed snapshots require an error summary")
        return self


class FactorValueRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    market: Market
    symbol: str = Field(min_length=1)
    trade_date: date
    values: dict[str, float | None]
    quality: dict[str, str | None]

    @field_validator("values", mode="before")
    @classmethod
    def require_finite_json_values(
        cls, values: dict[str, float | None]
    ) -> dict[str, float | None]:
        if not isinstance(values, dict):
            raise ValueError("factor values must be an object")
        for factor_id, value in values.items():
            if not factor_id or (
                value is not None
                and (isinstance(value, bool) or not isinstance(value, (int, float)))
            ):
                raise ValueError("factor values must be numeric or null")
            if value is not None and not float("-inf") < float(value) < float("inf"):
                raise ValueError("factor values must be finite or null")
        return values


class FactorUniverseSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: str = Field(min_length=1, max_length=200)
    symbols: tuple[str, ...] = Field(min_length=1, max_length=5000)

    @model_validator(mode="before")
    @classmethod
    def accept_explicit_universe_snapshot_name(cls, values: Any) -> Any:
        if not isinstance(values, dict) or "snapshot_id" in values:
            return values
        if "universe_snapshot_id" not in values:
            return values
        normalized = dict(values)
        normalized["snapshot_id"] = normalized.pop("universe_snapshot_id")
        return normalized

    @field_validator("snapshot_id")
    @classmethod
    def validate_snapshot_id(cls, value: str) -> str:
        if not value.strip() or value != value.strip():
            raise ValueError("universe snapshot_id must be non-blank and trimmed")
        return value

    @field_validator("symbols")
    @classmethod
    def validate_symbols(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item.strip() or item != item.strip() for item in values):
            raise ValueError("universe symbols must be non-blank and trimmed")
        if len(set(values)) != len(values):
            raise ValueError("universe symbols must be unique")
        return values


class FactorValidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    market: Market
    factor_specs: tuple[FactorVersionRef, ...] = Field(min_length=1)


class FactorValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    factor_id: str | None = None


class FactorValidateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    issues: list[FactorValidationIssue] = Field(default_factory=list)
    execution_order: tuple[str, ...] = ()
    required_columns: tuple[str, ...] = ()
    common_intermediates: tuple[str, ...] = ()
    plan_checksum: str | None = None


class FactorComputeApiRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    market: Market
    universe: FactorUniverseSelection
    start_date: date
    end_date: date
    as_of: datetime
    factor_specs: tuple[FactorVersionRef, ...] = Field(min_length=1)
    source_versions: dict[str, str] = Field(min_length=1)
    adj: str = Field(default="qfq", pattern=r"^(qfq|hfq|none)$")
    force_recompute: bool = False
    chunk_size: StrictInt = Field(default=100, ge=1, le=1000)
    workers: StrictInt = Field(default_factory=_default_factor_workers, ge=1, le=16)

    @field_validator("as_of")
    @classmethod
    def normalize_as_of(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_dates_and_versions(self) -> "FactorComputeApiRequest":
        if self.start_date > self.end_date:
            raise ValueError("start_date cannot be after end_date")
        if self.end_date > self.as_of.date():
            raise ValueError("end_date cannot be after as_of")
        if any(not key.strip() or not value.strip() for key, value in self.source_versions.items()):
            raise ValueError("source_versions keys and values cannot be blank")
        return self


class FactorComputeAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    task_id: str
    request_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    deduplicated: bool


class FactorDefinitionListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[FactorDefinition]
    page: int
    page_size: int
    total: int


class FactorSnapshotListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[FactorSnapshot]
    page: int
    page_size: int
    total: int


class FactorValueApiRow(FactorValueRow):
    created_at: datetime | None = None

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class FactorValuePage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot: FactorSnapshot
    items: list[FactorValueApiRow]
    page: int
    page_size: int
    total: int


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
