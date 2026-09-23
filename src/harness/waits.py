"""Wait toolkit: locators, custom expected conditions, and wait-wrapped interactions.

This module and :mod:`harness.driver` are the only places allowed to import
selenium. Everything else (page objects, components, tests) goes through the
:class:`Waiter` below, so there is exactly one place that knows about polling,
stale elements, and selenium exception types. There is no ``time.sleep`` here or
anywhere else: every pause is an explicit wait for a condition.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, TypeVar

from selenium.common.exceptions import (
    ElementClickInterceptedException,
    ElementNotInteractableException,
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.wait import WebDriverWait

from harness.errors import WaitTimeoutError

Element = WebElement
"""A located DOM element. Page objects may hold these but never import selenium."""

SearchContext = WebDriver | WebElement
"""Anything that can find elements: the whole page, or a component's root element."""

T = TypeVar("T")

DEFAULT_POLL_SECONDS = 0.25
_IGNORED = (NoSuchElementException, StaleElementReferenceException)


@dataclass(frozen=True, slots=True)
class Locator:
    """A selenium locator strategy and value, with a readable ``str`` for error messages."""

    by: str
    value: str

    def as_tuple(self) -> tuple[str, str]:
        """Return the ``(by, value)`` tuple selenium expects."""
        return (self.by, self.value)

    def __str__(self) -> str:
        return f"{self.by}={self.value!r}"


def css(selector: str) -> Locator:
    """Locate by CSS selector."""
    return Locator(By.CSS_SELECTOR, selector)


def xpath(expression: str) -> Locator:
    """Locate by XPath. Prefer :func:`css` or :func:`by_test_id` where possible."""
    return Locator(By.XPATH, expression)


def by_id(element_id: str) -> Locator:
    """Locate by element ``id``."""
    return Locator(By.ID, element_id)


def by_name(name: str) -> Locator:
    """Locate by the ``name`` attribute."""
    return Locator(By.NAME, name)


def by_test_id(value: str) -> Locator:
    """Locate by ``data-testid`` -- the preferred, most stable hook."""
    return css(f'[data-testid="{value}"]')


# --- custom expected conditions ---------------------------------------------------


def document_ready() -> Callable[[WebDriver], bool]:
    """Condition: ``document.readyState`` is ``complete``."""

    def _check(driver: WebDriver) -> bool:
        return bool(driver.execute_script("return document.readyState") == "complete")

    return _check


def url_starts_with(prefix: str) -> Callable[[WebDriver], bool]:
    """Condition: the current URL starts with ``prefix``."""

    def _check(driver: WebDriver) -> bool:
        return driver.current_url.startswith(prefix)

    return _check


def url_not_starts_with(prefix: str) -> Callable[[WebDriver], bool]:
    """Condition: the browser has navigated away from URLs starting with ``prefix``."""

    def _check(driver: WebDriver) -> bool:
        return not driver.current_url.startswith(prefix)

    return _check


def non_empty_text(locator: Locator) -> Callable[[SearchContext], str | Literal[False]]:
    """Condition: the element is visible and has non-blank text; returns the stripped text."""

    def _check(context: SearchContext) -> str | Literal[False]:
        element = context.find_element(*locator.as_tuple())
        text = element.text.strip()
        return text if element.is_displayed() and text else False

    return _check


def at_least(locator: Locator, count: int) -> Callable[[SearchContext], list[WebElement] | bool]:
    """Condition: at least ``count`` matching elements are present; returns them."""

    def _check(context: SearchContext) -> list[WebElement] | bool:
        elements = context.find_elements(*locator.as_tuple())
        return elements if len(elements) >= count else False

    return _check


# --- the waiter ---------------------------------------------------------------------


