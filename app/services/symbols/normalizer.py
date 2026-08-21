"""Side-effect-free normalization for supported CN, HK, and US symbols."""

import re
from collections.abc import Mapping
from typing import Any, Optional

from app.models.symbol import (
    CanonicalSymbol,
    Currency,
    Market,
    infer_cn_exchange,
)

LEGACY_SYMBOL_FIELDS = ("symbol", "code", "stock_code", "stock_symbol")

_CN_RE = re.compile(r"^(?P<symbol>\d{6})(?:\.(?P<exchange>SH|SZ|BJ))?$")
_HK_RE = re.compile(r"^(?P<symbol>\d{4,5})(?:\.HK)?$")
_US_RE = re.compile(r"^[A-Z]{1,5}(?:[.-][A-Z])?$")

_MARKET_ALIASES = {
    "CN": Market.CN,
    "CHINA": Market.CN,
    "CHINA_A": Market.CN,
    "A_SHARE": Market.CN,
    "A股": Market.CN,
    "HK": Market.HK,
    "HKG": Market.HK,
    "HONG_KONG": Market.HK,
    "港股": Market.HK,
    "US": Market.US,
    "USA": Market.US,
    "NASDAQ": Market.US,
    "NYSE": Market.US,
    "美股": Market.US,
}


class SymbolNormalizationError(ValueError):
    """Raised when an input cannot map to one unambiguous canonical identity."""


def _canonical_market(value: Any) -> Optional[Market]:
    if value is None:
        return None
    if isinstance(value, Market):
        return value
    if not isinstance(value, str) or not value.strip():
        raise SymbolNormalizationError("market must be one of CN, HK, or US")
    key = re.sub(r"[\s-]+", "_", value.strip().upper())
    try:
        return _MARKET_ALIASES[key]
    except KeyError as exc:
        raise SymbolNormalizationError(
            f"unsupported explicit market {value!r}; expected CN, HK, or US"
        ) from exc


def _infer_market_and_symbol(value: str) -> tuple[Market, str]:
    cn_match = _CN_RE.fullmatch(value)
    if cn_match:
        symbol = cn_match.group("symbol")
        detected_exchange = infer_cn_exchange(symbol)
        explicit_exchange = cn_match.group("exchange")
        if detected_exchange is None:
            raise SymbolNormalizationError(
                f"{value!r} is not in a supported A-share code family"
            )
        if explicit_exchange and explicit_exchange != detected_exchange:
            raise SymbolNormalizationError(
                f"exchange suffix {explicit_exchange} conflicts with "
                f"inferred exchange {detected_exchange}"
            )
        return Market.CN, symbol

    hk_match = _HK_RE.fullmatch(value)
    if hk_match:
        symbol = hk_match.group("symbol")
        if int(symbol) == 0:
            raise SymbolNormalizationError("Hong Kong symbol cannot be all zeroes")
        return Market.HK, symbol

    if _US_RE.fullmatch(value):
        return Market.US, value.replace("-", ".")

    raise SymbolNormalizationError(
        f"unsupported or ambiguous symbol input {value!r}"
    )


class SymbolNormalizer:
    """Normalize supported legacy strings without I/O or mutable state."""

    @classmethod
    def normalize(
        cls,
        value: str,
        market: Any = None,
    ) -> CanonicalSymbol:
        if not isinstance(value, str):
            raise SymbolNormalizationError("symbol input must be a string")

        original_input = value
        normalized_input = value.strip().upper()
        if not normalized_input:
            raise SymbolNormalizationError("symbol input cannot be empty")
        if len(normalized_input) > 10:
            raise SymbolNormalizationError("symbol input is too long")

        inferred_market, symbol = _infer_market_and_symbol(normalized_input)
        requested_market = _canonical_market(market)
        if requested_market is not None and requested_market != inferred_market:
            raise SymbolNormalizationError(
                f"explicit market {requested_market.value} conflicts with "
                f"inferred market {inferred_market.value}"
            )

        currency = {
            Market.CN: Currency.CNY,
            Market.HK: Currency.HKD,
            Market.US: Currency.USD,
        }[inferred_market]
        display_symbol = (
            f"{symbol}.HK" if inferred_market == Market.HK else symbol
        )
        return CanonicalSymbol(
            market=inferred_market,
            symbol=symbol,
            currency=currency,
            display_symbol=display_symbol,
            original_input=original_input,
        )

    @classmethod
    def from_legacy_fields(
        cls,
        *,
        symbol: Any = None,
        code: Any = None,
        stock_code: Any = None,
        stock_symbol: Any = None,
        market: Any = None,
    ) -> CanonicalSymbol:
        values = {
            "symbol": symbol,
            "code": code,
            "stock_code": stock_code,
            "stock_symbol": stock_symbol,
        }
        populated = [
            (field, value)
            for field, value in values.items()
            if value is not None
            and (not isinstance(value, str) or bool(value.strip()))
        ]
        if not populated:
            raise SymbolNormalizationError(
                "one of symbol, code, stock_code, or stock_symbol is required"
            )

        normalized = [
            (field, cls.normalize(value, market=market))
            for field, value in populated
        ]
        identities = {
            (item.market, item.symbol)
            for _, item in normalized
        }
        if len(identities) != 1:
            fields = ", ".join(field for field, _ in normalized)
            raise SymbolNormalizationError(
                f"conflicting legacy symbol fields: {fields}"
            )
        return normalized[0][1]

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any],
        market: Any = None,
    ) -> CanonicalSymbol:
        if not isinstance(payload, Mapping):
            raise SymbolNormalizationError("legacy payload must be a mapping")

        payload_market = payload.get("market")
        if market is not None and payload_market is not None:
            if _canonical_market(market) != _canonical_market(payload_market):
                raise SymbolNormalizationError(
                    "explicit market conflicts with payload market"
                )
        effective_market = market if market is not None else payload_market
        return cls.from_legacy_fields(
            symbol=payload.get("symbol"),
            code=payload.get("code"),
            stock_code=payload.get("stock_code"),
            stock_symbol=payload.get("stock_symbol"),
            market=effective_market,
        )

    normalize_legacy = from_legacy_fields


def normalize_symbol(value: str, market: Any = None) -> CanonicalSymbol:
    return SymbolNormalizer.normalize(value, market=market)


def normalize_legacy_symbol(
    *,
    symbol: Any = None,
    code: Any = None,
    stock_code: Any = None,
    stock_symbol: Any = None,
    market: Any = None,
) -> CanonicalSymbol:
    return SymbolNormalizer.from_legacy_fields(
        symbol=symbol,
        code=code,
        stock_code=stock_code,
        stock_symbol=stock_symbol,
        market=market,
    )
