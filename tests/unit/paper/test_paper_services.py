import pytest

from app.models.paper import PriceSnapshot
from app.models.symbol import Market
from app.services.paper import (
    MongoPaperAccountService,
    MongoPaperMarketRuleService,
    PaperConsistencyError,
    PaperSymbolNormalizer,
    PaperTradingService,
    PaperValidationError,
)
from tests.unit.paper.fakes import FakeDatabase

pytestmark = pytest.mark.asyncio


class StaticPriceService:
    def __init__(self, prices):
        self.prices = prices

    async def get_snapshot(self, identity):
        price = self.prices.get((identity.market.value, identity.code))
        if price is None:
            return None
        return PriceSnapshot(
            market=identity.market,
            symbol=identity.symbol,
            price=price,
            quote_time="2026-01-02T03:04:05",
            source="fixture",
            latency_ms=0,
        )


async def seed_rules(database):
    await database["paper_market_rules"].insert_one(
        {
            "market": "CN",
            "rules": {
                "t_plus": 1,
                "commission": {
                    "rate": 0.0003,
                    "min": 5.0,
                    "stamp_duty_rate": 0.001,
                    "transfer_fee_rate": 0.00002,
                },
            },
        }
    )
    await database["paper_market_rules"].insert_one(
        {
            "market": "HK",
            "rules": {
                "t_plus": 0,
                "commission": {
                    "rate": 0.0003,
                    "min": 3.0,
                    "stamp_duty_rate": 0.0013,
                    "transaction_levy_rate": 0.00005,
                    "trading_fee_rate": 0.00005,
                    "settlement_fee_rate": 0.00002,
                },
            },
        }
    )
    await database["paper_market_rules"].insert_one(
        {
            "market": "US",
            "rules": {
                "t_plus": 0,
                "commission": {
                    "rate": 0.0,
                    "min": 0.0,
                    "sec_fee_rate": 0.0000278,
                },
            },
        }
    )


async def test_cn_hk_us_normalization_uses_canonical_identity_and_legacy_code():
    cn = PaperSymbolNormalizer.normalize(" 600519.sh ")
    hk = PaperSymbolNormalizer.normalize("0700.hk")
    us = PaperSymbolNormalizer.normalize(" brk-b ")

    assert (cn.market.value, cn.symbol, cn.currency.value, cn.code) == (
        "CN",
        "600519",
        "CNY",
        "600519",
    )
    assert (hk.market.value, hk.symbol, hk.currency.value, hk.code) == (
        "HK",
        "0700",
        "HKD",
        "00700",
    )
    assert (us.market.value, us.symbol, us.currency.value, us.code) == (
        "US",
        "BRK.B",
        "USD",
        "BRK.B",
    )


async def test_legacy_account_is_migrated_to_multi_currency_without_reset():
    database = FakeDatabase()
    await database["paper_accounts"].insert_one(
        {
            "user_id": "owner",
            "cash": 1234.5,
            "realized_pnl": 67.8,
            "updated_at": "old",
        }
    )

    account = await MongoPaperAccountService(database).get_or_create("owner")

    assert account["cash"] == {"CNY": 1234.5, "HKD": 0.0, "USD": 0.0}
    assert account["realized_pnl"] == {
        "CNY": 67.8,
        "HKD": 0.0,
        "USD": 0.0,
    }


async def test_commission_characterizes_existing_questionable_rules():
    database = FakeDatabase()
    await seed_rules(database)
    service = MongoPaperMarketRuleService(database)

    cn = await service.get_rules(Market.CN)
    hk = await service.get_rules(Market.HK)
    us = await service.get_rules(Market.US)

    assert service.calculate_commission(Market.CN, "buy", 1000, cn) == 5.0
    assert service.calculate_commission(Market.CN, "sell", 1000, cn) == 6.0
    assert service.calculate_commission(Market.HK, "sell", 1000, hk) == 4.42
    assert service.calculate_commission(Market.US, "sell", 1000, us) == 0.03


async def test_buy_sell_t_plus_one_and_legacy_pnl_semantics():
    database = FakeDatabase()
    await seed_rules(database)
    prices = StaticPriceService({("CN", "600519"): 10.0})
    service = PaperTradingService(database, prices=prices)

    bought = await service.place_order(
        user_id="owner",
        code="600519",
        market=None,
        side="buy",
        quantity=100,
        analysis_id="analysis-1",
    )
    assert bought["order"]["amount"] == 1000.0
    assert bought["order"]["commission"] == 5.0
    assert bought["order"]["analysis_id"] == "analysis-1"
    account = await database["paper_accounts"].find_one({"user_id": "owner"})
    assert account["cash"]["CNY"] == 998_995.0
    position = await database["paper_positions"].find_one(
        {"user_id": "owner", "code": "600519"}
    )
    assert position["quantity"] == 100
    assert position["available_qty"] == 0
    assert position["avg_cost"] == 10.0

    prices.prices[("CN", "600519")] = 12.0
    with pytest.raises(PaperValidationError, match="可用持仓不足"):
        await service.place_order(
            user_id="owner",
            code="600519",
            market="CN",
            side="sell",
            quantity=100,
        )

    database["paper_trades"].documents[0]["timestamp"] = "2000-01-01T00:00:00"
    sold = await service.place_order(
        user_id="owner",
        code="600519",
        market="CN",
        side="sell",
        quantity=100,
    )
    assert sold["order"]["commission"] == 6.2
    account = await database["paper_accounts"].find_one({"user_id": "owner"})
    assert account["cash"]["CNY"] == 1_000_188.8
    assert account["realized_pnl"]["CNY"] == 200.0
    assert (
        await database["paper_positions"].find_one(
            {"user_id": "owner", "code": "600519"}
        )
        is None
    )
    assert len(database["paper_orders"].documents) == 2
    assert len(database["paper_trades"].documents) == 2


