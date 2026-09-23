"""Top navigation bar shared by the web apps.

Locators are placeholders assuming ``data-testid`` hooks; adjust to the real markup.
"""

from __future__ import annotations

from harness.pages.components.base import Component
from harness.waits import by_test_id, xpath


class NavBar(Component):
    """Site navigation plus the signed-in user menu."""

    default_root = by_test_id("nav-bar")
    USER_NAME = by_test_id("nav-user-name")
    SIGN_OUT = by_test_id("nav-sign-out")

    def signed_in_username(self) -> str:
        """Return the username shown in the nav bar."""
        return self.within().text_of(self.USER_NAME)

    def go_to(self, label: str) -> None:
        """Click the navigation link whose visible text is exactly ``label``."""
        self.within().click(xpath(f".//a[normalize-space()={_xpath_literal(label)}]"))

    def sign_out(self) -> None:
        """Click the sign-out control."""
        self.within().click(self.SIGN_OUT)


def _xpath_literal(text: str) -> str:
    """Quote ``text`` as an XPath 1.0 string literal, handling embedded quotes."""
    if "'" not in text:
        return f"'{text}'"
    if '"' not in text:
        return f'"{text}"'
    parts = text.split("'")
    return "concat(" + ', "\'", '.join(f"'{p}'" for p in parts) + ")"
