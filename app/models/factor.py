"""Static, executable-free factor definition models."""

from __future__ import annotations

import hashlib
import json
import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

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


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
