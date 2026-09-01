from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone

import pytest

from app.models.factor import FactorSnapshot, FactorSnapshotStatus, FactorValueRow
from app.models.strategy import (
    SYSTEM_USER_ID,
    StrategyVersion,
    StrategyVersionStatus,
    StrategyVisibility,
    UniverseMember,
    UniverseSnapshot,
)
from app.repositories.strategy_repository import StrategyRepository
from app.services.strategies.signal_engine import DeterministicSignalEngine
from app.services.strategies.templates import (
    SYSTEM_STRATEGY_TEMPLATES,
    SYSTEM_TEMPLATE_IDS,
)
from app.services.strategies.templates.seeder import seed_system_strategy_templates
from app.services.strategies.validator import StrategyDSLValidator
from app.services.strategies.version_service import (
    StrategyPermissionDenied,
    StrategyVersionService,
)
from tests.strategy_fakes import FakeDatabase


EXPECTED_IDS = (
    "value_quality",
    "growth_quality",
    "momentum_20_60",
    "low_volatility",
    "high_dividend_quality",
    "mean_reversion_rsi",
    "trend_following",
    "breakout_60",
    "volume_price_confirmation",
    "sentiment_reversal",
    "sentiment_momentum",
    "multi_factor_balanced",
    "industry_rotation",
    "defensive_risk_off",
)
TRADE_DATE = date(2025, 6, 2)  # Monday and monthly day-of-month 2.
EVALUATED_AT = datetime(2025, 6, 2, 10, tzinfo=timezone.utc)
SYMBOLS = ("000001", "000002", "000003")


def test_catalog_has_exactly_the_fourteen_active_specification_ids():
    assert SYSTEM_TEMPLATE_IDS == EXPECTED_IDS
    assert len(SYSTEM_STRATEGY_TEMPLATES) == len(set(SYSTEM_TEMPLATE_IDS)) == 14


@pytest.mark.parametrize("template", SYSTEM_STRATEGY_TEMPLATES, ids=SYSTEM_TEMPLATE_IDS)
def test_template_contract_is_complete_and_dsl_is_valid(template):
    assert template.version == 1
    assert template.formula
    assert template.parameter_ranges
    assert template.suitable_markets
    assert template.unsuitable_scenarios
    assert "不代表未来收益" in template.risk_warning
    assert template.minimum_history >= 1
    assert template.benchmark == "CN:000300"
    assert template.fee_model_version == "cn-a-v1"
    assert template.slippage_bps == 5
    assert set(template.signal_fixture.factor_values) == set(template.factor_ids)
    assert set(template.no_signal_fixture.factor_values) == set(template.factor_ids)
    for parameter in template.parameter_ranges:
        assert parameter.minimum <= parameter.default <= parameter.maximum
        assert parameter.unit and parameter.sensitivity

    report = StrategyDSLValidator().validate(
        template.definition_copy(), market=template.market, user_id=SYSTEM_USER_ID
    )
    assert report.valid, report.errors
    assert {item.factor_id for item in report.factor_dependencies} == set(template.factor_ids)


@pytest.mark.parametrize("template", SYSTEM_STRATEGY_TEMPLATES, ids=SYSTEM_TEMPLATE_IDS)
def test_each_template_signal_and_no_signal_fixtures_execute(template):
    signal_result = _evaluate(template, template.signal_fixture.factor_values)
    no_signal_result = _evaluate(template, template.no_signal_fixture.factor_values)

    assert any(item.signal_type == "buy" for item in signal_result.signals)
    assert not any(item.signal_type == "buy" for item in no_signal_result.signals)


