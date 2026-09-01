from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.models.backtest import (
    BacktestRequest,
    BenchmarkBar,
    BiasWarningCode,
    MarketRuleVersion,
    UniverseMembership,
)
from app.models.market_data import (
    DailyBar,
    DataQualityInfo,
    DataQualityStatus,
    MarketDataBatch,
    NewsSocialInput,
    PointInTimeFact,
)
from app.models.symbol import Currency, Market
from app.repositories.backtest_repository import BacktestInputRepository
from app.services.backtest.data import PointInTimeBacktestDataService
from app.services.calendars.market_calendar import MarketCalendarService
from tests.strategy_fakes import FakeDatabase


UTC = timezone.utc


def at(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def quality(as_of: datetime, *, reason: str = "OK") -> DataQualityInfo:
    return DataQualityInfo(
        status=DataQualityStatus.VALID if reason == "OK" else DataQualityStatus.PARTIAL,
        reason_code=reason,
        as_of=as_of,
        source_version="fixture-v1",
    )


class FakeRepository:
    def __init__(self, memberships: list[UniverseMembership]):
        self.memberships = memberships
        self.indexes_ready = False

    async def ensure_indexes(self):
        self.indexes_ready = True

    async def list_universe_memberships(self, universe_id, market, *, trade_date, as_of):
        assert universe_id == "fixture-universe"
        return tuple(
            item
            for item in self.memberships
            if item.market == Market(market) and item.applies_on(trade_date, as_of)
        )

    async def list_corporate_actions(self, market, *, symbols, start_date, end_date, as_of):
        del market, symbols, start_date, end_date, as_of
        return ()

    async def get_benchmark_bar(self, benchmark_id, market, *, trade_date, as_of):
        return BenchmarkBar(
            benchmark_id=benchmark_id,
            market=Market(market),
            symbol="000300",
            trade_date=trade_date,
            close=Decimal("3500"),
            source="fixture",
            source_version="benchmark-v1",
            ingested_at=as_of,
        )

    async def get_market_rule(self, market, *, trade_date, as_of):
        return MarketRuleVersion(
            rule_version_id="cn-rules-2020",
            market=Market(market),
            effective_from=date(2020, 1, 1),
            published_at=at("2019-12-31T00:00:00"),
            rules={"lot_size": 100},
        )


class FakeMarketData:
    def __init__(self, *, facts=(), news=(), social=()):
        self.facts = tuple(facts)
        self.news = tuple(news)
        self.social = tuple(social)

    @staticmethod
    def _batch(items, as_of):
        return MarketDataBatch(
            items=list(items),
            as_of=as_of,
            source_version="fixture-v1",
            quality=quality(as_of),
        )

    async def read_daily_bars(self, symbol, market, *, start_date, end_date, as_of):
        assert start_date == end_date
        return self._batch(
            (
                DailyBar(
                    market=Market(market),
                    symbol=symbol,
                    trade_date=start_date,
                    open=10,
                    high=11,
                    low=9,
                    close=10,
                    source="fixture",
                    source_version="bars-v1",
                ),
            ),
            as_of,
        )

    async def read_point_in_time_facts(self, symbol, market, *, as_of):
        del market
        return self._batch((item for item in self.facts if item.symbol == symbol), as_of)

    async def read_news_inputs(self, symbol, market, *, as_of):
        del market
        return self._batch((item for item in self.news if item.symbol == symbol), as_of)

    async def read_social_inputs(self, symbol, market, *, as_of):
        del market
        return self._batch((item for item in self.social if item.symbol == symbol), as_of)


def member(
    symbol: str,
    *,
    effective_from: date,
    effective_to: date | None = None,
    known_at: datetime = at("2019-01-01T00:00:00"),
    delisting_date: date | None = None,
) -> UniverseMembership:
    return UniverseMembership(
        universe_id="fixture-universe",
        market=Market.CN,
        symbol=symbol,
        effective_from=effective_from,
        effective_to=effective_to,
        known_at=known_at,
        listing_date=date(2010, 1, 1),
        delisting_date=delisting_date,
        source="fixture",
        source_version="universe-v1",
    )


@pytest.mark.asyncio
async def test_financial_release_is_not_visible_until_next_trading_day():
    fact = PointInTimeFact(
        fact_id="report-1",
        market=Market.CN,
        symbol="000001",
        report_period="2023Q4",
        publish_at=at("2024-01-05T01:00:00"),  # Friday in UTC
        ingested_at=at("2024-01-05T02:00:00"),
        data={"profit": 100},
        source="fixture",
        source_version="financial-v1",
    )
    service = PointInTimeBacktestDataService(
        repository=FakeRepository(
            [member("000001", effective_from=date(2020, 1, 1))]
        ),
        market_data=FakeMarketData(facts=(fact,)),
    )

    friday = await service.build_day(
        market=Market.CN,
        universe_id="fixture-universe",
        benchmark_id="csi300",
        trade_date=date(2024, 1, 5),
    )
    monday = await service.build_day(
        market=Market.CN,
        universe_id="fixture-universe",
        benchmark_id="csi300",
        trade_date=date(2024, 1, 8),
    )

    assert friday.financial_facts == ()
    assert [item.fact_id for item in monday.financial_facts] == ["report-1"]


@pytest.mark.asyncio
async def test_historical_universe_keeps_delisted_member_and_excludes_future_member():
    repository = FakeRepository(
        [
            member(
                "OLD001",
                effective_from=date(2019, 1, 1),
                effective_to=date(2020, 6, 30),
                delisting_date=date(2020, 6, 30),
            ),
            member("LIVE01", effective_from=date(2019, 1, 1)),
            member("NEW001", effective_from=date(2021, 1, 1)),
        ]
    )
    service = PointInTimeBacktestDataService(
        repository=repository,
        market_data=FakeMarketData(),
    )

    historical = await service.build_day(
        market=Market.CN,
        universe_id="fixture-universe",
        benchmark_id="csi300",
        trade_date=date(2020, 6, 1),
    )

    assert [item.symbol for item in historical.universe] == ["OLD001", "LIVE01"]
    assert [item.symbol for item in historical.bars] == ["LIVE01", "OLD001"]
    assert "NEW001" not in {item.symbol for item in historical.universe}


@pytest.mark.asyncio
async def test_empty_historical_universe_never_falls_back_to_current_constituents():
    service = PointInTimeBacktestDataService(
        repository=FakeRepository(
            [member("FUTURE", effective_from=date(2025, 1, 1))]
        ),
        market_data=FakeMarketData(),
    )

    day = await service.build_day(
        market=Market.CN,
        universe_id="fixture-universe",
        benchmark_id="csi300",
        trade_date=date(2024, 1, 8),
    )

    assert day.universe == ()
    assert day.bars == ()
    assert BiasWarningCode.MISSING_UNIVERSE_HISTORY in {
        item.code for item in day.bias_warnings
    }
    assert day.automatic_learning_allowed is False


def test_news_uses_later_of_publish_and_ingestion_and_strict_next_window():
    signal_close = MarketCalendarService.daily_as_of(Market.CN, date(2024, 1, 8))
    before_close = signal_close.astimezone(UTC).replace(hour=6, minute=59)
    at_close = signal_close.astimezone(UTC)
    service = PointInTimeBacktestDataService(
        repository=FakeRepository([]), market_data=FakeMarketData()
    )
    visible = NewsSocialInput(
        news_id="visible",
        market=Market.CN,
        symbol="000001",
        published_at=at("2024-01-07T01:00:00"),
        ingested_at=before_close,
        source="fixture",
        source_version="news-v1",
    )
    exactly_at_window = NewsSocialInput(
        news_id="next-window",
        market=Market.CN,
        symbol="000001",
        published_at=at("2024-01-07T01:00:00"),
        ingested_at=at_close,
        source="fixture",
        source_version="news-v1",
    )

    result = service.event_inputs_visible_at((visible, exactly_at_window), signal_close)

    assert [item.news_id for item in result] == ["visible"]


def test_market_rule_checksum_and_bundle_inputs_are_deterministic():
    first = MarketRuleVersion(
        rule_version_id="cn-rules-2020",
        market=Market.CN,
        effective_from=date(2020, 1, 1),
        published_at=at("2019-12-31T00:00:00"),
        rules={"lot_size": 100, "t_plus": 1},
    )
    second = MarketRuleVersion.model_validate(first.model_dump(mode="python"))

    assert first.checksum == second.checksum
    assert len(first.checksum or "") == 64


def test_request_enforces_single_market_currency_and_minimum_sessions():
    request = BacktestRequest(
        strategy_version_id="strategy-v1",
        market=Market.CN,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 4, 1),
        initial_cash=Decimal("100000"),
        benchmark="csi300",
        execution_model_id="next_open",
    )
    service = PointInTimeBacktestDataService(
        repository=FakeRepository([]), market_data=FakeMarketData()
    )

    assert request.base_currency == Currency.CNY
    assert len(service.validate_request_window(request)) >= 60
    with pytest.raises(ValueError, match="at least 60"):
        service.validate_request_window(
            request.model_copy(update={"end_date": date(2024, 1, 31)})
        )
    with pytest.raises(ValueError, match="base_currency"):
        BacktestRequest(
            strategy_version_id="strategy-v1",
            market=Market.CN,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 4, 1),
            initial_cash=Decimal("100000"),
            benchmark="csi300",
            execution_model_id="next_open",
            base_currency=Currency.USD,
        )


