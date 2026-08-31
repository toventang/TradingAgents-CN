"""Persistence contracts for versioned, deterministic trading strategies.

This module intentionally models persistence and lifecycle state only.  Signal
evaluation and strategy DSL execution belong to later tasks.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from app.models.symbol import Market


SYSTEM_USER_ID = "system"
_IDENTIFIER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_identifier() -> str:
    return str(uuid4())


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _checksum(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _normalized_time(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _require_aware_time(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _require_json_object(value: dict[str, Any], field_name: str) -> dict[str, Any]:
    try:
        encoded = _stable_json(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must contain only JSON values") from exc
    if len(encoded.encode("utf-8")) > 1_000_000:
        raise ValueError(f"{field_name} exceeds the 1 MB persistence limit")
    return value


class StrategyKind(str, Enum):
    SCREENING = "screening"
    RANKING = "ranking"
    PORTFOLIO = "portfolio"


class StrategyVisibility(str, Enum):
    PRIVATE = "private"
    SHARED_READONLY = "shared_readonly"
    SYSTEM = "system"


class StrategyVersionStatus(str, Enum):
    DRAFT = "draft"
    VALIDATING = "validating"
    PUBLISHED = "published"
    DEPRECATED = "deprecated"


class StrategyCloneSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy_id: str = Field(pattern=_IDENTIFIER_PATTERN)
    strategy_version_id: str = Field(pattern=_IDENTIFIER_PATTERN)
    version: StrictInt = Field(ge=1)
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")


class Strategy(BaseModel):
    """Stable strategy identity and mutable lifecycle pointers."""

    model_config = ConfigDict(extra="forbid")

    strategy_id: str = Field(default_factory=new_identifier, pattern=_IDENTIFIER_PATTERN)
    user_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    tags: tuple[str, ...] = ()
    kind: StrategyKind
    visibility: StrategyVisibility = StrategyVisibility.PRIVATE
    current_draft_version_id: str | None = Field(default=None, pattern=_IDENTIFIER_PATTERN)
    latest_published_version_id: str | None = Field(default=None, pattern=_IDENTIFIER_PATTERN)
    clone_source: StrategyCloneSource | None = None
    version_sequence: StrictInt = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    archived_at: datetime | None = None

    @field_validator("user_id", "name", "description")
    @classmethod
    def require_trimmed_text(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("text fields must be trimmed")
        return value

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) > 32:
            raise ValueError("at most 32 tags are allowed")
        if any(not item or item != item.strip() or len(item) > 64 for item in value):
            raise ValueError("tags must be non-empty, trimmed, and at most 64 characters")
        if len(set(value)) != len(value):
            raise ValueError("tags must be unique")
        return value

    @field_validator("created_at", "updated_at", "archived_at")
    @classmethod
    def normalize_timestamps(cls, value: datetime | None) -> datetime | None:
        return _normalized_time(value)

    @model_validator(mode="after")
    def validate_identity_and_lifecycle(self) -> "Strategy":
        if self.user_id == SYSTEM_USER_ID and self.visibility != StrategyVisibility.SYSTEM:
            raise ValueError("system-owned strategies must use system visibility")
        if self.visibility == StrategyVisibility.SYSTEM and self.user_id != SYSTEM_USER_ID:
            raise ValueError("system visibility is reserved for the system owner")
        if self.clone_source is not None and self.clone_source.strategy_id == self.strategy_id:
            raise ValueError("a strategy cannot clone itself")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        if self.archived_at is not None and self.archived_at < self.created_at:
            raise ValueError("archived_at cannot precede created_at")
        return self


class FrozenFactorDependency(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    factor_id: str = Field(pattern=r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
    version: StrictInt = Field(ge=1)
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")


class FrozenSkillDependency(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    skill_id: str = Field(pattern=_IDENTIFIER_PATTERN)
    version: StrictInt = Field(ge=1)
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")


class StrategyValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,63}$")
    message: str = Field(min_length=1, max_length=1000)
    path: str | None = Field(default=None, max_length=500)


class StrategyValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    valid: bool
    errors: tuple[StrategyValidationIssue, ...] = ()
    warnings: tuple[StrategyValidationIssue, ...] = ()
    validated_at: datetime = Field(default_factory=utc_now)

    @field_validator("validated_at")
    @classmethod
    def normalize_validated_at(cls, value: datetime) -> datetime:
        normalized = _normalized_time(value)
        assert normalized is not None
        return normalized

    @model_validator(mode="after")
    def validate_result(self) -> "StrategyValidationResult":
        if self.valid and self.errors:
            raise ValueError("a valid result cannot contain errors")
        if not self.valid and not self.errors:
            raise ValueError("an invalid result must contain at least one error")
        return self


class StrategyVersion(BaseModel):
    """One checksummed strategy definition version.

    Published and deprecated instances are immutable in persistence.  Draft
    updates replace the model and therefore always recompute the checksum.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy_version_id: str = Field(default_factory=new_identifier, pattern=_IDENTIFIER_PATTERN)
    strategy_id: str = Field(pattern=_IDENTIFIER_PATTERN)
    user_id: str = Field(min_length=1, max_length=128)
    version: StrictInt = Field(ge=1)
    status: StrategyVersionStatus = StrategyVersionStatus.DRAFT
    market: Market
    definition: dict[str, Any]
    analysis_profile_version_id: str | None = Field(default=None, pattern=_IDENTIFIER_PATTERN)
    factor_dependencies: tuple[FrozenFactorDependency, ...] = ()
    skill_dependencies: tuple[FrozenSkillDependency, ...] = ()
    checksum: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    validation_result: StrategyValidationResult | None = None
    created_by: str = Field(min_length=1, max_length=128)
    created_at: datetime = Field(default_factory=utc_now)
    published_at: datetime | None = None
    change_summary: str = Field(default="", max_length=2000)
    parent_version_id: str | None = Field(default=None, pattern=_IDENTIFIER_PATTERN)

    @field_validator("definition")
    @classmethod
    def validate_definition(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _require_json_object(value, "definition")

    @field_validator("user_id", "created_by", "change_summary")
    @classmethod
    def require_trimmed_text(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("text fields must be trimmed")
        return value

    @field_validator("created_at", "published_at")
    @classmethod
    def normalize_timestamps(cls, value: datetime | None) -> datetime | None:
        return _normalized_time(value)

    @model_validator(mode="after")
    def validate_version_state(self) -> "StrategyVersion":
        if self.version == 1 and self.parent_version_id is not None:
            raise ValueError("version 1 cannot have a parent version")
        if self.version > 1 and self.parent_version_id is None:
            raise ValueError("versions after 1 require parent_version_id provenance")
        if self.parent_version_id == self.strategy_version_id:
            raise ValueError("a strategy version cannot be its own parent")
        factor_keys = [(item.factor_id, item.version) for item in self.factor_dependencies]
        skill_keys = [(item.skill_id, item.version) for item in self.skill_dependencies]
        if len(set(factor_keys)) != len(factor_keys):
            raise ValueError("factor dependencies must be unique")
        if len(set(skill_keys)) != len(skill_keys):
            raise ValueError("skill dependencies must be unique")
        if self.status in {StrategyVersionStatus.PUBLISHED, StrategyVersionStatus.DEPRECATED}:
            if self.published_at is None:
                raise ValueError("published and deprecated versions require published_at")
            if self.validation_result is None or not self.validation_result.valid:
                raise ValueError("published versions require successful validation")
        elif self.published_at is not None:
            raise ValueError("draft and validating versions cannot have published_at")
        expected = self.content_checksum()
        if self.checksum is not None and self.checksum != expected:
            raise ValueError("checksum does not match strategy version content")
        object.__setattr__(self, "checksum", expected)
        return self

    def content_checksum(self) -> str:
        payload = self.model_dump(
            mode="json",
            exclude={"checksum", "status", "validation_result", "published_at"},
        )
        return _checksum(payload)


class UniverseMember(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    market: Market
    symbol: str = Field(min_length=1, max_length=64)

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, value: str) -> str:
        if value != value.strip() or not value:
            raise ValueError("symbol must be non-empty and trimmed")
        return value


class UniverseSnapshot(BaseModel):
    """Immutable point-in-time strategy universe."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    universe_snapshot_id: str = Field(default_factory=new_identifier, pattern=_IDENTIFIER_PATTERN)
    user_id: str = Field(min_length=1, max_length=128)
    market: Market
    trade_date: date
    as_of: datetime
    members: tuple[UniverseMember, ...] = Field(min_length=1)
    source_versions: dict[str, str] = Field(min_length=1)
    selection_definition: dict[str, Any] = Field(default_factory=dict)
    checksum: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("as_of")
    @classmethod
    def require_aware_as_of(cls, value: datetime) -> datetime:
        return _require_aware_time(value, "as_of")

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        normalized = _normalized_time(value)
        assert normalized is not None
        return normalized

    @field_validator("selection_definition")
    @classmethod
    def validate_selection_definition(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _require_json_object(value, "selection_definition")

    @model_validator(mode="after")
    def validate_snapshot(self) -> "UniverseSnapshot":
        member_keys = [(item.market, item.symbol) for item in self.members]
        if len(set(member_keys)) != len(member_keys):
            raise ValueError("universe members must be unique")
        if any(item.market != self.market for item in self.members):
            raise ValueError("all universe members must match the snapshot market")
        if self.trade_date > self.as_of.date():
            raise ValueError("trade_date cannot be after as_of")
        if any(not key.strip() or not value.strip() for key, value in self.source_versions.items()):
            raise ValueError("source version keys and values must be non-empty")
        expected = self.content_checksum()
        if self.checksum is not None and self.checksum != expected:
            raise ValueError("checksum does not match universe snapshot content")
        object.__setattr__(self, "checksum", expected)
        return self

    def content_checksum(self) -> str:
        payload = self.model_dump(mode="json", exclude={"checksum", "created_at"})
        payload["members"] = sorted(
            payload["members"], key=lambda item: (item["market"], item["symbol"])
        )
        payload["source_versions"] = dict(sorted(payload["source_versions"].items()))
        return _checksum(payload)


class StrategySignal(BaseModel):
    """Immutable persisted output from one explicit strategy version."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    signal_id: str = Field(default_factory=new_identifier, pattern=_IDENTIFIER_PATTERN)
    user_id: str = Field(min_length=1, max_length=128)
    strategy_version_id: str = Field(pattern=_IDENTIFIER_PATTERN)
    universe_snapshot_id: str = Field(pattern=_IDENTIFIER_PATTERN)
    factor_snapshot_id: str | None = Field(default=None, pattern=_IDENTIFIER_PATTERN)
    market: Market
    symbol: str = Field(min_length=1, max_length=64)
    signal_date: date
    signal_type: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    score: float | None = None
    rank: StrictInt | None = Field(default=None, ge=1)
    reason_codes: tuple[str, ...] = ()
    input_contributions: dict[str, float] = Field(default_factory=dict)
    as_of: datetime
    checksum: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("symbol must be non-empty and trimmed")
        return value

    @field_validator("as_of")
    @classmethod
    def require_aware_as_of(cls, value: datetime) -> datetime:
        return _require_aware_time(value, "as_of")

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        normalized = _normalized_time(value)
        assert normalized is not None
        return normalized

    @model_validator(mode="after")
    def validate_signal(self) -> "StrategySignal":
        if self.signal_date > self.as_of.date():
            raise ValueError("signal_date cannot be after as_of")
        if self.score is not None and not math.isfinite(self.score):
            raise ValueError("score must be finite")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("reason_codes must be unique")
        if any(not re.fullmatch(r"[A-Z][A-Z0-9_]{1,63}", item) for item in self.reason_codes):
            raise ValueError("reason_codes must use upper snake case")
        if any(
            not key.strip() or not math.isfinite(value)
            for key, value in self.input_contributions.items()
        ):
            raise ValueError("input contributions require non-empty keys and finite values")
        expected = self.content_checksum()
        if self.checksum is not None and self.checksum != expected:
            raise ValueError("checksum does not match strategy signal content")
        object.__setattr__(self, "checksum", expected)
        return self

    def content_checksum(self) -> str:
        payload = self.model_dump(
            mode="json", exclude={"signal_id", "checksum", "created_at"}
        )
        payload["reason_codes"] = sorted(payload["reason_codes"])
        payload["input_contributions"] = dict(sorted(payload["input_contributions"].items()))
        return _checksum(payload)
