"""Unit tests exercise the harness itself and need neither the kit nor a Grid."""

import pytest


@pytest.fixture(scope="session", autouse=True)
def environment_ready() -> None:
    """Override the root kit gate: nothing to check for offline tests."""
    return
