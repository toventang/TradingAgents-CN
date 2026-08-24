import asyncio
from app.core.database import get_mongo_db
from app.models.paper import PaperPortfolio, PositionLot, LedgerEntry, LedgerEntryType
from app.utils.timezone import now_tz


async def migrate_legacy_paper_trading(db=None) -> int:
    """
    幂等迁移旧版模拟账户数据至隔离 Portfolio / Lot / Double-Entry Ledger。
    """
    if db is None:
        db = get_mongo_db()

    cursor = db["paper_trading_accounts"].find()
    migrated_count = 0
    now = now_tz()

    async for acc in cursor:
        user_id = acc.get("user_id", "unknown_user")
        portfolio_id = f"p_migrated_{user_id}"

        # 检查是否已存在
        existing = await db["paper_portfolios"].find_one({"portfolio_id": portfolio_id})
        if not existing:
            cash = float(acc.get("balance", 1000000.0))
            portfolio = PaperPortfolio(
                portfolio_id=portfolio_id,
                user_id=user_id,
                name=f"Migrated Portfolio ({user_id})",
                initial_capital=cash,
                cash=cash,
                total_equity=cash,
                created_at=now,
                updated_at=now
            )
            await db["paper_portfolios"].insert_one(portfolio.model_dump())

            # 写入初始充值分录
            entry = LedgerEntry(
                entry_id=f"entry_init_{portfolio_id}",
                portfolio_id=portfolio_id,
                entry_type=LedgerEntryType.DEPOSIT,
                amount=cash,
                balance_after=cash,
                description="Initial deposit migration",
                created_at=now
            )
            await db["paper_ledger"].insert_one(entry.model_dump())
            migrated_count += 1

    return migrated_count


if __name__ == "__main__":
    count = asyncio.run(migrate_legacy_paper_trading())
    print(f"Successfully migrated {count} legacy paper trading accounts.")