@pytest.mark.asyncio
async def test_seed_migration_is_idempotent_published_and_readonly():
    database = FakeDatabase()
    repository = StrategyRepository(database)

    first = await seed_system_strategy_templates(repository)
    first_version_checksums = tuple(version.checksum for _, version in first)
    strategy_count = len(database[repository.STRATEGIES_COLLECTION].documents)
    version_count = len(database[repository.VERSIONS_COLLECTION].documents)
    second = await seed_system_strategy_templates(repository)

    assert len(first) == len(second) == 14
    assert len(database[repository.STRATEGIES_COLLECTION].documents) == strategy_count == 14
    assert len(database[repository.VERSIONS_COLLECTION].documents) == version_count == 14
    assert tuple(version.checksum for _, version in second) == first_version_checksums
    assert {strategy.strategy_id for strategy, _ in first} == {
        f"system-template:{template_id}" for template_id in EXPECTED_IDS
    }
    assert all(
        strategy.user_id == SYSTEM_USER_ID
        and strategy.visibility == StrategyVisibility.SYSTEM
        and strategy.current_draft_version_id is None
        and strategy.archived_at is None
        and version.status == StrategyVersionStatus.PUBLISHED
        and version.validation_result is not None
        and version.validation_result.valid
        for strategy, version in second
    )
    with pytest.raises(StrategyPermissionDenied, match="read-only"):
        await StrategyVersionService(repository).archive_strategy(
            first[0][0].strategy_id, user_id=SYSTEM_USER_ID
        )


def _evaluate(template, selected_values):
    universe = UniverseSnapshot(
        universe_snapshot_id="system-template-fixture-universe",
        user_id="fixture-user",
        market=template.market,
        trade_date=TRADE_DATE,
        as_of=datetime(2025, 6, 2, 1, tzinfo=timezone.utc),
        members=tuple(
            UniverseMember(market=template.market, symbol=symbol) for symbol in SYMBOLS
        ),
        source_versions={"security_master": "fixture-v1"},
        selection_definition={"market": template.market.value, "point_in_time": True},
        created_at=datetime(2025, 6, 2, 1, tzinfo=timezone.utc),
    )
    snapshots = []
    rows = []
    first_date = TRADE_DATE - timedelta(days=template.minimum_history - 1)
    fallback = template.no_signal_fixture.factor_values
    factor_count = len(template.factor_ids)
    for offset in range(template.minimum_history):
        trade_date = first_date + timedelta(days=offset)
        snapshot_id = hashlib.sha256(
            f"{template.template_id}:{selected_values}:{trade_date}".encode()
        ).hexdigest()
        visible_at = datetime.combine(trade_date, datetime.min.time(), timezone.utc) + timedelta(hours=1)
        snapshots.append(
            FactorSnapshot(
                snapshot_id=snapshot_id,
                user_id="fixture-user",
                job_id=f"fixture-{template.template_id}",
                task_id=f"fixture-{template.template_id}",
                market=template.market,
                trade_date=trade_date,
                as_of=visible_at,
                universe_snapshot_id=universe.universe_snapshot_id,
                factor_set_checksum="a" * 64,
                request_checksum="b" * 64,
                status=FactorSnapshotStatus.READY,
                expected_row_count=3,
                expected_factor_count=factor_count,
                row_count=3,
                factor_count=factor_count,
                source_versions={"daily": trade_date.isoformat()},
                values_checksum="c" * 64,
                created_at=visible_at,
                updated_at=visible_at,
                published_at=visible_at + timedelta(minutes=1),
            )
        )
        for symbol in SYMBOLS:
            values = selected_values if symbol == SYMBOLS[0] else fallback
            rows.append(
                FactorValueRow(
                    snapshot_id=snapshot_id,
                    market=template.market,
                    symbol=symbol,
                    trade_date=trade_date,
                    values=dict(values),
                    quality={factor_id: "ok" for factor_id in template.factor_ids},
                )
            )

    version = StrategyVersion(
        strategy_version_id=template.strategy_version_id,
        strategy_id=template.strategy_id,
        user_id=SYSTEM_USER_ID,
        version=template.version,
        market=template.market,
        definition=template.definition_copy(),
        created_by=SYSTEM_USER_ID,
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        change_summary="fixture execution",
    )
    metadata = {
        symbol: {
            "listing_days": 1_000,
            "is_st": False,
            "is_delisting": False,
            "is_suspended": False,
            "industry": "fixture-industry",
            "market_cap": 10_000_000_000,
        }
        for symbol in SYMBOLS
    }
    return DeterministicSignalEngine().evaluate(
        version=version,
        universe=universe,
        factor_snapshots=tuple(snapshots),
        factor_rows=tuple(rows),
        as_of=EVALUATED_AT,
        user_id="fixture-user",
        metadata_by_symbol=metadata,
    )