class Waiter:
    """Explicit waits and wait-wrapped interactions against a page or a component root."""

    def __init__(
        self,
        context: SearchContext,
        timeout: float,
        poll: float = DEFAULT_POLL_SECONDS,
    ) -> None:
        self._context = context
        self.timeout = timeout
        self._poll = poll

    @property
    def driver(self) -> WebDriver:
        """The underlying WebDriver, even when this waiter is scoped to an element."""
        if isinstance(self._context, WebElement):
            return self._context.parent  # type: ignore[no-any-return]
        return self._context

    def scoped(self, root: WebElement) -> Waiter:
        """Return a waiter whose lookups are confined to ``root``'s subtree."""
        return Waiter(root, self.timeout, self._poll)

    def with_timeout(self, timeout: float) -> Waiter:
        """Return a copy of this waiter with a different timeout."""
        return Waiter(self._context, timeout, self._poll)

    def until(self, condition: Callable[[SearchContext], T | Literal[False]], what: str) -> T:
        """Poll ``condition`` until truthy and return its value, or raise :class:`WaitTimeoutError`.

        ``condition`` returns a truthy value when satisfied and a falsy one to keep
        polling. ``what`` describes the awaited state in plain words for the error message.
        """
        wait: WebDriverWait[SearchContext] = WebDriverWait(
            self._context, self.timeout, poll_frequency=self._poll, ignored_exceptions=_IGNORED
        )
        try:
            return wait.until(condition)
        except TimeoutException as exc:
            raise WaitTimeoutError(
                f"Timed out after {self.timeout:g}s waiting for {what} (url: {self._safe_url()})"
            ) from exc

    def until_driver(self, condition: Callable[[WebDriver], T | Literal[False]], what: str) -> T:
        """Like :meth:`until`, but for page-level conditions that need the WebDriver itself."""
        driver = self.driver
        return self.until(lambda _ctx: condition(driver), what)

    # element lookups

    def visible(self, locator: Locator) -> WebElement:
        """Wait for ``locator`` to be visible and return the element."""
        return self.until(
            ec.visibility_of_element_located(locator.as_tuple()), f"{locator} visible"
        )

    def present(self, locator: Locator) -> WebElement:
        """Wait for ``locator`` to be in the DOM (visible or not) and return the element."""
        return self.until(ec.presence_of_element_located(locator.as_tuple()), f"{locator} present")

    def clickable(self, locator: Locator) -> WebElement:
        """Wait for ``locator`` to be visible and enabled and return the element."""
        return self.until(ec.element_to_be_clickable(locator.as_tuple()), f"{locator} clickable")

    def all_present(self, locator: Locator, minimum: int = 1) -> list[WebElement]:
        """Wait until at least ``minimum`` elements match and return all of them."""
        found = self.until(at_least(locator, minimum), f"at least {minimum} x {locator}")
        return found if isinstance(found, list) else []

    def first_visible(self, *locators: Locator) -> Locator:
        """Wait until any of ``locators`` is visible and return the one that is.

        Useful for branching flows, e.g. "OTP form or error banner, whichever appears".
        """

        def _check(context: SearchContext) -> Locator | Literal[False]:
            for locator in locators:
                for element in context.find_elements(*locator.as_tuple()):
                    if element.is_displayed():
                        return locator
            return False

        return self.until(_check, "any of " + ", ".join(str(loc) for loc in locators))

    def gone(self, locator: Locator) -> None:
        """Wait for ``locator`` to be absent or hidden."""
        self.until(
            ec.invisibility_of_element_located(locator.as_tuple()), f"{locator} to disappear"
        )

    def text_of(self, locator: Locator) -> str:
        """Wait for ``locator`` to show non-blank text and return it, stripped."""
        return self.until(non_empty_text(locator), f"{locator} to have text")

    def is_visible(self, locator: Locator, timeout: float = 0.0) -> bool:
        """Return whether ``locator`` becomes visible within ``timeout`` (default: check now)."""
        try:
            self.with_timeout(max(timeout, self._poll)).visible(locator)
        except WaitTimeoutError:
            return False
        return True

    def count(self, locator: Locator) -> int:
        """Return how many elements currently match ``locator`` (no waiting)."""
        return len(self._context.find_elements(*locator.as_tuple()))

    def find_all_now(self, locator: Locator) -> list[WebElement]:
        """Return elements currently matching ``locator`` (no waiting); may be empty."""
        return self._context.find_elements(*locator.as_tuple())

    # page-level

    def document_ready(self) -> None:
        """Wait for ``document.readyState == 'complete'``."""
        self.until_driver(document_ready(), "document.readyState == 'complete'")

    def url_starts_with(self, prefix: str) -> None:
        """Wait for the current URL to start with ``prefix``."""
        self.until_driver(url_starts_with(prefix), f"URL starting with {prefix}")

    def url_leaves(self, prefix: str) -> None:
        """Wait for the current URL to stop starting with ``prefix``."""
        self.until_driver(url_not_starts_with(prefix), f"URL to leave {prefix}")

    # interactions (retry through overlays, re-renders and stale references)

    def click(self, locator: Locator) -> None:
        """Wait for ``locator`` to be clickable and click it, retrying if something overlays it."""

        def _click(context: SearchContext) -> bool:
            element = ec.element_to_be_clickable(locator.as_tuple())(context)
            if not element:
                return False
            try:
                element.click()
            except (ElementClickInterceptedException, ElementNotInteractableException):
                return False
            return True

        self.until(_click, f"{locator} to accept a click")

    def type_text(self, locator: Locator, text: str, *, clear: bool = True) -> None:
        """Wait for ``locator`` to be interactable, optionally clear it, then type ``text``."""

        def _type(context: SearchContext) -> bool:
            element = ec.element_to_be_clickable(locator.as_tuple())(context)
            if not element:
                return False
            try:
                if clear:
                    element.clear()
                element.send_keys(text)
            except ElementNotInteractableException:
                return False
            return True

        self.until(_type, f"{locator} to accept text")

    def _safe_url(self) -> str:
        try:
            return self.driver.current_url
        except Exception:  # noqa: BLE001 - diagnostics only; never mask the timeout
            return "<unavailable>"
