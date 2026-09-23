"""Real UI login through the IdP: one positive and one negative case."""

import pytest

from harness.auth import Credentials
from harness.page_factory import PageFactory
from harness.pages.app_one import HomePage

pytestmark = [pytest.mark.smoke, pytest.mark.app_one]


def test_valid_user_lands_on_app_signed_in(
    pages: PageFactory, default_credentials: Credentials
) -> None:
    """Username, password and TOTP get the user back to app_one, signed in as themselves."""
    login = pages.login(start_app="app_one")

    login.log_in(
        default_credentials.username,
        default_credentials.password,
        default_credentials.otp_provider,
    )
    home = pages.app("app_one", HomePage).wait_until_ready()

    assert home.signed_in_username() == default_credentials.username


def test_unknown_user_is_rejected(pages: PageFactory) -> None:
    """An unknown username stays on the login form with an error.

    Deliberately not a real user with a wrong password: that would count
    towards the IdP's brute-force lockout for a shared test account.
    """
    login = pages.login(start_app="app_one")

    login.log_in("harness-no-such-user", "not-a-real-password")

    assert "invalid" in login.error_message().lower()
    assert login.is_displayed()
