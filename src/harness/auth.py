"""Authentication helpers: TOTP, UI login, and session capture/injection.

Logging in through the IdP UI for every test is slow, so the harness logs in once
per test session (:func:`ui_login` + :func:`capture_session`) and then seeds each
fresh browser with the captured cookies (:func:`inject_session`). The IdP's SSO
cookies are captured as well as each app's, so any app visited afterwards
completes OIDC silently even if its own cookie has expired.

TOTP caveat: an IdP that refuses to accept the same OTP twice in one 30-second
window (Keycloak "Reusable token: off") will reject a second login by the same
user inside that window -- e.g. two xdist workers starting together. Enable
reusable tokens in the test realm, or give each worker its own user.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import pyotp

from harness.config import Settings, resolve_secret
from harness.driver import Cookie, Driver
from harness.page_factory import PageFactory
from harness.pages.auth.login_page import LoginPage

_COOKIE_KEYS = ("name", "value", "path", "domain", "secure", "httpOnly", "expiry", "sameSite")


@dataclass(frozen=True)
class Credentials:
    """A test user's resolved credentials. Secrets are hidden from ``repr``."""

    username: str
    role: str
    password: str = field(repr=False)
    totp_seed: str | None = field(default=None, repr=False)

    def otp(self) -> str:
        """Return the current TOTP code; raise ``ValueError`` if the user has no MFA seed."""
        if self.totp_seed is None:
            raise ValueError(f"User {self.username!r} has no TOTP seed configured")
        return totp_code(self.totp_seed)

    @property
    def otp_provider(self) -> Callable[[], str] | None:
        """A callable yielding a fresh code, or ``None`` for users without MFA."""
        return self.otp if self.totp_seed is not None else None


def totp_code(seed: str) -> str:
    """Return the current 6-digit TOTP code for base32 ``seed``."""
    return pyotp.TOTP(seed).now()


def credentials_for(
    settings: Settings, user_key: str, environ: Mapping[str, str] | None = None
) -> Credentials:
    """Resolve user ``user_key``'s secrets from the environment into :class:`Credentials`."""
    user = settings.user(user_key)
    seed = resolve_secret(user.totp_seed_env, environ) if user.totp_seed_env else None
    return Credentials(
        username=user.username,
        role=user.role,
        password=resolve_secret(user.password_env, environ),
        totp_seed=seed,
    )


def origin_of(url: str) -> str:
    """Return ``scheme://host[:port]`` for ``url``."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def ui_login(login_page: LoginPage, start_url: str, credentials: Credentials) -> None:
    """Log in through the IdP UI starting from app URL ``start_url``.

    Returns once the browser has been redirected back off the IdP.
    """
    login_page.open_via(start_url)
    login_page.log_in(credentials.username, credentials.password, credentials.otp_provider)
    login_page.wait_until_left()


@dataclass(frozen=True)
class OriginCookies:
    """Cookies captured for one origin, plus the path used to land there before injecting."""

    landing_path: str
    cookies: tuple[Cookie, ...]


@dataclass(frozen=True)
class SessionState:
    """A logged-in browser session, reduced to cookies per origin."""

    username: str
    origins: dict[str, OriginCookies]


def capture_session(
    driver: Driver, username: str, landing_paths: Mapping[str, str]
) -> SessionState:
    """Visit each origin in ``landing_paths`` ({origin: path}) and record its cookies.

    WebDriver only exposes cookies whose domain *and path* match the current
    document, hence the visits -- and why the IdP's landing path must sit under
    the realm path its session cookies are scoped to (``/realms/<realm>/``).
    """
    origins: dict[str, OriginCookies] = {}
    for origin, landing_path in landing_paths.items():
        driver.get(origin + landing_path)
        cookies = tuple(_clean(c) for c in driver.get_cookies())
        origins[origin] = OriginCookies(landing_path=landing_path, cookies=cookies)
    return SessionState(username=username, origins=origins)


def inject_session(driver: Driver, state: SessionState) -> None:
    """Seed a fresh browser with ``state``'s cookies, one origin at a time.

    Each origin's ``landing_path`` must load without redirecting off-origin (a static
    asset or 404 page is ideal), because WebDriver can only set cookies for the
    domain currently loaded.
    """
    for origin, captured in state.origins.items():
        driver.get(origin + captured.landing_path)
        for cookie in captured.cookies:
            driver.add_cookie(dict(cookie))


def session_landing_paths(settings: Settings) -> dict[str, str]:
    """Return ``{origin: landing_path}`` for the IdP and every configured app."""
    paths = {origin_of(str(settings.idp.base_url)): settings.idp.cookie_landing_path}
    for app in settings.apps.values():
        paths[origin_of(str(app.base_url))] = app.cookie_landing_path
    return paths


def _clean(cookie: Mapping[str, object]) -> Cookie:
    """Keep only the fields ``add_cookie`` accepts, in a form the browser will take back.

    Firefox reports ``sameSite: "None"`` for cookies that never set the attribute,
    then rejects re-adding them because ``SameSite=None`` requires ``Secure``. For a
    non-secure cookie, dropping ``sameSite`` restores the browser default.
    """
    cleaned = {k: cookie[k] for k in _COOKIE_KEYS if k in cookie}
    if cleaned.get("sameSite") == "None" and not cleaned.get("secure"):
        del cleaned["sameSite"]
    return cleaned


@dataclass(frozen=True)
class AuthedSession:
    """A browser already signed in as :attr:`username`, with a page factory bound to it."""

    driver: Driver
    username: str
    pages: PageFactory
