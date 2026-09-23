"""Offline checks of the driver options, locators and health-check plumbing."""

import json

import httpx
import pytest

from harness.config import BrowserConfig
from harness.driver import AIRGAP_FIREFOX_PREFS, build_options
from harness.health import (
    CheckResult,
    HealthReport,
    check_grid_slots,
    check_vyos,
    grid_reachable,
)
from harness.waits import by_test_id, css

pytestmark = pytest.mark.unit


def _browser(**overrides: object) -> BrowserConfig:
    base: dict[str, object] = {
        "name": "firefox",
        "version": "128.0",
        "headless": True,
        "capture_console": True,
        "accept_insecure_certs": False,
    }
    return BrowserConfig.model_validate(base | overrides)


def test_options_tag_session_and_lock_down_firefox() -> None:
    """Capabilities carry the test name, version, BiDi flag and air-gap prefs."""
    caps = build_options(_browser(), "tests/x.py::test_y").to_capabilities()

    assert caps["browserName"] == "firefox"
    assert caps["browserVersion"] == "128.0"
    assert caps["platformName"] == "linux"
    assert caps["se:name"] == "tests/x.py::test_y"
    assert caps["webSocketUrl"] is True
    prefs = caps["moz:firefoxOptions"]["prefs"]
    assert all(prefs[k] == v for k, v in AIRGAP_FIREFOX_PREFS.items())


def test_empty_version_means_any_version() -> None:
    """An empty version string leaves browserVersion unset."""
    caps = build_options(_browser(version="", capture_console=False), "t").to_capabilities()
    assert "browserVersion" not in caps
    assert "webSocketUrl" not in caps


def test_locator_helpers() -> None:
    """by_test_id builds a data-testid CSS locator; str() is readable."""
    assert by_test_id("nav") == css('[data-testid="nav"]')
    assert str(css("a.b")) == "css selector='a.b'"


def _client(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=handler)


def test_unreachable_hub_is_distinguished_from_broken_hub() -> None:
    """Connection errors mean 'unreachable'; any HTTP answer means 'reachable'."""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    assert not grid_reachable(_client(httpx.MockTransport(refuse)), "http://hub:4444")
    broken = httpx.MockTransport(lambda _r: httpx.Response(500))
    assert grid_reachable(_client(broken), "http://hub:4444")


def test_grid_slot_check_counts_up_nodes_only() -> None:
    """Slots on DOWN nodes do not count towards the expectation."""
    status = {
        "value": {
            "ready": True,
            "nodes": [
                {"availability": "UP", "slots": [{"stereotype": {"browserName": "firefox"}}] * 2},
                {"availability": "DOWN", "slots": [{"stereotype": {"browserName": "firefox"}}]},
            ],
        }
    }
    client = _client(httpx.MockTransport(lambda _r: httpx.Response(200, json=status)))

    assert check_grid_slots(client, "http://hub:4444", {"firefox": 2}).ok
    short = check_grid_slots(client, "http://hub:4444", {"firefox": 3})
    assert not short.ok
    assert "have 2, need 3" in short.detail


def test_vyos_check_posts_key_and_reads_success() -> None:
    """The VyOS check sends a read-only showConfig with the API key."""
    seen: dict[str, str] = {}

    def api(request: httpx.Request) -> httpx.Response:
        form = dict(httpx.QueryParams(request.content.decode()))
        seen.update(form)
        return httpx.Response(200, json={"success": True, "data": "vyos-kit", "error": None})

    result = check_vyos(_client(httpx.MockTransport(api)), "https://vyos", "k3y")

    assert result.ok
    assert seen["key"] == "k3y"
    assert json.loads(seen["data"])["op"] == "showConfig"


def test_report_summary_lists_failures() -> None:
    """The summary says NOT READY and shows each failing check."""
    report = HealthReport(
        (
            CheckResult("grid", "http://hub", True, "ready"),
            CheckResult("app:app_one", "https://a/healthz", False, "HTTP 503"),
        )
    )
    assert not report.ok
    assert "NOT READY (1 failing)" in report.summary()
    assert "[FAIL] app:app_one" in report.summary()
