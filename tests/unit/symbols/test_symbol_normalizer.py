import pytest
from pydantic import ValidationError

from app.models.symbol import CanonicalSymbol, Currency, Market
from app.services.symbols import (
    SymbolNormalizationError,
    SymbolNormalizer,
    normalize_legacy_symbol,
    normalize_symbol,
)


@pytest.mark.parametrize(
    ("value", "symbol", "display"),
    [
        ("600519", "600519", "600519"),
        ("600000.SH", "600000", "600000"),
        ("000001", "000001", "000001"),
        ("300750.sz", "300750", "300750"),
        ("830799", "830799", "830799"),
        ("920001.BJ", "920001", "920001"),
    ],
)
def test_normalizes_representative_cn_exchanges(value, symbol, display):
    result = normalize_symbol(value)

    assert result.market == Market.CN
    assert result.symbol == symbol
    assert result.currency == Currency.CNY
    assert result.display_symbol == display


@pytest.mark.parametrize(
    ("value", "symbol", "display"),
    [
        ("0700", "0700", "0700.HK"),
        (" 0700.hk ", "0700", "0700.HK"),
        ("09988.HK", "09988", "09988.HK"),
        ("9988", "9988", "9988.HK"),
    ],
)
def test_normalizes_hong_kong_inputs(value, symbol, display):
    result = SymbolNormalizer.normalize(value)

    assert result.market == Market.HK
    assert result.symbol == symbol
    assert result.currency == Currency.HKD
    assert result.display_symbol == display
    assert result.original_input == value


@pytest.mark.parametrize(
    ("value", "symbol"),
    [
        ("aapl", "AAPL"),
        ("  msft  ", "MSFT"),
        ("BRK.B", "BRK.B"),
        ("brk-b", "BRK.B"),
    ],
)
def test_normalizes_us_case_whitespace_and_share_classes(value, symbol):
    result = normalize_symbol(value)

    assert result.market == Market.US
    assert result.symbol == symbol
    assert result.currency == Currency.USD
    assert result.display_symbol == symbol
    assert result.original_input == value


@pytest.mark.parametrize(
    ("value", "market"),
    [
        ("600519", "HK"),
        ("0700.HK", "CN"),
        ("AAPL", "CN"),
        ("300750.SZ", "US"),
    ],
)
def test_rejects_conflicting_explicit_market(value, market):
    with pytest.raises(SymbolNormalizationError, match="conflicts"):
        normalize_symbol(value, market=market)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "123",
        "700.HK",
        "0000",
        "000000",
        "123456",
        "1234567",
        "600A00",
        "AAPL1",
        "AAPL.US",
        "0700.SH",
        "600000.HK",
        "TOO-LONG-TICKER",
        "ＡＡＰＬ",
    ],
)
def test_rejects_empty_malformed_overlong_and_mixed_inputs(value):
    with pytest.raises(SymbolNormalizationError):
        normalize_symbol(value)


@pytest.mark.parametrize("value", [None, 700, 600519, object()])
def test_rejects_non_string_inputs_instead_of_padding(value):
    with pytest.raises(SymbolNormalizationError, match="string"):
        normalize_symbol(value)


@pytest.mark.parametrize(
    "field",
    ["symbol", "code", "stock_code", "stock_symbol"],
)
def test_every_legacy_field_has_a_compatibility_adapter(field):
    result = SymbolNormalizer.from_legacy_fields(**{field: " aapl "})

    assert result.market == Market.US
    assert result.symbol == "AAPL"
    assert result.original_input == " aapl "


def test_consistent_legacy_fields_are_accepted_deterministically():
    result = normalize_legacy_symbol(
        symbol="aapl",
        code=" AAPL ",
        stock_code="AAPL",
        stock_symbol="aapl",
    )

    assert result.symbol == "AAPL"
    assert result.original_input == "aapl"


def test_conflicting_legacy_fields_are_rejected():
    with pytest.raises(SymbolNormalizationError, match="conflicting legacy"):
        SymbolNormalizer.from_legacy_fields(
            symbol="AAPL",
            stock_code="MSFT",
        )


def test_mapping_adapter_checks_payload_and_argument_market_conflicts():
    payload = {"stock_symbol": "0700.HK", "market": "HK"}
    assert SymbolNormalizer.from_mapping(payload).market == Market.HK

    with pytest.raises(SymbolNormalizationError, match="payload market"):
        SymbolNormalizer.from_mapping(payload, market="US")


def test_mapping_adapter_does_not_mutate_input():
    payload = {"code": " 300750.sz ", "market": "cn"}
    before = dict(payload)

    first = SymbolNormalizer.from_mapping(payload)
    second = SymbolNormalizer.from_mapping(payload)

    assert first == second
    assert payload == before


def test_serialization_round_trip_preserves_canonical_identity():
    original = normalize_symbol(" 0700.hk ")

    restored = CanonicalSymbol.model_validate_json(original.model_dump_json())

    assert restored == original
    assert restored.model_dump(mode="json") == {
        "market": "HK",
        "symbol": "0700",
        "currency": "HKD",
        "display_symbol": "0700.HK",
        "original_input": " 0700.hk ",
    }


def test_model_rejects_inconsistent_currency_and_display():
    with pytest.raises(ValidationError):
        CanonicalSymbol(
            market="CN",
            symbol="600519",
            currency="USD",
            display_symbol="600519",
            original_input="600519",
        )

    with pytest.raises(ValidationError):
        CanonicalSymbol(
            market="HK",
            symbol="0700",
            currency="HKD",
            display_symbol="0700",
            original_input="0700",
        )


def test_model_documents_detection_limitations():
    limitations = CanonicalSymbol.MARKET_DETECTION_LIMITATIONS.lower()
    assert "syntactic" in limitations
    assert "listing existence" in limitations
