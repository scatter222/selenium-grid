"""Readiness checks for the kit, importable by fixtures and CI scripts alike.

Checks run from the pytest runner on the management network. Each one returns a
:class:`CheckResult`; :func:`run_checks` bundles them into a :class:`HealthReport`
whose :meth:`~HealthReport.summary` is printed when the environment is not ready.
Nothing here reaches beyond the kit: no internet access is needed or attempted.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass

import httpx
from tenacity import RetryCallState, Retrying, retry_if_result, stop_after_delay, wait_fixed

from harness.config import AppConfig, Settings, resolve_secret
from harness.errors import MissingSecretError


@dataclass(frozen=True)
class CheckResult:
    """Outcome of one readiness check."""

    name: str
    target: str
    ok: bool
    detail: str
    elapsed_s: float = 0.0
    skipped: bool = False


@dataclass(frozen=True)
class HealthReport:
    """All check results for one pass over the kit."""

    results: tuple[CheckResult, ...]

    @property
    def ok(self) -> bool:
        """True when every check that ran passed."""
        return not self.failures

    @property
    def failures(self) -> list[CheckResult]:
        """The checks that ran and failed."""
        return [r for r in self.results if not r.ok and not r.skipped]

    def summary(self) -> str:
        """Return a fixed-width, one-line-per-check summary suitable for logs."""
        width = max((len(r.name) for r in self.results), default=4)
        lines = [
            f"  [{_label(r)}] {r.name:<{width}}  {r.target}  -- {r.detail}" for r in self.results
        ]
        verdict = "READY" if self.ok else f"NOT READY ({len(self.failures)} failing)"
        return f"Kit health: {verdict}\n" + "\n".join(lines)


def _label(result: CheckResult) -> str:
    if result.skipped:
        return "SKIP"
    return "PASS" if result.ok else "FAIL"


def skipped(name: str, target: str, switch: str) -> CheckResult:
    """A placeholder result for a check disabled in the env file's ``checks`` section."""
    return CheckResult(name, target, ok=False, detail=f"disabled ({switch}=false)", skipped=True)


def make_client(settings: Settings) -> httpx.Client:
    """Return an HTTP client configured for runner-to-kit traffic (TLS, proxy, timeout)."""
    return httpx.Client(
        timeout=settings.timeouts.health_request,
        verify=settings.tls.httpx_verify(),
        trust_env=settings.network.use_env_proxy,
        follow_redirects=False,
    )


def _timed(name: str, target: str, fn: Callable[[], tuple[bool, str]]) -> CheckResult:
    start = time.monotonic()
    try:
        ok, detail = fn()
    except httpx.HTTPError as exc:
        ok, detail = False, f"{type(exc).__name__}: {exc}"
    return CheckResult(name, target, ok, detail, round(time.monotonic() - start, 3))


def check_http(client: httpx.Client, name: str, url: str) -> CheckResult:
    """Pass if ``url`` answers with a 2xx or 3xx status (3xx = e.g. redirect to login)."""

    def _do() -> tuple[bool, str]:
        resp = client.get(url)
        return resp.status_code < 400, f"HTTP {resp.status_code}"

    return _timed(name, url, _do)


def grid_reachable(client: httpx.Client, hub_url: str) -> bool:
    """Return False only if the hub cannot be reached at the network level.

    Any HTTP response -- even an error -- counts as reachable: that is a broken kit,
    which must fail rather than skip.
    """
    try:
        client.get(_join(hub_url, "/status"))
    except httpx.TransportError:
        return False
    return True


def check_grid(client: httpx.Client, hub_url: str) -> CheckResult:
    """Pass if the hub's ``/status`` reports ``ready: true``."""
    url = _join(hub_url, "/status")

    def _do() -> tuple[bool, str]:
        resp = client.get(url)
        if resp.status_code != 200:
            return False, f"HTTP {resp.status_code}"
        value = resp.json().get("value", {})
        return bool(value.get("ready")), str(value.get("message", "no message"))

    return _timed("grid", url, _do)


def grid_slots(client: httpx.Client, hub_url: str) -> Counter[str]:
    """Return the number of Grid slots per ``browserName`` from ``/status``."""
    resp = client.get(_join(hub_url, "/status"))
    resp.raise_for_status()
    slots: Counter[str] = Counter()
    for node in resp.json().get("value", {}).get("nodes", []):
        if node.get("availability") != "UP":
            continue
        for slot in node.get("slots", []):
            slots[slot.get("stereotype", {}).get("browserName", "unknown")] += 1
    return slots


