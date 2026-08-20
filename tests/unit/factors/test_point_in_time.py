import pytest
from datetime import datetime, timedelta
from app.services.factors.point_in_time import PointInTimeService
from app.utils.timezone import now_tz
from tests.integration.test_domain_task_repository import FakeDatabase

@pytest.mark.asyncio
async def test_point_in_time_publication_boundary():
    db = FakeDatabase()
    service = PointInTimeService(db=db)

    now = now_tz()
    published_yesterday = now - timedelta(days=1)
    published_tomorrow = now + timedelta(days=1)

    await db["stock_financial_data"].insert_one({
        "code": "000001",
        "symbol": "000001",
        "report_period": "2024Q1",
        "publish_at": published_yesterday.isoformat(),
        "data": {"pe_ttm": 12.5, "roe": 0.15}
    })

    await db["stock_financial_data"].insert_one({
        "code": "000001",
        "symbol": "000001",
        "report_period": "2024Q2",
        "publish_at": published_tomorrow.isoformat(),
        "data": {"pe_ttm": 10.0, "roe": 0.18}
    })

    # As of now -> receives 2024Q1 published yesterday
    obs = await service.get_latest_observation("000001", "CN", as_of=now)
    assert obs is not None
    assert obs.report_period == "2024Q1"
    assert obs.data["pe_ttm"] == 12.5

    # As of day after tomorrow -> receives 2024Q2
    obs_future = await service.get_latest_observation("000001", "CN", as_of=now + timedelta(days=2))
    assert obs_future is not None
    assert obs_future.report_period == "2024Q2"
