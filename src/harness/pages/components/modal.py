"""Generic modal dialog (``role="dialog"``)."""

from __future__ import annotations

from harness.pages.components.base import Component
from harness.waits import by_test_id, css


class Modal(Component):
    """A dialog with a title and confirm/dismiss buttons."""

    default_root = css('[role="dialog"]')
    TITLE = css("h1, h2, [data-testid='modal-title']")
    CONFIRM = by_test_id("modal-confirm")
    DISMISS = by_test_id("modal-dismiss")

    def title(self) -> str:
        """Return the dialog title text."""
        return self.within().text_of(self.TITLE)

    def confirm(self) -> None:
        """Click the confirm button and wait for the dialog to close."""
        self.within().click(self.CONFIRM)
        self.wait_closed()

    def dismiss(self) -> None:
        """Click the dismiss button and wait for the dialog to close."""
        self.within().click(self.DISMISS)
        self.wait_closed()

    def wait_closed(self) -> None:
        """Wait until the dialog is no longer visible."""
        self._page_wait.gone(self.root_locator)
