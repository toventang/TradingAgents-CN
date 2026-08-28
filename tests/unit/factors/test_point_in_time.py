from datetime import datetime, timezone

import pytest

from app.services.factors.point_in_time import (
    point_in_time_snapshots,
    resolve_point_in_time,
)


UTC = timezone.utc


def _time(year, month, day):
    return datetime(year, month, day, tzinfo=UTC)


def _fact(fact_id, period, publish_at, **data):
    return {
        "fact_id": fact_id,
        "market": "US",
        "symbol": "AAA",
        "report_period": period,
        "publish_at": publish_at,
        "source": "fixture",
        "source_version": "v1",
        "data": data,
    }


def test_publication_boundary_and_forward_fill_stop_at_next_publication():
    facts = [
        _fact("q1", "2025Q1", _time(2025, 5, 1), revenue=10),
        _fact("q2", "2025Q2", _time(2025, 8, 1), revenue=20),
    ]
    snapshots = point_in_time_snapshots(
        facts,
        [
            _time(2025, 4, 30),
            _time(2025, 5, 1),
            _time(2025, 7, 31),
            _time(2025, 8, 1),
        ],
        market="US",
        symbol="AAA",
    )
    assert snapshots[0].current_period is None
    assert snapshots[1].value("revenue") == 10
    assert snapshots[2].value("revenue") == 10
    assert snapshots[3].value("revenue") == 20
    assert snapshots[3].evidence["revenue"][0].fact_id == "q2"


def test_restatement_is_visible_only_when_published_and_preserves_evidence():
    facts = [
        _fact("q1-original", "2024Q1", _time(2024, 4, 1), revenue=100),
        _fact("q1-restated", "2024Q1", _time(2024, 6, 1), revenue=120),
    ]
    original = resolve_point_in_time(facts, as_of=_time(2024, 5, 31))
    restated = resolve_point_in_time(facts, as_of=_time(2024, 6, 1))
    assert original.value("revenue") == 100
    assert restated.value("revenue") == 120
    evidence = restated.evidence["revenue"][0]
    assert evidence.fact_id == "q1-restated"
    assert evidence.report_period == "2024Q1"
    assert evidence.publish_at == _time(2024, 6, 1)


def test_late_older_report_does_not_replace_current_period():
    facts = [
        _fact("q2", "2024Q2", _time(2024, 8, 1), revenue=200),
        _fact("late-q1", "2024Q1", _time(2024, 9, 1), revenue=100),
    ]
    snapshot = resolve_point_in_time(facts, as_of=_time(2024, 9, 2))
    assert snapshot.current_period == "2024Q2"
    assert snapshot.value("revenue") == 200
    assert [report.report_period for report in snapshot.reports] == ["2024Q1", "2024Q2"]


def test_ytd_quarter_conversion_and_ttm_are_explicit_and_deterministic():
    facts = [
        _fact("q1", "2024Q1", _time(2024, 4, 1), revenue=10),
        _fact("q2", "2024Q2", _time(2024, 7, 1), revenue=30),
        _fact("q3", "2024Q3", _time(2024, 10, 1), revenue=60),
        _fact("q4", "2024Q4", _time(2025, 3, 1), revenue=100),
    ]
    snapshot = resolve_point_in_time(
        facts, as_of=_time(2025, 3, 2), flow_basis="ytd"
    )
    assert [report.values["revenue"] for report in snapshot.reports] == [10, 20, 30, 40]
    assert snapshot.value("revenue_ttm") == 100
    assert len(snapshot.evidence["revenue_ttm"]) == 4


def test_missing_quarter_prevents_ttm_and_naive_datetimes_are_rejected():
    facts = [
        _fact("q1", "2024Q1", _time(2024, 4, 1), revenue=10),
        _fact("q3", "2024Q3", _time(2024, 10, 1), revenue=30),
        _fact("q4", "2024Q4", _time(2025, 3, 1), revenue=40),
        _fact("q1-next", "2025Q1", _time(2025, 4, 1), revenue=50),
    ]
    snapshot = resolve_point_in_time(facts, as_of=_time(2025, 4, 2))
    assert snapshot.value("revenue_ttm") is None
    with pytest.raises(ValueError, match="timezone-aware"):
        resolve_point_in_time(facts, as_of=datetime(2025, 4, 2))
