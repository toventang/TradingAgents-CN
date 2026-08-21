import os
import sys

import pytest

# 将项目根目录加入 sys.path，确保 `import tradingagents` 可用
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from tests.external_test_inventory import classify_test_path


def pytest_ignore_collect(collection_path, config):
    """Avoid importing known live/manual modules during the default test run."""
    relative_path = os.path.relpath(str(collection_path), PROJECT_ROOT).replace(os.sep, "/")
    classification = classify_test_path(relative_path)
    if not classification:
        return None

    marker_expression = config.getoption("markexpr") or ""
    explicitly_requested = (
        classification in marker_expression
        and f"not {classification}" not in marker_expression
    )
    return not explicitly_requested


def pytest_collection_modifyitems(items):
    """Apply centrally audited markers without changing historical assertions."""
    for item in items:
        relative_path = os.path.relpath(str(item.path), PROJECT_ROOT).replace(os.sep, "/")
        classification = classify_test_path(relative_path)
        if classification:
            item.add_marker(getattr(pytest.mark, classification))
