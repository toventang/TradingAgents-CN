import pytest
import pandas as pd
from datetime import datetime
from app.models.strategy import StrategyVersion, UniverseSnapshot
from app.services.strategies.signal_engine import DeterministicSignalEngine
from app.utils.timezone import now_tz


def test_signal_engine_deterministic_execution():
    engine = DeterministicSignalEngine()

    univ = UniverseSnapshot(
        universe_id="univ_test",
        user_id="user_test",
        symbols=["000001.SZ", "600000.SH", "000002.SZ"]
    )

    version = StrategyVersion(
        version_id="v_1",
        strategy_id="strat_1",
        version_num=1,
        is_published=True,
        parameters={"weights": {"ret_1d": 1.0}},
        rules={
            "conditions": {"op": ">", "factor_id": "ret_1d", "value": 0.01},
            "top_k": 2
        },
        universe=univ
    )

    df = pd.DataFrame({
        "ret_1d": [0.02, 0.05, -0.01]
    }, index=["000001.SZ", "600000.SH", "000002.SZ"])

    as_of = now_tz()
    signals = engine.generate_signals(version, "user_test", as_of, df)

    assert len(signals) == 3

    # Check top_k buy signals
    buy_signals = [s for s in signals if s.signal_type == "buy"]
    assert len(buy_signals) == 2

    # Verify reason codes
    s000002 = next(s for s in signals if s.symbol == "000002.SZ")
    assert s000002.signal_type == "hold"
    assert s000002.reason_code == "CONDITION_FAILED"

    # Deterministic sorting check
    # 600000.SH has highest return (0.05) -> rank 1
    # 000001.SZ has second highest return (0.02) -> rank 2
    s600000 = next(s for s in signals if s.symbol == "600000.SH")
    assert s600000.rank == 1
    assert s600000.reason_code == "OK"


def test_signal_engine_tie_breaking():
    engine = DeterministicSignalEngine()

    univ = UniverseSnapshot(
        universe_id="univ_test",
        user_id="user_test",
        symbols=["BBB.SH", "AAA.SH"]
    )

    version = StrategyVersion(
        version_id="v_1",
        strategy_id="strat_1",
        version_num=1,
        is_published=True,
        parameters={"weights": {"ret_1d": 1.0}},
        rules={"top_k": 1},
        universe=univ
    )

    # Identical factor values -> tie breaking by symbol ASC
    df = pd.DataFrame({
        "ret_1d": [0.02, 0.02]
    }, index=["BBB.SH", "AAA.SH"])

    signals = engine.generate_signals(version, "user_test", now_tz(), df)

    s_aaa = next(s for s in signals if s.symbol == "AAA.SH")
    s_bbb = next(s for s in signals if s.symbol == "BBB.SH")

    assert s_aaa.rank == 1
    assert s_aaa.signal_type == "buy"
    assert s_bbb.rank == 2
    assert s_bbb.reason_code == "RANK_CUTOFF"
