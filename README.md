# selenium-grid: remote Selenium test harness

End-to-end browser tests for the deployable system: a KVM server whose guests are
VyOS (internal routing), a Keycloak-style IdP, and several web app VMs, used from
laptops across a switch and a firewall.

```
GitLab runner (mgmt network)                        Grid nodes (workstation network)
  pytest ── WebDriver HTTP ──► Grid hub ──────────► Firefox on the laptop image
    │                                                  │
    └── readiness checks (httpx) ──► VyOS API,         └── browser traffic ──► firewall ──► VyOS ──► IdP / apps
                                      IdP, apps
```

The same suite runs unchanged against the vCenter replica (`env/virtual.yaml`) and
the physical kit (`env/physical.yaml`). Only the `--env` file differs.

## Layout

```
env/                    virtual.yaml, physical.yaml (identical keys), schema.md
src/harness/
  config.py             Settings model: YAML + secrets from env vars
  driver.py             Remote WebDriver factory, Firefox caps, BiDi console capture   [selenium]
  waits.py              Locators, custom expected conditions, Waiter                   [selenium]
  auth.py               UI login, TOTP, cookie capture/injection
  health.py             Readiness checks (Grid, VyOS, IdP, each app)
  page_factory.py       Builds page objects from Settings
  pytest_plugin.py      --env / --require-kit options (pytest11 entry point)
  pages/
    base_page.py        navigation, page-ready, wait-wrapped interactions
    components/         NavBar, Modal, DataTable
    auth/login_page.py  IdP login + OTP
    app_one/            one package per web app
tests/
  conftest.py           settings, environment_ready, driver, authed_session, failure hook
  smoke/                health + login
  regression/app_one/   per-app regression tests
  unit/                 offline tests of the harness itself (env files, layering rules)
ci/                     wait_healthy.py, check_grid.py (thin CLIs over harness.health)
infra/                  Selenium Grid install: hub + nodes on RHEL-family VMs (systemd, offline)
```

### Layering rules and how they're enforced

| Rule | Enforcement |
|---|---|
| 1. Tests never import selenium, and contain no locators, waits or sleeps | `tests/unit/test_architecture.py` |
| 2. Page objects never read env vars or config | `test_architecture.py`. Pages take `driver, base_url, timeout`. `PageFactory` supplies them. |
| 3. Only `driver.py` and `waits.py` import selenium | ruff `TID251` (banned-api) + `test_architecture.py` |
| 4. No `time.sleep()` anywhere | ruff `TID251` + `test_architecture.py` |

## Setting up the Grid

The harness is a Grid **client**: it doesn't start browsers or the Grid. To build
the Grid (a hub on a dual-homed VM, a node on each laptop-image VM, fully offline),
follow **[infra/README.md](infra/README.md)**. It covers the port matrix, the
install scripts, `infra/verify.sh`, IdP test users, and a single-VM dev setup.

## Setup

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```sh
uv sync                        # creates .venv from uv.lock (all versions pinned)
uv run pre-commit install      # optional; hooks are local, no network needed
make check                     # ruff, mypy --strict, shellcheck, offline unit tests
```

## Required environment variables

Secrets are **never** in YAML. The YAML names the variable (`*_env` keys) and the
harness reads it at runtime. If any are missing, the run fails before any browser
test and every missing name is listed.

| Variable | Purpose |
|---|---|
| `HARNESS_VYOS_API_KEY` | VyOS HTTPS API key (readiness check) |
| `HARNESS_STANDARD_PASSWORD` | `standard` user password |
| `HARNESS_STANDARD_TOTP_SEED` | `standard` user TOTP seed (base32) |
| `HARNESS_ADMIN_PASSWORD` | `admin` user password |
| `HARNESS_ADMIN_TOTP_SEED` | `admin` user TOTP seed (base32) |

Optional run-level switches:

| Variable | Default | Purpose |
|---|---|---|
| `HARNESS_ENV_FILE` | `env/virtual.yaml` | Environment file if `--env` isn't given |
| `HARNESS_REQUIRE_KIT` | `false` | Same as `--require-kit` |

In GitLab, define the secrets as **masked, protected** CI/CD variables.

## Running

### Against each environment

```sh
uv run pytest --env=env/virtual.yaml        # vCenter kit
uv run pytest --env=env/physical.yaml       # physical kit
make smoke ENV=env/physical.yaml            # same thing via make
```