def check_grid_slots(
    client: httpx.Client, hub_url: str, expected: Mapping[str, int]
) -> CheckResult:
    """Pass if every browser in ``expected`` has at least that many slots on UP nodes."""

    def _do() -> tuple[bool, str]:
        actual = grid_slots(client, hub_url)
        short = {b: (actual.get(b, 0), n) for b, n in expected.items() if actual.get(b, 0) < n}
        found = ", ".join(f"{b}={n}" for b, n in sorted(actual.items())) or "none"
        if short:
            want = ", ".join(f"{b}: have {have}, need {need}" for b, (have, need) in short.items())
            return False, f"insufficient slots ({want}); found {found}"
        return True, f"slots: {found}"

    return _timed("grid-slots", hub_url, _do)


def check_vyos(client: httpx.Client, api_url: str, api_key: str) -> CheckResult:
    """Pass if the VyOS HTTPS API answers a read-only ``showConfig`` successfully."""
    url = _join(api_url, "/retrieve")
    payload = {"op": "showConfig", "path": ["system", "host-name"]}

    def _do() -> tuple[bool, str]:
        resp = client.post(url, data={"data": json.dumps(payload), "key": api_key})
        if resp.status_code != 200:
            return False, f"HTTP {resp.status_code}"
        body = resp.json()
        if not body.get("success"):
            return False, f"API error: {body.get('error')}"
        return True, f"host-name={body.get('data')}"

    return _timed("vyos", url, _do)


def check_app(client: httpx.Client, name: str, app: AppConfig) -> CheckResult:
    """Check one web app's health path."""
    return check_http(client, f"app:{name}", _join(str(app.base_url), app.health_path))


def check_apps(client: httpx.Client, apps: Mapping[str, AppConfig]) -> list[CheckResult]:
    """Check every configured web app."""
    return [check_app(client, name, app) for name, app in sorted(apps.items())]


def run_checks(
    settings: Settings,
    environ: Mapping[str, str] | None = None,
    *,
    include_grid: bool = True,
) -> HealthReport:
    """Run every readiness check once and return the report. Never raises for a failed check."""
    results: list[CheckResult] = []
    with make_client(settings) as client:
        if include_grid:
            results.append(check_grid(client, str(settings.grid.hub_url)))
        results.append(_vyos(client, settings, environ))
        idp_url = _join(str(settings.idp.base_url), settings.idp.health_path)
        if settings.checks.idp:
            results.append(check_http(client, "idp", idp_url))
        else:
            results.append(skipped("idp", idp_url, "checks.idp"))
        if settings.checks.apps:
            results.extend(check_apps(client, settings.apps))
        else:
            results.extend(
                skipped(f"app:{name}", _join(str(app.base_url), app.health_path), "checks.apps")
                for name, app in sorted(settings.apps.items())
            )
    return HealthReport(tuple(results))


def _vyos(
    client: httpx.Client, settings: Settings, environ: Mapping[str, str] | None
) -> CheckResult:
    """Run the VyOS check if enabled; a missing API key is reported as a failure, not raised."""
    api_url = str(settings.vyos.api_url)
    if not settings.checks.vyos:
        return skipped("vyos", api_url, "checks.vyos")
    try:
        api_key = resolve_secret(settings.vyos.api_key_env, environ)
    except MissingSecretError as exc:
        return CheckResult("vyos", api_url, False, str(exc))
    return check_vyos(client, api_url, api_key)


def wait_until_healthy(
    settings: Settings,
    timeout: float,
    interval: float = 10.0,
    on_attempt: Callable[[int, HealthReport], None] | None = None,
) -> HealthReport:
    """Re-run :func:`run_checks` every ``interval`` seconds until healthy or ``timeout`` passes.

    Returns the last report either way; check ``report.ok``.
    """
    attempt = 0

    def _run() -> HealthReport:
        nonlocal attempt
        attempt += 1
        report = run_checks(settings)
        if on_attempt is not None:
            on_attempt(attempt, report)
        return report

    def _last(state: RetryCallState) -> HealthReport:
        assert state.outcome is not None
        result: HealthReport = state.outcome.result()
        return result

    retrying = Retrying(
        stop=stop_after_delay(timeout),
        wait=wait_fixed(interval),
        retry=retry_if_result(lambda report: not report.ok),
        retry_error_callback=_last,
    )
    report: HealthReport = retrying(_run)
    return report


def _join(base: str, path: str) -> str:
    return base.rstrip("/") + "/" + path.lstrip("/")
