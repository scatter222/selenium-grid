"""Base class for reusable page components."""

from __future__ import annotations

from typing import ClassVar

from harness.driver import Driver
from harness.waits import Element, Locator, Waiter


class Component:
    """A widget identified by a root locator; all lookups are scoped to that root.

    The root element is re-located on every call, so a component survives the
    widget being re-rendered between interactions.
    """

    default_root: ClassVar[Locator]

    def __init__(self, driver: Driver, timeout: float, root: Locator | None = None) -> None:
        self.driver = driver
        self.root_locator = root or self.default_root
        self._page_wait = Waiter(driver, timeout)

    def root(self) -> Element:
        """Wait for the component's root to be visible and return it."""
        return self._page_wait.visible(self.root_locator)

    def within(self) -> Waiter:
        """Return a waiter scoped to the (freshly located) root element."""
        return self._page_wait.scoped(self.root())

    def is_displayed(self, timeout: float = 0.0) -> bool:
        """Return whether the component is visible (optionally waiting ``timeout``)."""
        return self._page_wait.is_visible(self.root_locator, timeout)
