"""Builds page objects from config, so tests never handle URLs, timeouts or drivers.

This is the seam between the config layer and page objects: page objects take
plain values, and this factory supplies them from :class:`~harness.config.Settings`.
"""

from __future__ import annotations

from harness.config import Settings
from harness.driver import Driver
from harness.pages.auth.login_page import LoginPage
from harness.pages.base_page import BasePage


class PageFactory:
    """Construct page objects bound to one browser session."""

    def __init__(self, driver: Driver, settings: Settings) -> None:
        self._driver = driver
        self._settings = settings

    @property
    def timeout(self) -> float:
        """Default element timeout passed to every page object."""
        return self._settings.timeouts.element

    def login(self, start_app: str | None = None) -> LoginPage:
        """Open app ``start_app`` (default ``idp.entry_app``) and return the IdP login page."""
        app = self._settings.app(start_app or self._settings.idp.entry_app)
        page = LoginPage(self._driver, str(self._settings.idp.base_url), self.timeout)
        return page.open_via(str(app.base_url))

    def app[P: BasePage](self, app_name: str, page_cls: type[P]) -> P:
        """Return an (unopened) ``page_cls`` for app ``app_name``; call ``.open()`` to navigate."""
        return page_cls(self._driver, str(self._settings.app(app_name).base_url), self.timeout)
