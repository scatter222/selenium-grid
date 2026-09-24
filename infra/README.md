# Selenium Grid infrastructure

Everything needed to stand up the Selenium Grid the harness drives: one **hub** on a
dual-homed VM, and a **node** on each laptop-image VM. The targets are RHEL, Rocky
or Alma 9, set up with shell scripts and systemd, and nothing is downloaded at install
time.

```
infra/
  versions.env              pinned Selenium / geckodriver versions + SHA-256, ports, paths
  bundle.sh                 build the offline bundle (run on a connected machine)
  verify.sh                 end-to-end Grid check using curl + python3 (run anywhere)
  lib/common.sh             shared helpers
  hub/install.sh            install the hub (systemd: selenium-hub)
  hub/hub.toml.tmpl
  hub/selenium-hub.service
  node/install.sh           turn a laptop-image VM into a node (systemd: selenium-node)
  node/node.toml.tmpl
  node/selenium-node.service
  node/run-foreground.sh    run the node in the desktop session to watch Firefox
  standalone/run.sh         dev only: hub + node in one process on one VM
```

## Topology

```
          MANAGEMENT NETWORK                          WORKSTATION NETWORK
 ┌──────────────────────┐               ┌───────────────────────────┐
 │ GitLab runner        │   :4444       │ Hub VM (dual-homed)       │
 │  pytest ─────────────┼──────────────►│ mgmt NIC      ws NIC      │
 │                      │  WebDriver +  │  (4444)     (4442/4443)   │
 └──────────────────────┘  BiDi (ws)    └───────────────┬───────────┘
                                                        │ :5555 hub → node
                                  :4442/4443 node → hub │
                                        ┌───────────────┴───────────┐
                                        │ Laptop-image VMs (nodes)  │
                                        │  Firefox + geckodriver    │
                                        └───────────────┬───────────┘
                                                        │ HTTPS, as a user's laptop would
                                                  firewall → VyOS → IdP / app VMs
```

### Port matrix

| From | To | Port | Why |
|---|---|---|---|
| runner (mgmt) | hub mgmt NIC | 4444/tcp | WebDriver commands **and** the BiDi websocket (console capture) |
| each node | hub workstation NIC | 4442/tcp, 4443/tcp | Event bus: registration, heartbeats |
| hub workstation NIC | each node | 5555/tcp | Hub forwards sessions to the node |
| each node | IdP + app VMs | 443/tcp (whatever the apps use) | The system under test, through firewall + VyOS |
| runner (mgmt) | VyOS API, IdP, apps | 443/tcp | Readiness checks. **Optional**: each can be turned off in `checks:` |

