"""pytest plugin registering the harness command-line options.

Loaded through the ``pytest11`` entry point rather than ``tests/conftest.py``, so
``--env env/virtual.yaml`` (space-separated) parses correctly: pytest reads the
command line before it discovers conftest files, and would otherwise mistake the
YAML path for a test path.
"""

from __future__ import annotations

import pytest

from harness.driver import disable_selenium_manager


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register ``--env`` and ``--require-kit``."""
    group = parser.getgroup("harness")
    group.addoption(
        "--env",
        dest="harness_env",
        default=None,
        metavar="PATH",
        help="Environment YAML, e.g. env/virtual.yaml (default: $HARNESS_ENV_FILE "
        "or env/virtual.yaml).",
    )
    group.addoption(
        "--require-kit",
        dest="harness_require_kit",
        action="store_true",
        default=False,
        help="Fail, rather than skip, kit tests when the Grid hub is unreachable "
        "(also: HARNESS_REQUIRE_KIT=1). Always set in CI.",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Make sure Selenium Manager never tries to download anything."""
    disable_selenium_manager()
