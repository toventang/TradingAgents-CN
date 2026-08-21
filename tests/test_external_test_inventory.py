from pathlib import Path

from tests.external_test_inventory import EXTERNAL_TESTS, classify_test_path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_every_external_inventory_path_exists():
    missing = [path for path in EXTERNAL_TESTS if not (REPOSITORY_ROOT / path).is_file()]
    assert missing == []


def test_integration_directory_is_classified():
    assert classify_test_path("tests/integration/test_dashscope_integration.py") == "integration"


def test_fast_gate_paths_are_not_classified_external():
    fast_paths = (
        "tests/test_external_test_inventory.py",
        "tests/test_jules_validation_contract.py",
        "tests/unit/tools/analysis/test_indicators_uil.py",
    )
    assert [path for path in fast_paths if classify_test_path(path)] == []
