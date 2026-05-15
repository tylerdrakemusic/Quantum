"""⟨ψ⟩Quantum test configuration."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def pytest_collection_modifyitems(config, items):
    """Skip playwright-marked tests unless PLAYWRIGHT_ENABLED=1 is set."""
    if os.getenv("PLAYWRIGHT_ENABLED") != "1":
        skip = pytest.mark.skip(reason="Set PLAYWRIGHT_ENABLED=1 to run Playwright tests")
        for item in items:
            if item.get_closest_marker("playwright"):
                item.add_marker(skip)
