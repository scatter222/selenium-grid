# Environment file schema

Each file in `env/` describes one kit. The suite reads exactly one of them, chosen
with `--env` (or `HARNESS_ENV_FILE`). Only the file changes between the vCenter kit
(`virtual.yaml`) and the real hardware (`physical.yaml`). The code stays the same.

Rules:

* **No secrets in YAML.** A field ending in `_env` holds the *name* of an environment
  variable, never a value. Unknown keys are rejected, so `password: hunter2` fails
  validation instead of slipping through.
* **Identical keys.** Every file has the same key structure. `tests/unit/test_env_files.py`
  enforces this, so a key added to one file must be added to all of them.
* Durations are in **seconds**.

| Key | Type | Meaning |
|---|---|---|
| `name` | str | Label shown in reports (`virtual`, `physical`). |
| `grid.hub_url` | URL | Selenium Grid hub as reached from the runner (management network). |
| `grid.expected_slots` | map browser→int | Minimum slots per `browserName` on UP nodes. Checked by `ci/check_grid.py`. |
| `browser.name` | `firefox` | Browser requested from the Grid. |
| `browser.version` | str | `browserVersion` capability. `""` means any version. |
| `browser.platform` | str | `platformName` capability (nodes are `linux`). |
| `browser.headless` | bool | Run Firefox with `-headless`. |
| `browser.capture_console` | bool | Collect console output and JS errors over WebDriver BiDi, to attach to failed tests. |
| `browser.accept_insecure_certs` | bool | Let the browser accept untrusted TLS. Keep this `false` and install the internal CA on the laptop image instead. |
| `timeouts.page_load` | float | WebDriver page-load timeout. |
| `timeouts.element` | float | Default explicit-wait timeout used by page objects. |
| `timeouts.health_request` | float | Per-request timeout for readiness checks. |
| `timeouts.health_total` | float | Overall budget for `ci/wait_healthy.py`. |
| `timeouts.grid_command` | int | HTTP timeout for each WebDriver command sent to the hub. |
| `tls.verify` | bool | Verify TLS for runner→kit HTTP calls (health checks, hub). |
| `tls.ca_bundle` | path / null | Internal CA bundle. `null` uses the system trust store. |
| `network.use_env_proxy` | bool | Whether runner→kit traffic honours `HTTP(S)_PROXY`. Normally `false`. |
| `checks.vyos` | bool | Run the VyOS API readiness check from the runner. When `false`, `vyos.api_key_env` isn't required. |
| `checks.idp` | bool | Check the IdP health path from the runner. |
| `checks.apps` | bool | Check each app's health path from the runner. Also gates `tests/smoke/test_health.py`. |
| `idp.base_url` | URL | IdP (Keycloak-style) base URL as the *browser* sees it. |
| `idp.realm` | str | Realm the test users live in. |
| `idp.entry_app` | str | Key in `apps` whose URL starts the UI login flow. |
| `idp.health_path` | str | Path checked for readiness (OIDC discovery document). |
| `idp.cookie_landing_path` | str | Same-origin path that loads **without redirect** and sits **under the realm cookie path** (`/realms/<realm>/...`). WebDriver can only read and set cookies whose path matches the loaded page. The OIDC discovery document works. |
| `vyos.api_url` | URL | VyOS HTTPS API on the management interface. |
| `vyos.api_key_env` | env var name | Variable holding the VyOS API key. |
| `apps.<name>.base_url` | URL | App base URL as the browser sees it. `<name>` must also be a pytest marker. |
| `apps.<name>.health_path` | str | Path whose 2xx/3xx response means the app is up. |
| `apps.<name>.cookie_landing_path` | str | Like `idp.cookie_landing_path`, for this app's origin. |
| `users.<key>.username` | str | Login name. |
| `users.<key>.role` | str | Role label (informational; lets tests pick users by role). |
| `users.<key>.password_env` | env var name | Variable holding the password. |
| `users.<key>.totp_seed_env` | env var name / null | Variable holding the base32 TOTP seed. `null` for users without MFA. |
| `default_user` | str | Key in `users` used by the `authed_session` fixture. |

## Secrets referenced by the shipped files

| Variable | Used for |
|---|---|
| `HARNESS_VYOS_API_KEY` | VyOS readiness check (only while `checks.vyos: true`) |
| `HARNESS_STANDARD_PASSWORD` | `standard` user password |
| `HARNESS_STANDARD_TOTP_SEED` | `standard` user TOTP seed (base32) |
| `HARNESS_ADMIN_PASSWORD` | `admin` user password |
| `HARNESS_ADMIN_TOTP_SEED` | `admin` user TOTP seed (base32) |
