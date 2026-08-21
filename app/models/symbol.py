"""Canonical, persistence-ready security identity models."""

import re
from enum import Enum
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, model_validator


def infer_cn_exchange(symbol: str) -> str | None:
    """Return the exchange for a supported A-share code family."""
    if symbol == "000000":
        return None
    if re.fullmatch(r"(?:600|601|603|605|688|689)\d{3}", symbol):
        return "SH"
    if re.fullmatch(r"(?:000|001|002|003|300|301)\d{3}", symbol):
        return "SZ"
    if re.fullmatch(r"(?:43|82|83|87|88|92)\d{4}", symbol):
        return "BJ"
    return None


class Market(str, Enum):
    CN = "CN"
    HK = "HK"
    US = "US"


class Currency(str, Enum):
    CNY = "CNY"
    HKD = "HKD"
    USD = "USD"


class CanonicalSymbol(BaseModel):
    """A deterministic market + symbol identity.

    Detection is intentionally syntactic. It does not prove that a security is
    listed, active, or available from a data provider. Chinese exchange
    detection uses known A-share code families and may need a versioned update
    when exchanges allocate new ranges. Hong Kong and US formats likewise do
    not resolve delistings, aliases, warrants, funds, or other instrument types.
    Callers needing those facts must validate them in a separate data-quality
    step; they must not reinterpret this canonical identity.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    MARKET_DETECTION_LIMITATIONS: ClassVar[str] = (
        "Syntactic classification only; it does not verify listing existence, "
        "status, instrument type, provider coverage, or future exchange ranges."
    )

    market: Market
    symbol: str = Field(min_length=1, max_length=7)
    currency: Currency
    display_symbol: str = Field(min_length=1, max_length=10)
    original_input: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_canonical_invariants(self) -> "CanonicalSymbol":
        expected_currency = {
            Market.CN: Currency.CNY,
            Market.HK: Currency.HKD,
            Market.US: Currency.USD,
        }[self.market]
        if self.currency != expected_currency:
            raise ValueError(
                f"currency {self.currency.value} is invalid for market "
                f"{self.market.value}"
            )

        if self.market == Market.CN:
            valid_symbol = infer_cn_exchange(self.symbol) is not None
            expected_display = self.symbol
        elif self.market == Market.HK:
            valid_symbol = (
                re.fullmatch(r"\d{4,5}", self.symbol)
                and int(self.symbol) != 0
            )
            expected_display = f"{self.symbol}.HK"
        else:
            valid_symbol = re.fullmatch(r"[A-Z]{1,5}(?:\.[A-Z])?", self.symbol)
            expected_display = self.symbol

        if not valid_symbol:
            raise ValueError(
                f"symbol {self.symbol!r} is not canonical for "
                f"market {self.market.value}"
            )
        if self.display_symbol != expected_display:
            raise ValueError(
                f"display_symbol must be {expected_display!r} for "
                f"market {self.market.value}"
            )
        if not self.original_input.strip():
            raise ValueError("original_input must contain a non-whitespace value")
        return self