Before browser tests start, the `environment_ready` fixture checks the kit in this order:

1. **Grid hub unreachable** (connection-level failure): kit tests are **skipped** with
   a clear reason, so you can verify the scaffold on a laptop with no kit. Add
   `--require-kit` (CI always does) to make that a failure.
2. **Secrets missing**: failure, listing every missing variable.
3. **Any readiness check failing** (Grid not ready, VyOS, IdP, an app): failure with
   a one-line-per-check summary, and no browser session is started.

Use the `--env=PATH` form (with `=`). pytest pre-scans the command line before
plugins load, and a separate path argument outside the repo would be mistaken
for a test path. Keep `--alluredir`/`--junitxml` paths inside the repo for the
same reason.

Check the kit without running tests:

```sh
make grid ENV=env/virtual.yaml     # hub up and slots >= grid.expected_slots
make health ENV=env/virtual.yaml   # retries readiness checks up to timeouts.health_total
```

### One app's tests

Every app has a marker (declared in `pyproject.toml`; unknown markers are errors):

```sh
uv run pytest --env=env/virtual.yaml -m app_one
uv run pytest --env=env/virtual.yaml -m "regression and app_one"
make app APP=app_one
```

### In parallel

pytest-xdist runs one browser per worker, so size `-n` to the **Grid slots**, not to
the runner's CPUs:

```sh
uv run pytest --env=env/virtual.yaml -n 4
make parallel N=4
```

Each worker logs in through the UI once (`login_state`) and then injects cookies per
test. See the TOTP note under *Gotchas*.

### Reports

```sh
uv run pytest --env=env/virtual.yaml --alluredir=reports/allure-results --junitxml=reports/junit.xml
```

When a test that used a browser fails, the Allure result gets a **screenshot**, the
**page URL** and the **browser console log**. Firefox has no `get_log('browser')`,
so console output and JS errors are collected over WebDriver BiDi (`webSocketUrl`).
If the Grid doesn't proxy BiDi, the attachment says so. The failing URL is also
written to the JUnit XML as a `failure_url` property. In the Grid UI, each session
is named after its pytest node id (`se:name`).

## CI (`.gitlab-ci.yml`)

Stages: `reset → deploy → health → smoke → regression → collect`, plus a kit-free
`static-checks` job in `.pre` (ruff, mypy, unit tests). Jobs run on runners tagged
`harness`. Kit jobs hold `resource_group: virtual-kit`. JUnit XML is published through
`artifacts:reports:junit`, so failures show in merge requests. Allure results are kept
as artifacts, and `collect` gathers them into one artifact (it also generates the
HTML report if the `allure` CLI is on the runner). All artifacts use `when: always`.

`reset-kit` and `deploy` are **placeholders** (they only echo). Fill in the vCenter
snapshot revert and your deployment.

> **Kit locking caveat:** GitLab's `resource_group` locks one *job* at a time, so
> another pipeline's job can slip in between this pipeline's `reset` and `smoke`.
> If that becomes a problem, move the kit stages into a child pipeline triggered by
> a single job that holds `resource_group: virtual-kit`. That locks the whole run.

To run against the physical kit, run a pipeline with `HARNESS_ENV_FILE=env/physical.yaml`
and give those jobs their own resource group.

## Air-gapped operation

Nothing in the harness contacts the internet at runtime:

* **Selenium Manager is disabled.** `SE_OFFLINE=true` is set by the pytest plugin and
  in CI. Sessions are always `webdriver.Remote` against the hub, so no local driver
  is resolved. The Grid nodes installed by `infra/` use a pinned geckodriver with
  `selenium-manager = false`, `detect-drivers = false` and `SE_OFFLINE=true`.
* **Firefox call-home is off.** `harness.driver.AIRGAP_FIREFOX_PREFS` disables
  updates, safe-browsing list fetches, telemetry, captive-portal and connectivity
  probes, and OCSP.
* **HTTP from the runner** (health checks, hub) ignores `HTTP(S)_PROXY` unless
  `network.use_env_proxy: true`, and uses the internal CA via `tls.ca_bundle`
  (or the system store).
* **pre-commit** uses only `repo: local` hooks, so it never clones hook repos.

### Air-gapped installs (internal package index)

With **uv**, point it at the mirror, then re-lock once so `uv.lock` records mirror URLs
(the committed lock references pypi.org):

