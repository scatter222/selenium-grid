"""Block until the kit passes every readiness check, or time out.

Thin CLI over :func:`harness.health.wait_until_healthy`. Exit status 0 = ready,
1 = still not ready at the deadline, 2 = configuration or secret problem.

    uv run python ci/wait_healthy.py --env=env/virtual.yaml [--timeout 900] [--interval 15]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from harness.config import RunOptions, load_settings
from harness.errors import HarnessError
from harness.health import HealthReport, wait_until_healthy


def _print_attempt(attempt: int, report: HealthReport) -> None:
    """Print one attempt's summary, flushed so CI logs stream."""
    print(f"--- attempt {attempt} ---\n{report.summary()}", flush=True)


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, wait for the kit, and return a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env", type=Path, default=RunOptions().env_file, help="environment YAML")
    parser.add_argument("--timeout", type=float, help="seconds (default: timeouts.health_total)")
    parser.add_argument("--interval", type=float, default=15.0, help="seconds between attempts")
    args = parser.parse_args(argv)

    try:
        settings = load_settings(args.env)
        settings.check_secrets()
    except HarnessError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    timeout = args.timeout if args.timeout is not None else settings.timeouts.health_total
    print(f"Waiting up to {timeout:g}s for the {settings.name} kit to become ready...", flush=True)
    report = wait_until_healthy(settings, timeout, args.interval, on_attempt=_print_attempt)
    if report.ok:
        print("Kit is ready.")
        return 0
    print(f"Kit NOT ready after {timeout:g}s.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
