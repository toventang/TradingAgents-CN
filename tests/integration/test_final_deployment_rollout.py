import pytest
from app.migrations.seed_system_templates import seed_system_templates
from app.migrations.seed_system_skills import seed_system_skills
from app.migrations.migrate_paper_trading_ledger import migrate_legacy_paper_trading


class MockCollection:
    def __init__(self, data=None):
        self.data = data if data is not None else []

    async def insert_one(self, doc):
        self.data.append(dict(doc))
        return True

    async def update_one(self, query, update, upsert=False):
        doc = await self.find_one(query)
        if not doc:
            if upsert:
                new_doc = {}
                if "$set" in update:
                    new_doc.update(update["$set"])
                self.data.append(new_doc)
                return True
            return False
        if "$set" in update:
            for k, v in update["$set"].items():
                doc[k] = v
        return True

    async def find_one(self, query):
        for d in self.data:
            if all(d.get(k) == v for k, v in query.items()):
                return dict(d)
        return None

    def find(self, query=None):
        query = query or {}
        filtered = [dict(d) for d in self.data if all(d.get(k) == v for k, v in query.items())]

        class Cursor:
            def __init__(self, items):
                self.items = items
            def __aiter__(self):
                return self._gen()
            async def _gen(self):
                for item in self.items:
                    yield item
        return Cursor(filtered)


class MockDB(dict):
    def __getitem__(self, item):
        if item not in self:
            self[item] = MockCollection()
        return super().__getitem__(item)


@pytest.mark.asyncio
async def test_migration_idempotency_and_deployment_readiness():
    db = MockDB()

    # 1. Seed system templates twice -> 14 templates, idempotent second run
    count_templates_1 = await seed_system_templates(db=db)
    assert count_templates_1 == 14

    count_templates_2 = await seed_system_templates(db=db)
    assert count_templates_2 == 14  # Upsert idempotency

    # 2. Seed system skills twice -> 6 skills, idempotent second run
    count_skills_1 = await seed_system_skills(db=db)
    assert count_skills_1 == 6

    count_skills_2 = await seed_system_skills(db=db)
    assert count_skills_2 == 6  # Upsert idempotency

    # 3. Paper trading migration idempotency
    db["paper_trading_accounts"].data = [{"user_id": "legacy_u1", "balance": 100000.0}]
    migrated_1 = await migrate_legacy_paper_trading(db=db)
    assert migrated_1 == 1

    migrated_2 = await migrate_legacy_paper_trading(db=db)
    assert migrated_2 == 0  # Second run skips already migrated
