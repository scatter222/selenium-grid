"""Exception hierarchy for the harness.

Every error raised deliberately by harness code derives from :class:`HarnessError`
so callers (fixtures, CI scripts) can catch one type and print a readable message.
"""

from __future__ import annotations

from collections.abc import Sequence


class HarnessError(Exception):
    """Base class for all harness errors."""


class ConfigError(HarnessError):
    """The environment YAML file is missing, unreadable, or fails validation."""


class MissingSecretError(HarnessError):
    """One or more secrets referenced by the config are not set in the environment."""

    def __init__(self, missing: Sequence[str]) -> None:
        self.missing = sorted(set(missing))
        names = "\n".join(f"  - {name}" for name in self.missing)
        super().__init__(
            "Required secret environment variable(s) are not set:\n"
            f"{names}\n"
            "Secrets are never read from the YAML file. Export them in your shell, "
            "or define them as masked, protected CI/CD variables in GitLab."
        )


class GridUnavailableError(HarnessError):
    """The Selenium Grid hub could not be reached at all (connection-level failure)."""


class EnvironmentNotReadyError(HarnessError):
    """The kit is reachable but one or more readiness checks failed."""


class PageNotReadyError(HarnessError):
    """A page object's readiness condition was not met within its timeout."""


class WaitTimeoutError(HarnessError):
    """An explicit wait expired. Raised by :mod:`harness.waits` in place of selenium's error."""


class DriverStartError(HarnessError):
    """The Grid was reachable but refused or failed to create a browser session."""
