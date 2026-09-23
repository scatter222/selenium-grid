"""Data table component: reads headers and rows as plain Python values."""

from __future__ import annotations

from typing import Literal

from harness.pages.components.base import Component
from harness.waits import SearchContext, css

Row = dict[str, str]


class DataTable(Component):
    """An HTML ``<table>`` with a ``<thead>`` header row and ``<tbody>`` data rows.

    Reads are done inside a wait so a table that re-renders mid-read (stale
    elements) is simply read again rather than failing the test.
    """

    default_root = css("table")
    HEADER_CELLS = css("thead th")
    BODY_ROWS = css("tbody tr")
    CELLS = css("td")

    def headers(self) -> list[str]:
        """Return the column header texts, in order."""
        cells = self.within().all_present(self.HEADER_CELLS)
        return [cell.text.strip() for cell in cells]

    def wait_for_rows(self, minimum: int = 1) -> int:
        """Wait until the table has at least ``minimum`` body rows; return the row count."""
        return len(self.within().all_present(self.BODY_ROWS, minimum))

    def rows(self) -> list[Row]:
        """Return every body row as a ``{header: cell text}`` mapping (may be empty)."""

        def _read(context: SearchContext) -> tuple[list[Row]] | Literal[False]:
            header_cells = context.find_elements(*self.HEADER_CELLS.as_tuple())
            headers = [c.text.strip() for c in header_cells]
            if not headers:
                return False
            rows: list[Row] = []
            for tr in context.find_elements(*self.BODY_ROWS.as_tuple()):
                cells = [c.text.strip() for c in tr.find_elements(*self.CELLS.as_tuple())]
                rows.append(dict(zip(headers, cells, strict=False)))
            return (rows,)  # 1-tuple is truthy even when there are no rows

        return self.within().until(_read, f"table {self.root_locator} to be readable")[0]

    def find_row(self, column: str, value: str) -> Row | None:
        """Return the first row whose ``column`` cell equals ``value``, or ``None``."""
        return next((row for row in self.rows() if row.get(column) == value), None)
