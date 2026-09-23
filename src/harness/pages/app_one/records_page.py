"""app_one records list. Locators are placeholders; adjust to the real markup."""

from __future__ import annotations

from harness.pages.base_page import BasePage
from harness.pages.components import DataTable, NavBar
from harness.pages.components.table import Row
from harness.waits import by_test_id


class RecordsPage(BasePage):
    """A list of records shown in a data table."""

    path = "/records"
    ready_locator = by_test_id("records-page")

    @property
    def nav(self) -> NavBar:
        """The shared navigation bar."""
        return NavBar(self.driver, self.timeout)

    @property
    def table(self) -> DataTable:
        """The records table."""
        return DataTable(self.driver, self.timeout, root=by_test_id("records-table"))

    def column_headers(self) -> list[str]:
        """Return the table's column headers."""
        return self.table.headers()

    def record_count(self, minimum: int = 1) -> int:
        """Wait for at least ``minimum`` records and return how many are shown."""
        return self.table.wait_for_rows(minimum)

    def records(self) -> list[Row]:
        """Return all records as ``{column: value}`` mappings."""
        return self.table.rows()
