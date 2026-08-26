import pytest
from datetime import datetime
from app.models.strategy import UniverseSnapshot
from app.models.backtest import BacktestConfig, CostSlippageModel
from app.models.risk import RiskConfig
from app.models.attribution import TradeReviewInput
from app.services.strategies.version_service import VersionService
from app.services.strategies.signal_engine import DeterministicSignalEngine
from app.services.backtest.engine import BacktestExecutionEngine
from app.services.paper.ledger_service import LedgerService
from app.services.campaigns.lifecycle_service import CampaignLifecycleService
from app.services/campaigns.cycle_engine import CampaignCycleEngine
from app.services/risk/pre_trade import PreTradeRiskService
from app.services/learning/attribution import TradeAttributionService
from app.services/learning/counterfactual import CounterfactualService
from app.services/learning/ai_review import AITradeReviewService
from app.services/learning/proposals import LearningProposalService
from tests.fixtures.e2e_market_data import generate_20_stock_120_day_fixture


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
        if "$inc" in update:
            for k, v in update["$inc"].items():
                doc[k] = doc.get(k, 0.0) + v
        if "$set" in update:
            for k, v in update["$set"].items():
                doc[k] = v
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
async def test_full_program_e2e_pipeline():
    # 1. Load 20-Stock / 120-Day Market Data Fixture
    symbols, dates, prices_df, factors_df, bm_prices = generate_20_stock_120_day_fixture()
    assert len(symbols) == 20
    assert len(dates) == 120

    db = FakeDB()

    # 2. Strategy Creation & Publishing
    v_service = VersionService(repo=None)
    univ = UniverseSnapshot(universe_id="u_e2e", user_id="u_e2e", symbols=symbols)
    strat, ver_v1 = await v_service.create_strategy(
        user_id="u_e2e",
        name="E2E Strategy",
        parameters={"weights": {"ret_1d": 0.6, "ret_5d": 0.4}},
        rules={"conditions": {"op": ">", "factor_id": "ret_1d", "value": 0.0}, "top_k": 5},
        universe=univ
    )
    pub_ver = await v_service.publish_version(strat.strategy_id, "u_e2e")
    assert pub_ver.is_published is True

    # 3. Deterministic Signal Engine Execution
    sig_engine = DeterministicSignalEngine()
    signals = sig_engine.generate_signals(pub_ver, "u_e2e", datetime.strptime(dates[0], "%Y-%m-%d"), factors_df.loc[dates[0]])
    assert len(signals) == 20
    buy_signals = [s for s in signals if s.signal_type == "buy"]
    assert len(buy_signals) == 5

    # 4. Point-In-Time Backtest Execution
    bt_engine = BacktestExecutionEngine(signal_engine=sig_engine)
    bt_config = BacktestConfig(
        strategy_id=strat.strategy_id,
        version_num=1,
        start_date=dates[0],
        end_date=dates[-1],
        initial_capital=1000000.0,
        cost_model=CostSlippageModel()
    )
    bt_res = bt_engine.run_backtest("bt_e2e_1", "u_e2e", bt_config, pub_ver, prices_df, factors_df, bm_prices)
    assert bt_res.status.value == "completed"
    assert len(bt_res.equity_curve) == 120
    assert bt_res.metrics is not None

    # 5. Pre-Trade Risk Check
    risk_service = PreTradeRiskService()
    risk_cfg = RiskConfig(max_stock_weight=0.20, block_limit_up_buy=True)
    proposed_trades = [{"symbol": symbols[0], "side": "buy", "quantity": 1000, "price": 10.0}]
    risk_res = risk_service.check_pre_trade_orders(risk_cfg, 1000000.0, 1000000.0, {}, proposed_trades)
    assert risk_res["is_blocked"] is False

    # 6. Trade Attribution (MAE/MFE) & Legal Counterfactuals
    trade_inp = TradeReviewInput(
        trade_id="tr_e2e_1",
        symbol=symbols[0],
        entry_date=dates[0],
        exit_date=dates[10],
        entry_price=10.0,
        exit_price=11.5,
        quantity=1000,
        daily_prices=[10.0 + i * 0.15 for i in range(11)],
        daily_benchmark_prices=[1000.0 + i * 2.0 for i in range(11)]
    )
    attr_res = TradeAttributionService.analyze_trade(trade_inp)
    assert attr_res.metrics.realized_pnl_pct == 0.15

    cf_res = CounterfactualService.analyze_post_exit_paths(
        trade_id="tr_e2e_1",
        symbol=symbols[0],
        exit_price=11.5,
        post_exit_prices=[11.5 + i * 0.1 for i in range(60)],
        post_exit_bm_prices=[1020.0 + i * 1.5 for i in range(60)]
    )
    assert cf_res.is_legal_tradeable is True

    # 7. Evidence-Bound AI Trade Review & Controlled Learning Proposals
    ai_service = AITradeReviewService(is_test_env=True)
    ai_review = await ai_service.generate_review(attr_res, cf_res)
    assert ai_review.grounding.is_sufficient is True

    proposal_service = LearningProposalService(strategy_repo=None)
    reviews = [ai_review] * 5
    proposal = proposal_service.generate_proposal_from_reviews("c_e2e", strat.strategy_id, reviews, pub_ver, min_sample_gate=5)
    assert proposal.status.value == "proposed"
    assert len(proposal.diff_items) >= 1
