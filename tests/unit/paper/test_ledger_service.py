import pytest
from app.models.paper import PaperPortfolio
from app.repositories.paper_repository import PaperRepository
from app.services.paper.ledger_service import LedgerService


class FakeCollection:
    def __init__(self):
        self.docs = []

    async def insert_one(self, doc):
        self.docs.append(dict(doc))
        return True

    async def find_one(self, query):
        for d in self.docs:
            if all(d.get(k) == v for k, v in query.items()):
                return dict(d)
        return None

    def find(self, query):
        filtered = [dict(d) for d in self.docs if all(d.get(k) == v for k, v in query.items())]

        class Cursor:
            def __init__(self, items):
                self.items = items

            def sort(self, k, d=1):
                self.items.sort(key=lambda x: x.get(k, 0), reverse=(d == -1))
                return self

            def limit(self, n):
                self.items = self.items[:n]
                return self

            def __aiter__(self):
                return self._gen()

            async def _gen(self):
                for item in self.items:
                    yield item

        return Cursor(filtered)

    async def find_one_and_update(self, query, update, return_document=True):
        doc = await self.find_one(query)
        if not doc:
            return None

        # Check conditions
        if "cash" in query and "$gte" in query["cash"]:
            if doc.get("cash", 0.0) < query["cash"]["$gte"]:
                return None

        if "$inc" in update:
            for k, v in update["$inc"].items():
                doc[k] = doc.get(k, 0.0) + v

        for i, d in enumerate(self.docs):
            if d.get("portfolio_id") == query.get("portfolio_id"):
                self.docs[i] = dict(doc)
                break

        return doc

    async def update_one(self, query, update, upsert=False):
        doc = await self.find_one(query)
        if not doc:
            if upsert:
                new_doc = {}
                if "$set" in update:
                    new_doc.update(update["$set"])
                self.docs.append(new_doc)
                return True
            return False
        if "$set" in update:
            for k, v in update["$set"].items():
                doc[k] = v
        return True


class FakeDB(dict):
    def __getitem__(self, item):
        if item not in self:
            self[item] = FakeCollection()
        return super().__getitem__(item)


@pytest.mark.asyncio
async def test_ledger_service_atomic_buy_and_reconciliation():
    db = FakeDB()
    repo = PaperRepository(db=db)
    service = LedgerService(repo=repo)

    p = PaperPortfolio(portfolio_id="p_test_atomic", user_id="u1", cash=100000.0, total_equity=100000.0)
    await repo.create_portfolio(p)

    # Execute trade buy: 1000 shares @ 10.0 RMB (total cost 10000 + commission 5.0 = 10005.0)
    ok = await service.execute_trade_buy("p_test_atomic", "600000.SH", 1000, 10.0, 5.0, 0.10)
    assert ok is True

    # Portfolio cash updated atomically
    p_updated = await repo.get_portfolio("p_test_atomic")
    assert p_updated.cash == 89994.90

    # Overdraft attempt fails atomically
    fail_ok = await service.execute_trade_buy("p_test_atomic", "600000.SH", 100000, 10.0, 5.0, 0.10)
    assert fail_ok is False

    # Reconciliation check
    recon = await repo.reconcile("p_test_atomic")
    assert recon.is_balanced is True
