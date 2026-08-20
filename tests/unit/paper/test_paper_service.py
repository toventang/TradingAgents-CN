import pytest
from app.services.paper.paper_service import (
    PaperTradingService,
    detect_market_and_code,
    INITIAL_CASH_BY_MARKET
)
from tests.integration.test_domain_task_repository import FakeDatabase


def test_detect_market_and_code():
    assert detect_market_and_code("000001") == ("CN", "000001")
    assert detect_market_and_code("0700.HK") == ("HK", "00700")
    assert detect_market_and_code("AAPL") == ("US", "AAPL")
    assert detect_market_and_code("0700") == ("HK", "00700")


def test_calculate_commission():
    service = PaperTradingService()

    cn_rules = {
        "commission": {
            "rate": 0.0003,
            "min": 5.0,
            "stamp_duty_rate": 0.001
        }
    }

    # Buy CN stock: amount 10000 -> comm_rate=3 (below min 5) -> commission = 5.0
    comm_buy = service.calculate_commission("CN", "buy", 10000.0, cn_rules)
    assert comm_buy == 5.0

    # Sell CN stock: amount 10000 -> min comm 5.0 + stamp duty 10.0 = 15.0
    comm_sell = service.calculate_commission("CN", "sell", 10000.0, cn_rules)
    assert comm_sell == 15.0


@pytest.mark.asyncio
async def test_get_or_create_account():
    db = FakeDatabase()
    service = PaperTradingService(db=db)

    acc = await service.get_or_create_account("user_test")
    assert acc["user_id"] == "user_test"
    assert acc["cash"]["CNY"] == INITIAL_CASH_BY_MARKET["CNY"]
    assert acc["cash"]["HKD"] == INITIAL_CASH_BY_MARKET["HKD"]
    assert acc["cash"]["USD"] == INITIAL_CASH_BY_MARKET["USD"]


@pytest.mark.asyncio
async def test_buy_and_insufficient_cash():
    db = FakeDatabase()
    service = PaperTradingService(db=db)

    # Seed mock market quote for price lookup
    await db["market_quotes"].insert_one({"code": "000001", "close": 10.0})

    # Insufficient cash error
    with pytest.raises(ValueError, match="可用CNY不足"):
        await service.place_order("user_test", "000001", "buy", quantity=1_000_000, market="CN")


@pytest.mark.asyncio
async def test_reset_account():
    db = FakeDatabase()
    service = PaperTradingService(db=db)

    await service.get_or_create_account("user_test")
    res = await service.reset_account("user_test")
    assert res["user_id"] == "user_test"
