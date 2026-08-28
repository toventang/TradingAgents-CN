"""Version-stable default benchmark identities."""

from app.models.market_data import BenchmarkIdentity
from app.models.symbol import Currency, Market


class BenchmarkRegistry:
    VERSION = "benchmark-identities-v1"
    _DEFAULTS = {
        Market.CN: BenchmarkIdentity(
            benchmark_id="CN.CSI300",
            market=Market.CN,
            symbol="000300.SH",
            display_name="CSI 300",
            currency=Currency.CNY,
        ),
        Market.HK: BenchmarkIdentity(
            benchmark_id="HK.HSI",
            market=Market.HK,
            symbol="HSI",
            display_name="Hang Seng Index",
            currency=Currency.HKD,
        ),
        Market.US: BenchmarkIdentity(
            benchmark_id="US.SP500",
            market=Market.US,
            symbol="SPX",
            display_name="S&P 500",
            currency=Currency.USD,
        ),
    }

    @classmethod
    def default_for(cls, market: Market | str) -> BenchmarkIdentity:
        return cls._DEFAULTS[Market(market)]

    @classmethod
    def all(cls) -> tuple[BenchmarkIdentity, ...]:
        return tuple(cls._DEFAULTS.values())