```sh
export UV_DEFAULT_INDEX=https://pypi.internal.example/simple
export UV_PYTHON_DOWNLOADS=never
uv lock                      # rewrites registry URLs in uv.lock; commit the result
uv sync --frozen
```

Or set it permanently in `pyproject.toml`:

```toml
[[tool.uv.index]]
name = "internal"
url = "https://pypi.internal.example/simple"
default = true
```

With **pip**, export a hash-pinned requirements file and install from the mirror:

```sh
uv export --frozen --no-emit-project --format requirements-txt > requirements.lock
pip install --index-url https://pypi.internal.example/simple --require-hashes -r requirements.lock
pip install --no-deps -e .
# or persistently: pip config set global.index-url https://pypi.internal.example/simple
```

For a fully offline box, `pip download -r requirements.lock -d wheelhouse/` on a
connected machine, copy the wheelhouse across, then
`pip install --no-index --find-links wheelhouse/ -r requirements.lock`.

## Extending

### Add a page object

1. Create `src/harness/pages/<app>/<name>_page.py`:

   ```python
   from harness.pages.base_page import BasePage
   from harness.pages.components import DataTable
   from harness.waits import by_test_id


   class InvoicesPage(BasePage):
       """Invoice list."""

       path = "/invoices"  # relative to the app's base_url
       ready_locator = by_test_id("invoices-page")  # visible == page is ready
       SEARCH = by_test_id("invoice-search")

       @property
       def table(self) -> DataTable:
           """The invoices table."""
           return DataTable(self.driver, self.timeout, root=by_test_id("invoices-table"))

       def search(self, text: str) -> None:
           """Filter invoices by free text."""
           self.wait.type_text(self.SEARCH, text)

       def invoice_numbers(self) -> list[str]:
           """Invoice numbers currently listed."""
           return [row["Number"] for row in self.table.rows()]
   ```

2. Keep all locators and waits in the page. Methods return plain values (`str`,
   `list`, `dict`, another page object), never elements, so tests only assert.
3. Use `self.wait` (a `Waiter`) for everything: `visible`, `click`, `type_text`,
   `text_of`, `first_visible`, `until(...)`. For a new kind of condition, add it to
   `harness/waits.py`, the only place allowed to touch selenium.
4. Reuse widgets from `pages/components/`. A new shared widget subclasses `Component`
   and sets `default_root`.
5. Export it from the app package's `__init__.py` and use it in a test:

   ```python
   def test_search_filters(authed_session: AuthedSession) -> None:
       """Searching narrows the list."""
       page = authed_session.pages.app("app_one", InvoicesPage).open()
       page.search("INV-0042")
       assert page.invoice_numbers() == ["INV-0042"]
   ```

### Add a new app

1. **Config:** add the app under `apps:` in **every** file in `env/`, with the same
   keys (`base_url`, `health_path`, `cookie_landing_path`). The unit tests fail if the
   files drift apart.
2. **Marker:** add `"app_two: tests for app_two"` to `markers` in `pyproject.toml`.
   A unit test fails if an app has no marker.
3. **Page objects:** create `src/harness/pages/app_two/` with `__init__.py` and pages
   as above.
4. **Tests:** create `tests/regression/app_two/` (with `__init__.py`) and mark the
   module `pytestmark = [pytest.mark.regression, pytest.mark.app_two]`.
5. **Health:** nothing to do. `harness.health` checks every configured app, and
   `authed_session` captures cookies for every app origin.

## Gotchas

* **TOTP reuse.** Each xdist worker logs in once. With `-n 4`, the same user logs in
  four times within seconds using the *same* code. Keycloak rejects that unless the
  test realm's OTP policy allows reusable codes ("Reusable token: ON"). Enable it in
  the test realm, or give each worker its own user.
* **Cookie landing paths.** WebDriver can only read or set cookies whose domain *and
  path* match the loaded page. `idp.cookie_landing_path` must be under
  `/realms/<realm>/` (Keycloak scopes its SSO cookies there). App landing paths
  must load without redirecting off-origin.
* **Negative login uses an unknown username**, not a real user with a bad password,
  so it can't trip the IdP's brute-force lockout on a shared test account.
* **Locators are placeholders.** The IdP ones match Keycloak's stock theme. The app
  ones assume `data-testid` hooks. Adjust them in the page objects, and nowhere else.
