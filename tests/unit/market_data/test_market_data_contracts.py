from datetime import datetime, timedelta, timezone

import pytest

from app.models.market_data import DataQualityStatus, NewsSocialInput, PointInTimeFact
from app.services.market_data.benchmarks import BenchmarkRegistry
from app.services.market_data.market_data_service import MarketDataReadService


class FakeCursor:
    def __init__(self, items):
        self.items = items

    async def to_list(self, length=None):
        return list(self.items if length is None else self.items[:length])


class FakeCollection:
    def __init__(self, items=()):
        self.items = list(items)

    def find(self, query):
        symbol = next(iter(query.get("$or", [{}]))).get("symbol")
        return FakeCursor([
            item for item in self.items
            if not symbol or item.get("symbol") == symbol or item.get("code") == symbol
        ])


class FakeDatabase:
    def __init__(self, **collections):
        self.collections = {name: FakeCollection(items) for name, items in collections.items()}

    def __getitem__(self, name):
        return self.collections.setdefault(name, FakeCollection())


def test_point_in_time_models_enforce_visibility_boundaries():
    now = datetime(2026, 8, 28, 8, tzinfo=timezone.utc)
    fact = PointInTimeFact(
        fact_id="f1", symbol="000001", market="CN", report_period="2024Q1",
        publish_at=now + timedelta(seconds=1), fact_type="financial", data={"roe": 0.15},
    )
    assert fact.is_visible_at(now) is False
    news = NewsSocialInput(
        news_id="n1", symbol="AAPL", market="US", published_at=now - timedelta(hours=1),
        ingested_at=now + timedelta(seconds=1), title="news",
    )
    assert news.is_visible_at(now) is False
    assert news.is_visible_at(now + timedelta(seconds=2)) is True


@pytest.mark.asyncio
async def test_daily_adapter_converts_percent_deduplicates_and_sorts():
    db = FakeDatabase(stock_daily_quotes=[
        {"symbol": "000001", "market": "CN", "trade_date": "2026-08-22", "period": "daily",
         "open": 10, "high": 11, "low": 9, "close": 10.5, "pre_close": 10,
         "volume": 100, "amount": 1000, "adj_factor": 1, "pct_chg": 5,
         "data_source": "old", "version": 1, "updated_at": datetime(2026, 8, 22, tzinfo=timezone.utc)},
        {"symbol": "000001", "market": "CN", "trade_date": "2026-08-22", "period": "daily",
         "open": 10, "high": 11, "low": 9, "close": 10.6, "pre_close": 10,
         "volume": 100, "amount": 1000, "adj_factor": 1, "pct_chg": 6,
         "data_source": "new", "version": 2, "updated_at": datetime(2026, 8, 23, tzinfo=timezone.utc)},
    ])
    batch = await MarketDataReadService(db).read_daily_bars(
        "000001", "CN", as_of=datetime(2026, 8, 24, tzinfo=timezone.utc)
    )
    assert len(batch.items) == 1
    assert batch.items[0].close == 10.6
    assert batch.items[0].pct_chg == pytest.approx(0.06)
    assert batch.quality.status == DataQualityStatus.PARTIAL
    assert batch.quality.reason_code == "DUPLICATE_BAR"
    assert batch.source_version == "2"


@pytest.mark.asyncio
async def test_financial_adapter_never_uses_report_period_as_visibility():
    now = datetime(2026, 8, 28, tzinfo=timezone.utc)
    db = FakeDatabase(stock_financial_data=[
        {"_id": "visible", "symbol": "000001", "report_period": "20261231",
         "ann_date": "20260820", "created_at": datetime(2026, 8, 21, tzinfo=timezone.utc)},
        {"_id": "future", "symbol": "000001", "report_period": "20200101",
         "publish_at": now + timedelta(days=1), "created_at": now},
        {"_id": "missing", "symbol": "000001", "report_period": "20191231"},
    ])
    batch = await MarketDataReadService(db).read_point_in_time_facts("000001", "CN", as_of=now)
    assert [fact.fact_id for fact in batch.items] == ["visible"]
    assert batch.quality.status == DataQualityStatus.PARTIAL
    assert batch.quality.details["excluded_missing_publication"] == 1


@pytest.mark.asyncio
async def test_news_requires_published_and_ingested_timestamps():
    now = datetime(2026, 8, 28, tzinfo=timezone.utc)
    db = FakeDatabase(stock_news=[
        {"_id": "ok", "symbol": "AAPL", "publish_time": now - timedelta(hours=2),
         "created_at": now - timedelta(hours=1), "title": "visible"},
        {"_id": "late", "symbol": "AAPL", "publish_time": now - timedelta(hours=2),
         "created_at": now + timedelta(seconds=1), "title": "backfilled later"},
        {"_id": "incomplete", "symbol": "AAPL", "publish_time": now, "title": "no ingestion"},
    ])
    batch = await MarketDataReadService(db).read_news_inputs("AAPL", "US", as_of=now)
    assert [item.news_id for item in batch.items] == ["ok"]
    assert batch.quality.status == DataQualityStatus.PARTIAL


def test_benchmark_identity_is_stable_and_market_scoped():
    assert BenchmarkRegistry.default_for("CN").benchmark_id == "CN.CSI300"
    assert BenchmarkRegistry.default_for("US").symbol == "SPX"
