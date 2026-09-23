"""Remote WebDriver factory for the Selenium Grid.

The harness never starts a local browser: every session is created on the Grid
hub named in the config, which schedules it onto a node built from the laptop
image (workstation network). Browser traffic then reaches the apps through the
firewall and VyOS, exactly as a user's would.

Air-gap notes:

* ``SE_OFFLINE=true`` is set so Selenium Manager never tries to download a driver
  or browser. (Remote sessions do not invoke it anyway; this guards against misuse.)
* Firefox preferences below switch off every background call home: updates,
  safe-browsing lists, telemetry, captive-portal and connectivity probes, OCSP.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final

from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.proxy import Proxy, ProxyType
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.remote.client_config import ClientConfig
from selenium.webdriver.remote.webdriver import WebDriver

from harness.config import BrowserConfig, Settings
from harness.errors import DriverStartError

Driver = WebDriver
"""The driver type handed to page objects and fixtures."""

Cookie = dict[str, object]
"""A cookie as returned by ``get_cookies`` and accepted by ``add_cookie``."""

AIRGAP_FIREFOX_PREFS: Final[Mapping[str, bool | int | str]] = {
    "app.update.auto": False,
    "app.update.checkInstallTime": False,
    "browser.safebrowsing.malware.enabled": False,
    "browser.safebrowsing.phishing.enabled": False,
    "browser.safebrowsing.downloads.enabled": False,
    "browser.safebrowsing.downloads.remote.enabled": False,
    "browser.region.network.url": "",
    "browser.region.update.enabled": False,
    "network.captive-portal-service.enabled": False,
    "network.connectivity-service.enabled": False,
    "network.dns.disablePrefetch": True,
    "network.prefetch-next": False,
    "datareporting.healthreport.uploadEnabled": False,
    "datareporting.policy.dataSubmissionEnabled": False,
    "toolkit.telemetry.enabled": False,
    "toolkit.telemetry.unified": False,
    "extensions.update.enabled": False,
    "extensions.getAddons.cache.enabled": False,
    "security.OCSP.enabled": 0,
}


def disable_selenium_manager() -> None:
    """Stop Selenium Manager from downloading drivers or browsers (air-gapped kits)."""
    os.environ["SE_OFFLINE"] = "true"


def build_options(browser: BrowserConfig, session_name: str) -> FirefoxOptions:
    """Build Firefox capabilities for a Grid session.

    ``session_name`` becomes the ``se:name`` capability, which the Grid UI shows
    against the running session so a test can be matched to its browser.
    """
    options = FirefoxOptions()
    if browser.version:
        options.browser_version = browser.version
    options.platform_name = browser.platform
    options.accept_insecure_certs = browser.accept_insecure_certs
    options.page_load_strategy = "normal"
    if browser.headless:
        options.add_argument("-headless")
    if browser.capture_console:
        options.enable_bidi = True
    for name, value in AIRGAP_FIREFOX_PREFS.items():
        options.set_preference(name, value)
    options.set_capability("se:name", session_name)
    return options


def hub_address(settings: Settings) -> str:
    """Hub URL without a trailing slash (pydantic adds one; selenium would send ``//session``)."""
    return str(settings.grid.hub_url).rstrip("/")


def build_client_config(settings: Settings) -> ClientConfig:
    """Build the HTTP client config used to talk to the hub (timeouts, TLS, proxy)."""
    proxy = None if settings.network.use_env_proxy else Proxy({"proxyType": ProxyType.DIRECT})
    ca_bundle = settings.tls.ca_bundle
    return ClientConfig(
        remote_server_addr=hub_address(settings),
        timeout=settings.timeouts.grid_command,
        proxy=proxy,
        ignore_certificates=not settings.tls.verify,
        ca_certs=str(ca_bundle) if ca_bundle else None,
    )


def create_driver(settings: Settings, session_name: str) -> WebDriver:
    """Create a Remote WebDriver session on the Grid hub.

    Implicit waits are forced to zero: all waiting is explicit, via :mod:`harness.waits`.
    Raises :class:`DriverStartError` if the hub refuses or fails to create the session.
    """
    disable_selenium_manager()
    hub = hub_address(settings)
    try:
        driver = webdriver.Remote(
            command_executor=hub,
            options=build_options(settings.browser, session_name),
            client_config=build_client_config(settings),
        )
    except WebDriverException as exc:
        raise DriverStartError(
            f"Grid at {hub} could not start a {settings.browser.name} "
            f"{settings.browser.version or '(any version)'} session: {exc.msg}"
        ) from exc
    driver.implicitly_wait(0)
    driver.set_page_load_timeout(settings.timeouts.page_load)
    return driver


def quit_quietly(driver: WebDriver) -> None:
    """Quit ``driver``, ignoring errors from an already-dead session (always frees the slot)."""
    with contextlib.suppress(WebDriverException):
        driver.quit()


@dataclass
class ConsoleCollector:
    """Collect browser console messages and JS errors over WebDriver BiDi.

    Firefox does not implement ``driver.get_log('browser')``, so BiDi's
    ``log.entryAdded`` events are the only option. If the Grid or node does not
    support BiDi, :attr:`unavailable_reason` explains why and capture is skipped.
    """

    entries: list[str] = field(default_factory=list)
    unavailable_reason: str | None = None

    def attach(self, driver: WebDriver, *, enabled: bool) -> None:
        """Start collecting from ``driver``. Never raises; records why capture is off."""
        if not enabled:
            self.unavailable_reason = "console capture disabled (browser.capture_console=false)"
            return
        try:
            driver.script.add_console_message_handler(self._on_console)
            driver.script.add_javascript_error_handler(self._on_js_error)
        except Exception as exc:  # noqa: BLE001 - BiDi support varies by Grid/node version
            self.unavailable_reason = f"WebDriver BiDi unavailable on this session: {exc}"

    def _on_console(self, entry: object) -> None:
        level = getattr(entry, "level", "?")
        self.entries.append(f"[console.{level}] {getattr(entry, 'text', entry)}")

    def _on_js_error(self, entry: object) -> None:
        self.entries.append(f"[js-error] {getattr(entry, 'text', entry)}")

    def clear(self) -> None:
        """Drop everything collected so far (e.g. noise from session set-up)."""
        self.entries.clear()

    def render(self) -> str:
        """Return the collected log as text, or the reason nothing was collected."""
        if self.unavailable_reason:
            return self.unavailable_reason
        return "\n".join(self.entries) or "(no console output)"


@dataclass(frozen=True)
class FailureArtifacts:
    """Diagnostics captured from a browser when a test fails."""

    url: str
    title: str
    screenshot_png: bytes | None


def capture_failure_artifacts(driver: WebDriver) -> FailureArtifacts:
    """Grab URL, title and a screenshot, tolerating a crashed or closed session."""
    try:
        url = driver.current_url
        title = driver.title
    except WebDriverException as exc:
        return FailureArtifacts(url=f"<unavailable: {exc.msg}>", title="", screenshot_png=None)
    try:
        png: bytes | None = driver.get_screenshot_as_png()
    except WebDriverException:
        png = None
    return FailureArtifacts(url=url, title=title, screenshot_png=png)
