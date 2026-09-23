"""Keycloak-style IdP login page.

Flow: an app redirects to the IdP; this page takes username and password; if the
user has MFA a second page takes the TOTP code; then the IdP redirects back.

Locators match Keycloak's stock login theme (``#username``, ``#kc-login``...).
If the realm uses a custom theme, update them here -- nowhere else.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Self

from harness.errors import HarnessError
from harness.pages.base_page import BasePage
from harness.waits import by_id, css


class LoginRejectedError(HarnessError):
    """The IdP showed an error instead of the expected next step."""


class LoginPage(BasePage):
    """The IdP username/password form and its OTP follow-up."""

    ready_locator = by_id("kc-form-login")
    USERNAME = by_id("username")
    PASSWORD = by_id("password")
    SUBMIT = by_id("kc-login")
    OTP_INPUT = by_id("otp")
    ERROR = css("#input-error, #input-error-otp-code, .kc-feedback-text, .alert-error")

    def open_via(self, start_url: str) -> Self:
        """Navigate to ``start_url`` (an app page) and wait to be redirected to the login form."""
        self.driver.get(start_url)
        return self.wait_until_ready()

    def log_in(self, username: str, password: str, otp: Callable[[], str] | None = None) -> None:
        """Submit credentials and, if ``otp`` is given, the one-time code.

        ``otp`` is called only once the OTP field is on screen, so the code is as
        fresh as possible. This method does not wait for the post-login redirect;
        wait on the destination page (or :meth:`wait_until_left`) instead.
        Raises :class:`LoginRejectedError` if the IdP shows an error instead of the OTP form.
        """
        self.wait.type_text(self.USERNAME, username)
        self.wait.type_text(self.PASSWORD, password)
        self.wait.click(self.SUBMIT)
        if otp is None:
            return
        if self.wait.first_visible(self.OTP_INPUT, self.ERROR) == self.ERROR:
            raise LoginRejectedError(f"IdP rejected credentials: {self.error_message()}")
        self.wait.type_text(self.OTP_INPUT, otp())
        self.wait.click(self.SUBMIT)

    def error_message(self) -> str:
        """Wait for and return the IdP's error text (e.g. "Invalid username or password.")."""
        return self.wait.text_of(self.ERROR)

    def wait_until_left(self) -> None:
        """Wait for the browser to be redirected away from the IdP."""
        self.wait.url_leaves(self.base_url)
