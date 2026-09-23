"""Base class for every page object.

Page objects receive everything they need (driver, base URL, timeout) through the
constructor. They never read environment variables or config files, and they never
import selenium: locators come from :mod:`harness.waits` helpers and every
interaction goes through a :class:`~harness.waits.Waiter`.
"""

from __future__ import annotations

from typing import ClassVar, Self

from harness.driver import Driver
from harness.errors import PageNotReadyError, WaitTimeoutError
from harness.waits import Locator, Waiter


class BasePage:
    """Navigation, readiness, and wait-wrapped interactions shared by all pages.

    Subclasses set :attr:`path` (relative to ``base_url``) and :attr:`ready_locator`,
    an element whose visibility means the page has finished rendering.
    """

    path: ClassVar[str] = "/"
    ready_locator: ClassVar[Locator]

    def __init__(self, driver: Driver, base_url: str, timeout: float) -> None:
        self.driver = driver
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.wait = Waiter(driver, timeout)

    @property
    def url(self) -> str:
        """Absolute URL of this page."""
        return f"{self.base_url}{self.path}"

    @property
    def current_url(self) -> str:
        """URL the browser is currently showing."""
        return self.driver.current_url

    @property
    def title(self) -> str:
        """Document title of the current page."""
        return self.driver.title

    def open(self) -> Self:
        """Navigate directly to this page and wait until it is ready."""
        self.driver.get(self.url)
        return self.wait_until_ready()

    def wait_until_ready(self) -> Self:
        """Wait for the document to load and :attr:`ready_locator` to be visible."""
        try:
            self.wait.document_ready()
            self.wait.visible(self.ready_locator)
        except WaitTimeoutError as exc:
            raise PageNotReadyError(
                f"{type(self).__name__} did not become ready within {self.timeout:g}s "
                f"(waiting for {self.ready_locator}); browser is at {self._safe_url()}"
            ) from exc
        return self

    def is_displayed(self, timeout: float = 0.0) -> bool:
        """Return whether this page's ready marker is visible (optionally waiting ``timeout``)."""
        return self.wait.is_visible(self.ready_locator, timeout)

    def page[P: BasePage](self, page_cls: type[P]) -> P:
        """Construct another page object of this app sharing driver, base URL and timeout."""
        return page_cls(self.driver, self.base_url, self.timeout)

    def _safe_url(self) -> str:
        try:
            return self.driver.current_url
        except Exception:  # noqa: BLE001 - diagnostics only
            return "<unavailable>"