@pytest.mark.asyncio
async def test_repository_resolves_only_membership_version_known_at_cutoff():
    database = FakeDatabase()
    repository = BacktestInputRepository(database)
    original = member("OLD001", effective_from=date(2020, 1, 1))
    future_correction = original.model_copy(
        update={
            "known_at": at("2024-02-01T00:00:00"),
            "source_version": "universe-v2",
            "is_st": True,
        }
    )
    collection = database[repository.UNIVERSE_COLLECTION]
    await collection.insert_one(original.model_dump(mode="json"))
    await collection.insert_one(future_correction.model_dump(mode="json"))

    historical = await repository.list_universe_memberships(
        "fixture-universe",
        Market.CN,
        trade_date=date(2024, 1, 8),
        as_of=at("2024-01-08T07:00:00"),
    )
    corrected = await repository.list_universe_memberships(
        "fixture-universe",
        Market.CN,
        trade_date=date(2024, 2, 2),
        as_of=at("2024-02-02T07:00:00"),
    )

    assert len(historical) == 1 and historical[0].is_st is False
    assert len(corrected) == 1 and corrected[0].is_st is True


@pytest.mark.asyncio
async def test_repository_creates_point_in_time_indexes_idempotently():
    database = FakeDatabase()
    repository = BacktestInputRepository(database)

    await repository.ensure_indexes()
    first_counts = {
        name: len(collection.indexes)
        for name, collection in database.collections.items()
    }
    await repository.ensure_indexes()

    assert first_counts == {
        name: len(collection.indexes)
        for name, collection in database.collections.items()
    }
    assert set(database.collections) == {
        repository.UNIVERSE_COLLECTION,
        repository.CORPORATE_ACTION_COLLECTION,
        repository.BENCHMARK_COLLECTION,
        repository.MARKET_RULE_COLLECTION,
    }
