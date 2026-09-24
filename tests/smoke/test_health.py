"""Every web app answers its health endpoint from the runner."""

import pytest

from harness.config import Settings
from harness.health import check_apps, make_client

pytestmark = pytest.mark.smoke


def test_every_app_responds(settings: Settings) -> None:
    """Each configured app returns 2xx/3xx on its health path."""
    if not settings.checks.apps:
        pytest.skip("checks.apps is false: the runner can't reach the apps directly")
    with make_client(settings) as client:
        results = check_apps(client, settings.apps)

    assert results, "no apps are configured in the environment file"
    failures = [f"{r.name} {r.target}: {r.detail}" for r in results if not r.ok]
    assert not failures, "apps not responding:\n" + "\n".join(failures)
