"""Verify the Selenium Grid hub is up and offers the slots the config expects.

Thin CLI over :mod:`harness.health`. Exit status 0 = OK, 1 = hub down or short of
slots, 2 = configuration problem.

    uv run python ci/check_grid.py --env=env/virtual.yaml
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from harness.config import RunOptions, load_settings
from harness.errors import HarnessError
from harness.health import HealthReport, check_grid, check_grid_slots, make_client


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, check the hub, print a summary, and return an exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env", type=Path, default=RunOptions().env_file, help="environment YAML")
    args = parser.parse_args(argv)

    try:
        settings = load_settings(args.env)
        with make_client(settings) as client:
            hub = str(settings.grid.hub_url)
            report = HealthReport(
                (
                    check_grid(client, hub),
                    check_grid_slots(client, hub, settings.grid.expected_slots),
                )
            )
    except HarnessError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(report.summary())
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
