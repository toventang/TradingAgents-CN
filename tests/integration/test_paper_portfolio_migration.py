import pytest
from app.migrations.migrate_paper_trading_ledger import migrate_legacy_paper_trading


@pytest.mark.asyncio
async def test_legacy_paper_trading_migration():
    fake_legacy = [
        {"user_id": "u_legacy_1", "balance": 500000.0},
        {"user_id": "u_legacy_2", "balance": 200000.0}
    ]
    fake_portfolios = []
    fake_ledger = []

    class MockCollection:
        def __init__(self, data):
            self.data = data

        def find(self, query=None):
            class Cursor:
                def __init__(self, items):
                    self.items = items
                def __aiter__(self):
                    return self._gen()
                async def _gen(self):
                    for item in self.items:
                        yield item
            return Cursor(self.data)

        async def find_one(self, query):
            for d in self.data:
                if all(d.get(k) == v for k, v in query.items()):
                    return dict(d)
            return None

        async def insert_one(self, doc):
            self.data.append(dict(doc))
            return True

    class MockDB(dict):
        def __init__(self):
            self["paper_trading_accounts"] = MockCollection(fake_legacy)
            self["paper_portfolios"] = MockCollection(fake_portfolios)
            self["paper_ledger"] = MockCollection(fake_ledger)

        def __getitem__(self, item):
            if item not in self:
                self[item] = MockCollection([])
            return super().__getitem__(item)

    db = MockDB()
    migrated_1 = await migrate_legacy_paper_trading(db=db)
    assert migrated_1 == 2

    # Idempotency check
    migrated_2 = await migrate_legacy_paper_trading(db=db)
    assert migrated_2 == 0
