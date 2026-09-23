"""app_one landing page. Locators are placeholders; adjust to the real markup."""

from __future__ import annotations

from harness.pages.app_one.records_page import RecordsPage
from harness.pages.base_page import BasePage
from harness.pages.components import NavBar
from harness.waits import by_test_id


class HomePage(BasePage):
    """The page a signed-in user lands on."""

    path = "/"
    ready_locator = by_test_id("app-one-home")

    @property
    def nav(self) -> NavBar:
        """The shared navigation bar."""
        return NavBar(self.driver, self.timeout)

    def signed_in_username(self) -> str:
        """Return the username shown as signed in."""
        return self.nav.signed_in_username()

    def go_to_records(self) -> RecordsPage:
        """Open the Records page through the navigation bar."""
        self.nav.go_to("Records")
        return self.page(RecordsPage).wait_until_ready()
