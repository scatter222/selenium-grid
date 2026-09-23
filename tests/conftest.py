"""Shared fixtures: settings, kit readiness gate, Grid driver, authenticated session.

Kit-dependent tests skip with a clear reason when no Grid hub is reachable, so the
scaffold can be verified offline. CI passes ``--require-kit`` to turn that skip
into a failure.
"""

from __future__ import annotations

from collections.abc import Generator, Iterator
from dataclasses import dataclass
from pathlib import Path

import allure
import pytest

from harness.auth import (
    AuthedSession,
    Credentials,
    SessionState,
    capture_session,
    credentials_for,
    inject_session,
    session_landing_paths,
    ui_login,
)
from harness.config import RunOptions, Settings, load_settings
from harness.driver import (
    ConsoleCollector,
    Driver,
    capture_failure_artifacts,
    create_driver,
    quit_quietly,
)
from harness.errors import HarnessError
from harness.health import HealthReport, grid_reachable, make_client, run_checks
from harness.page_factory import PageFactory

# --- settings & readiness -------------------------------------------------------------


@pytest.fixture(scope="session")
def run_options(pytestconfig: pytest.Config) -> RunOptions:
    """Run-level switches: ``HARNESS_*`` env vars, overridden by command-line flags."""
    options = RunOptions()
    env_flag: str | None = pytestconfig.getoption("harness_env")
    updates: dict[str, object] = {}
    if env_flag:
        updates["env_file"] = Path(env_flag)
    if pytestconfig.getoption("harness_require_kit"):
        updates["require_kit"] = True
    return options.model_copy(update=updates)


@pytest.fixture(scope="session")
def settings(run_options: RunOptions) -> Settings:
    """Validated settings from the environment file chosen by ``--env``."""
    try:
        return load_settings(run_options.env_file)
    except HarnessError as exc:
        pytest.fail(str(exc), pytrace=False)


@pytest.fixture(scope="session", autouse=True)
def environment_ready(settings: Settings, run_options: RunOptions) -> HealthReport:
    """Gate every kit test on the kit being up; fail fast with a readable summary.

    Order: Grid reachable? -> all secrets present? -> every readiness check passes?
    An unreachable hub skips (or fails, with ``--require-kit``); anything else fails.
    ``tests/unit`` overrides this fixture because unit tests need no kit.
    """
    hub = str(settings.grid.hub_url)
    try:
        with make_client(settings) as client:
            reachable = grid_reachable(client, hub)
    except HarnessError as exc:
        pytest.fail(str(exc), pytrace=False)
    if not reachable:
        reason = (
            f"No Selenium Grid hub reachable at {hub} "
            f"(env file: {run_options.env_file}, kit: {settings.name})."
        )
        if run_options.require_kit:
            pytest.fail(f"{reason} --require-kit is set, so this is a failure.", pytrace=False)
        pytest.skip(f"{reason} Pass --require-kit to fail instead of skipping.")
    try:
        settings.check_secrets()
    except HarnessError as exc:
        pytest.fail(str(exc), pytrace=False)
    report = run_checks(settings)
    if not report.ok:
        pytest.fail(
            "Environment is not ready; no browser tests were attempted.\n" + report.summary(),
            pytrace=False,
        )
    return report


# --- browser ------------------------------------------------------------------------

_BROWSER = pytest.StashKey["BrowserHandle"]()


@dataclass(frozen=True)
class BrowserHandle:
    """What the failure hook needs to collect diagnostics for a test's browser."""

    driver: Driver
    console: ConsoleCollector


@pytest.fixture
def driver(request: pytest.FixtureRequest, settings: Settings) -> Iterator[Driver]:
    """A fresh Remote WebDriver on the Grid, named after the test; always quit."""
    try:
        drv = create_driver(settings, session_name=request.node.nodeid)
    except HarnessError as exc:
        pytest.fail(str(exc), pytrace=False)
    console = ConsoleCollector()
    console.attach(drv, enabled=settings.browser.capture_console)
    request.node.stash[_BROWSER] = BrowserHandle(drv, console)
    try:
        yield drv
    finally:
        quit_quietly(drv)


@pytest.fixture
def pages(driver: Driver, settings: Settings) -> PageFactory:
    """Page-object factory for an *unauthenticated* browser."""
    return PageFactory(driver, settings)


# --- authentication -----------------------------------------------------------------


@pytest.fixture(scope="session")
def default_credentials(settings: Settings) -> Credentials:
    """Resolved credentials for ``settings.default_user``."""
    try:
        return credentials_for(settings, settings.default_user)
    except HarnessError as exc:
        pytest.fail(str(exc), pytrace=False)


@pytest.fixture(scope="session")
def login_state(settings: Settings, default_credentials: Credentials) -> SessionState:
    """Log in through the UI once per session (per xdist worker) and capture cookies."""
    drv = create_driver(settings, session_name="authed_session: one-off UI login")
    try:
        login_page = PageFactory(drv, settings).login()
        entry = str(settings.app(settings.idp.entry_app).base_url)
        ui_login(login_page, entry, default_credentials)
        return capture_session(drv, default_credentials.username, session_landing_paths(settings))
    finally:
        quit_quietly(drv)


@pytest.fixture
def authed_session(
    request: pytest.FixtureRequest,
    driver: Driver,
    settings: Settings,
    login_state: SessionState,
) -> AuthedSession:
    """A fresh browser seeded with the session's login cookies (no UI login per test)."""
    inject_session(driver, login_state)
    request.node.stash[_BROWSER].console.clear()  # keep only the test's own console output
    return AuthedSession(driver, login_state.username, PageFactory(driver, settings))


# --- failure diagnostics ------------------------------------------------------------


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    """On failure, attach screenshot, page URL and browser console log to Allure."""
    report = yield
    handle = item.stash.get(_BROWSER, None)
    if handle is None or not report.failed or report.when == "teardown":
        return report
    artifacts = capture_failure_artifacts(handle.driver)
    if artifacts.screenshot_png is not None:
        allure.attach(
            artifacts.screenshot_png, name="screenshot", attachment_type=allure.attachment_type.PNG
        )
    allure.attach(
        f"{artifacts.url}\n{artifacts.title}",
        name="page url",
        attachment_type=allure.attachment_type.TEXT,
    )
    allure.attach(
        handle.console.render(),
        name="browser console",
        attachment_type=allure.attachment_type.TEXT,
    )
    item.user_properties.append(("failure_url", artifacts.url))
    return report
