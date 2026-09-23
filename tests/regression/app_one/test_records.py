"""app_one records list, using an already-authenticated browser."""

import pytest

from harness.auth import AuthedSession
from harness.pages.app_one import RecordsPage

pytestmark = [pytest.mark.regression, pytest.mark.app_one]


def test_records_table_lists_records(authed_session: AuthedSession) -> None:
    """A signed-in user sees a records table with headers and at least one row."""
    records = authed_session.pages.app("app_one", RecordsPage).open()

    headers = records.column_headers()
    assert headers, "records table has no column headers"
    assert records.record_count(minimum=1) >= 1
    assert all(set(row) <= set(headers) for row in records.records())