async def test_insufficient_cash_and_position_do_not_write_orders():
    database = FakeDatabase()
    await seed_rules(database)
    service = PaperTradingService(
        database,
        prices=StaticPriceService({("US", "AAPL"): 200_000.0}),
    )

    with pytest.raises(PaperValidationError, match="可用USD不足"):
        await service.place_order(
            user_id="owner",
            code="AAPL",
            market="US",
            side="buy",
            quantity=1,
        )
    with pytest.raises(PaperValidationError, match="可用持仓不足"):
        await service.place_order(
            user_id="owner",
            code="AAPL",
            market="US",
            side="sell",
            quantity=1,
        )
    assert database["paper_orders"].documents == []
    assert database["paper_trades"].documents == []


async def test_account_positions_orders_and_reset_responses_are_preserved():
    database = FakeDatabase()
    await seed_rules(database)
    service = PaperTradingService(
        database,
        prices=StaticPriceService({("HK", "00700"): 300.0}),
    )
    await service.place_order(
        user_id="owner",
        code="0700.HK",
        market=None,
        side="buy",
        quantity=10,
    )

    overview = await service.get_account("owner")
    assert overview["account"]["cash"]["HKD"] == 996_996.64
    assert overview["account"]["positions_value"]["HKD"] == 3000.0
    assert overview["account"]["equity"]["HKD"] == 999_996.64
    assert overview["positions"][0]["code"] == "00700"
    assert (await service.list_positions("owner"))["items"][0]["quantity"] == 10
    assert (await service.list_orders("owner", 50))["items"][0]["status"] == "filled"

    reset = await service.reset("owner")
    assert reset["message"] == "账户已重置"
    assert reset["cash"] == {
        "CNY": 1_000_000.0,
        "HKD": 1_000_000.0,
        "USD": 100_000.0,
    }
    assert database["paper_positions"].documents == []
    assert database["paper_orders"].documents == []
    assert database["paper_trades"].documents == []


async def test_legacy_four_digit_hk_position_is_reused_without_migration():
    database = FakeDatabase()
    await seed_rules(database)
    await database["paper_positions"].insert_one(
        {
            "user_id": "owner",
            "code": "0700",
            "market": "HK",
            "currency": "HKD",
            "quantity": 5,
            "available_qty": 5,
            "frozen_qty": 0,
            "avg_cost": 280.0,
            "updated_at": "legacy",
        }
    )
    service = PaperTradingService(
        database,
        prices=StaticPriceService({("HK", "00700"): 300.0}),
    )

    await service.place_order(
        user_id="owner",
        code="0700.HK",
        market=None,
        side="buy",
        quantity=10,
    )

    assert len(database["paper_positions"].documents) == 1
    position = database["paper_positions"].documents[0]
    assert position["code"] == "0700"
    assert position["quantity"] == 15
    assert position["available_qty"] == 15
    assert position["avg_cost"] == 293.3333


async def test_partial_account_position_failure_is_explicit_and_recoverable():
    database = FakeDatabase()
    await seed_rules(database)
    service = PaperTradingService(
        database,
        prices=StaticPriceService({("CN", "600519"): 10.0}),
    )
    database["paper_positions"].fail_next["insert_one"] = RuntimeError(
        "fixture position failure"
    )

    with pytest.raises(PaperConsistencyError) as exc_info:
        await service.place_order(
            user_id="owner",
            code="600519",
            market="CN",
            side="buy",
            quantity=100,
        )

    assert exc_info.value.recovery_id
    account = await database["paper_accounts"].find_one({"user_id": "owner"})
    assert account["cash"]["CNY"] == 998_995.0
    recovery = database["paper_consistency_recovery"].documents[0]
    assert recovery["recovery_id"] == exc_info.value.recovery_id
    assert recovery["operation"] == "buy"
    assert recovery["failed_stage"] == "position"
    assert recovery["completed_stages"] == ["account"]
    assert recovery["status"] == "pending"
    assert database["paper_orders"].documents == []
    assert database["paper_trades"].documents == []
