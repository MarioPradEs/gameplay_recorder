import os

import pytest


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "gui: GUI tests requiring a display")
    config.addinivalue_line("markers", "e2e: End-to-end tests requiring a real Android device")


def pytest_collection_modifyitems(config, items):
    """Skip E2E tests unless GAMEPLAY_RECORDER_E2E env var is set."""
    if os.getenv("GAMEPLAY_RECORDER_E2E"):
        return
    skip_e2e = pytest.mark.skip(reason="Set GAMEPLAY_RECORDER_E2E=1 to run E2E tests")
    for item in items:
        if "e2e" in item.keywords:
            item.add_marker(skip_e2e)
