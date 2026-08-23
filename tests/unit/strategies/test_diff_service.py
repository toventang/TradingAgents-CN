import pytest
from app.models.strategy import StrategyVersion, UniverseSnapshot
from app.services.strategies.diff_service import StrategyDiffService


def test_strategy_diff_service():
    diff_service = StrategyDiffService()

    univ1 = UniverseSnapshot(universe_id="u1", user_id="u1", symbols=["000001.SZ", "600000.SH"])
    univ2 = UniverseSnapshot(universe_id="u2", user_id="u1", symbols=["600000.SH", "000002.SZ"])

    v1 = StrategyVersion(
        version_id="v1",
        strategy_id="strat_diff",
        version_num=1,
        parameters={"weights": {"ret_1d": 0.5}},
        rules={"top_k": 5},
        universe=univ1
    )

    v2 = StrategyVersion(
        version_id="v2",
        strategy_id="strat_diff",
        version_num=2,
        parameters={"weights": {"ret_1d": 0.8, "ret_5d": 0.2}},
        rules={"top_k": 10},
        universe=univ2
    )

    diff = diff_service.diff_versions(v1, v2)

    assert diff["v1_num"] == 1
    assert diff["v2_num"] == 2
    assert "ret_5d" in diff["parameter_diffs"]["added"]
    assert "000002.SZ" in diff["universe_diffs"]["added_symbols"]
    assert "000001.SZ" in diff["universe_diffs"]["removed_symbols"]