The install scripts open the Grid ports in firewalld (4444 in the management zone,
4442-4443 in the workstation zone, and 5555 on each node **only from the hub's IP**).
They don't touch the kit's own firewall.

## Before you start: fill in this worksheet

| Item | Example | Yours |
|---|---|---|
| Hub, **management** address (runner uses it) | `hub.mgmt.kit.lab` / `10.10.0.20` | |
| Hub, **workstation** address (nodes use it) | `hub.ws.kit.lab` / `10.20.0.20` | |
| Hub NIC → firewalld zone (mgmt / workstation) | `internal` / `trusted` | |
| Node VMs + workstation IPs | `lap01 10.20.0.31`, `lap02 10.20.0.32` | |
| Browsers per node (`--max-sessions`) | `2` | |
| Internal dnf mirror, or build RPMs into the bundle? | Satellite | |

Slots in total = nodes × max-sessions. That number goes in `grid.expected_slots.firefox`
in your env file, and it's the most useful value for `-n` in pytest/CI.

## 1. Build the bundle (connected machine)

```sh
infra/bundle.sh
#   or, through an internal GitHub mirror:
ARTIFACT_MIRROR=https://artifactory.internal/github infra/bundle.sh
#   or, if the kit has no dnf mirror at all (run on a MINIMAL RHEL-family 9 box,
#   same release as the nodes, so dependency resolution matches):
infra/bundle.sh --with-rpms
```

This downloads the Selenium server jar and geckodriver, **refuses them unless the
SHA-256 matches `versions.env`**, and writes `dist/selenium-grid-bundle-<ver>.tar.gz`
plus a `.sha256` file. Copy both to the hub and every node, then:

```sh
sha256sum -c selenium-grid-bundle-4.49.0.tar.gz.sha256
tar -xzf selenium-grid-bundle-4.49.0.tar.gz      # creates ./infra
```

## 2. Hub VM

Put each NIC in the right firewalld zone first (connection names from `nmcli con show`):

```sh
sudo nmcli connection modify <mgmt-connection> connection.zone internal
sudo nmcli connection modify <ws-connection>   connection.zone trusted
sudo nmcli connection up <mgmt-connection>; sudo nmcli connection up <ws-connection>
```

Then install:

```sh
sudo infra/hub/install.sh --mgmt-zone internal --workstation-zone trusted
systemctl status selenium-hub
curl -s http://localhost:4444/status | python3 -m json.tool | head    # ready: false until a node joins
```

## 3. Each laptop-image VM (node)

```sh
sudo infra/node/install.sh \
    --hub      http://hub.ws.kit.lab:4444 \
    --grid-url http://hub.mgmt.kit.lab:4444 \
    --max-sessions 2
```

* `--hub` is the hub **as this VM sees it** (workstation address).
* `--grid-url` is the hub **as the runner sees it** (management address, same as
  `grid.hub_url` in the env file). Grid builds the BiDi websocket URL it hands to
  pytest from this. If it's wrong, sessions still work but browser console logs
  silently stop being captured. `verify.sh` warns about it.
* `--node-address` defaults to the VM's first IP. Set it if the VM has more than one.

The script adds Java, geckodriver 0.37.0 and the Selenium jar, plus a `selenium`
service account. It **doesn't change the laptop image's Firefox, policies or CA
trust**, because those are part of what's being tested. It prints the detected
Firefox version at the end.

The node service runs Firefox headless (a system service has no display). To watch
tests drive the browser, see [Watching the browser](#watching-the-browser).

## 4. Verify from the runner

```sh
infra/verify.sh --hub http://hub.mgmt.kit.lab:4444 --expect-slots 4 \
    --url https://app-one.kit.lab/
```

```
Grid at http://hub.mgmt.kit.lab:4444
         node UP   http://10.20.0.31:5555 (2 slots)
         node UP   http://10.20.0.32:5555 (2 slots)
  [PASS] hub ready: 2/2 nodes UP
  [PASS] firefox slots: 4 (0 busy), versions: 128.14.0esr
  [PASS] session 3f1c… started: firefox 128.14.0esr
  [PASS] BiDi websocket via hub: ws://hub.mgmt.kit.lab:4444
  [PASS] node browser loaded https://app-one.kit.lab/ -> https://auth.kit.lab/realms/… (title: Sign in)
All checks passed.
```

`--url` loads the page **in a node's Firefox**, so it tests the whole user path
(node → firewall → VyOS → app). The landing URL shows whether you were redirected to
the IdP. `make verify-grid HUB=… URL=… SLOTS=…` does the same thing.

### Which readiness checks can the runner do?

The harness's readiness checks are HTTP calls **from the runner**, not from the
browser. Find out what the management network can reach:

```sh
curl -sk -o /dev/null -w '%{http_code}\n' https://vyos.mgmt.kit.lab/retrieve    # VyOS API
curl -sk -o /dev/null -w '%{http_code}\n' https://auth.kit.lab/realms/harness/.well-known/openid-configuration
curl -sk -o /dev/null -w '%{http_code}\n' https://app-one.kit.lab/healthz
```

Any HTTP status (even 4xx) means reachable. `000` means unreachable: turn that group off in the env file's `checks:` section.
A disabled check shows as `[SKIP]` in the readiness summary, and a disabled VyOS
check no longer needs `HARNESS_VYOS_API_KEY`. The browser path to the apps is
still proven by the tests themselves, and by `verify.sh --url`.

## 5. Point the harness at it

In `env/virtual.yaml` (and `env/physical.yaml` for the real kit):

```yaml
grid:
  hub_url: http://hub.mgmt.kit.lab:4444      # the runner's view = --grid-url
  expected_slots:
    firefox: 4                               # nodes × max-sessions
browser:
  version: "128"                             # matches by prefix: "128" matches 128.14.0esr; "" = any
checks: { vyos: true, idp: true, apps: true } # from step 4
```

The hub rejects impossible requests immediately (`reject-unsupported-caps`). A wrong
`browser.version` fails fast with "No nodes support the capabilities in the request"
instead of hanging.

Then:

```sh
make grid ENV=env/virtual.yaml      # hub + slots
make health ENV=env/virtual.yaml    # all readiness checks
make smoke ENV=env/virtual.yaml
```

## 6. IdP test users (Keycloak)

The harness logs in with real users and real TOTP. For each user in `users:`
(`harness.standard`, `harness.admin` by default):

1. **Realm → Authentication → Policies → OTP Policy:** type TOTP, SHA1, 6 digits,
   30 s period (pyotp's defaults), and **Reusable token: ON**. Without that, parallel
   workers logging in as the same user within one 30 s window reject each other.
2. **Users → Add user**, set a password (not temporary), and add the required action
   *Configure OTP*.
3. Log in once as that user in a browser. On the QR-code page, click **"Unable to
   scan?"** and copy the secret: that's the base32 seed. Remove the spaces. Finish
   enrolment with a code from `python -c "import pyotp; print(pyotp.TOTP('SEED').now())"`.
4. Store it as `HARNESS_<USER>_TOTP_SEED` and the password as `HARNESS_<USER>_PASSWORD`
   (masked + protected CI/CD variables in GitLab, shell exports for local runs).

If brute-force detection is on, note that the negative login test uses a
**nonexistent** username, so it never locks out a real test account.

## 7. GitLab runner

On a VM on the management network: install `git`, Python 3.12 and `uv` (from your
mirrors), and register a **shell** executor with tag `harness`. Set
`UV_DEFAULT_INDEX` to your PyPI mirror and the `HARNESS_*` secrets as CI/CD
variables. `.gitlab-ci.yml` does the rest: `static-checks → reset → deploy → health →
smoke → regression → collect`.

## Development: a single laptop VM, no hub

For writing page objects against the kit, one laptop-image VM can be both Grid and
test runner:

```sh
sudo infra/node/install.sh --hub http://localhost:4444 --no-firewall   # Java, geckodriver, jar
sudo systemctl disable --now selenium-node                             # standalone replaces it
infra/standalone/run.sh                                                # from the desktop session
```

Then, in another terminal on the same VM, create a personal env file (`env/local*.yaml`
is git-ignored but still checked for identical keys):

```sh
cp env/virtual.yaml env/local-dev.yaml
# edit: grid.hub_url: http://localhost:4444, browser.headless: false, checks as reachable
uv run pytest --env=env/local-dev.yaml -m smoke
```

You'll watch Firefox run each test. Page-object locators that don't match the real
markup fail with a `PageNotReadyError` naming the locator. Fix them there.

## Watching the browser

On a node:

```sh
sudo systemctl stop selenium-node
infra/node/run-foreground.sh           # from the logged-in desktop session; Ctrl-C to stop
sudo systemctl start selenium-node
```

and set `browser.headless: false` in the env file. The Grid UI is at
`http://<hub>:4444/ui`. Each running session is labelled with its pytest test id.

## Operations

| Task | Command |
|---|---|
| Logs | `journalctl -u selenium-hub -f` / `journalctl -u selenium-node -f` |
| Restart | `sudo systemctl restart selenium-hub` (nodes re-register by themselves) |
| Node config | `/etc/selenium/node.toml`. Re-run `node/install.sh` to regenerate it. |
| Firefox updated on the image | Re-run `node/install.sh`. The stereotype records the Firefox version. |
| Upgrade Selenium | Bump `SELENIUM_VERSION` + `SELENIUM_JAR_SHA256` in `versions.env` **and** the `selenium==` pin in `pyproject.toml` (a unit test enforces they match), then re-bundle and re-run the installers. |

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Hub `ready: false`, no nodes listed | Node can't reach hub 4442/4443 | Check `--hub` address; firewalld workstation zone on the hub |
| Node listed, sessions fail with `Connection error (POST http://<node>:5555/...)` | Hub can't reach node 5555, or wrong `--node-address` | Re-run node install with the right `--node-address`; check the 5555 rule |
| `No nodes support the capabilities in the request` | `browser.version` doesn't match any node | Use the major version (`"128"`) or `""`. See versions in `verify.sh` output. |
| `[WARN] BiDi websocket … is not at …` | Node `--grid-url` isn't the runner's hub address | Re-run node install with `--grid-url http://<hub mgmt addr>:4444` |
| `node browser could not load …: about:neterror?e=connectionFailure` | Workstation network → app path: firewall, VyOS routing or DNS | Fix the kit's network. That's a real finding. |
| `… e=nssFailure2` / certificate errors in the node browser | Laptop image doesn't trust the kit's CA | Install the CA on the laptop image (as for real users) |
| Readiness check `ConnectError` from the runner, but `verify.sh --url` works | Management network can't reach that target | Turn it off under `checks:` |
| Node starts then dies; `journalctl` shows SELinux AVCs | Custom paths | `sudo ausearch -m avc -ts recent`; the scripts use standard paths, so report it |

## How this was tested

In a sandbox, with Docker standing in for VMs:

* **Hub:** `hub/install.sh`, and the hub started with the unit's exact `ExecStart`
  line as the `selenium` user.
* **Node:** `node/install.sh`, and the node started the same way, using the pinned
  jar and geckodriver.
* **Checks:** `verify.sh` scenarios, plus the full harness suite through that Grid
  (26 pass, BiDi console capture working through `grid-url`).

What wasn't exercised: dnf package installs (the sandbox can't reach any RPM repo),
real systemd, and firewalld rules (both were stubbed). Expect to verify those on the
first real VM. `bundle.sh --with-rpms` is untested for the same reason.
