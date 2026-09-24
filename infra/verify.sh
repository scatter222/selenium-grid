#!/usr/bin/env bash
# Check a Grid end to end, using only curl and python3 (works on the runner, hub or a node).
#
#   infra/verify.sh --hub http://hub.mgmt.kit.lab:4444 \
#       [--expect-slots 4] [--browser-version 128.14.0esr] [--url https://app-one.kit.lab/]
#
#  1. hub /status: ready, nodes UP, firefox slots (>= --expect-slots)
#  2. creates a real Firefox session through the hub (proves hub -> node -> geckodriver)
#  3. with --url, loads it IN THE NODE'S BROWSER and prints the landing URL and title,
#     which proves the node -> firewall -> VyOS -> app path
#  4. always deletes the session
# Exit 0 = all good, 1 = a check failed.
set -euo pipefail

HUB="" EXPECT=0 VERSION="" URL=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --hub) HUB="${2%/}"; shift 2 ;;
        --expect-slots) EXPECT="$2"; shift 2 ;;
        --browser-version) VERSION="$2"; shift 2 ;;
        --url) URL="$2"; shift 2 ;;
        -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done
[[ -n "${HUB}" ]] || { echo "--hub is required" >&2; exit 2; }

# Talk to the hub directly, never through an HTTP proxy from the environment.
CURL=(curl --fail-with-body --silent --show-error --noproxy '*')
json() { python3 -c "import json,sys; d=json.load(sys.stdin); $1"; }
ok()   { printf '  [PASS] %s\n' "$*"; }
bad()  { printf '  [FAIL] %s\n' "$*"; exit 1; }

echo "Grid at ${HUB}"
status="$("${CURL[@]}" --max-time 10 "${HUB}/status")" || bad "hub unreachable: ${HUB}/status"

summary="$(json '
v = d["value"]
nodes = v.get("nodes", [])
up = [n for n in nodes if n.get("availability") == "UP"]
slots = [s for n in up for s in n.get("slots", [])
         if s.get("stereotype", {}).get("browserName") == "firefox"]
busy = sum(1 for s in slots if s.get("session"))
versions = sorted({s["stereotype"].get("browserVersion", "?") for s in slots})
print(int(bool(v.get("ready"))), len(nodes), len(up), len(slots), busy, ",".join(versions) or "-")
for n in nodes:
    print("NODE", n.get("availability"), n.get("uri"), len(n.get("slots", [])))
' <<<"${status}")"
read -r ready nodes up slots busy versions <<<"$(head -1 <<<"${summary}")"
grep '^NODE' <<<"${summary}" | while read -r _ avail uri n; do
    printf '         node %-4s %s (%s slots)\n' "${avail}" "${uri}" "${n}"
done
[[ "${ready}" == 1 ]] || bad "hub reports not ready (no UP nodes?)"
ok "hub ready: ${up}/${nodes} nodes UP"
((slots >= EXPECT)) || bad "firefox slots: ${slots}, expected at least ${EXPECT}"
ok "firefox slots: ${slots} (${busy} busy), versions: ${versions}"

caps='{"browserName": "firefox", "platformName": "linux"'
[[ -n "${VERSION}" ]] && caps+=", \"browserVersion\": \"${VERSION}\""
caps+=', "webSocketUrl": true, "se:name": "infra/verify.sh"}'
if ! resp="$("${CURL[@]}" --max-time 180 -H 'Content-Type: application/json; charset=utf-8' \
    -d "{\"capabilities\": {\"alwaysMatch\": ${caps}}}" "${HUB}/session" 2>/dev/null)"; then
    bad "session creation failed: $(json 'print(d["value"].get("message","?").splitlines()[0][:300])' <<<"${resp}" 2>/dev/null || echo "${resp:-no response}")"
fi
sid="$(json 'print(d["value"]["sessionId"])' <<<"${resp}")"
trap '"${CURL[@]}" --max-time 30 -X DELETE "${HUB}/session/${sid}" >/dev/null || true' EXIT
ok "session ${sid} started: $(json 'c=d["value"]["capabilities"]; print(c["browserName"], c["browserVersion"])' <<<"${resp}")"

# BiDi (browser console capture) needs a websocket URL that points back at the hub
# address we used. Grid builds it from each node's grid-url (node.toml).
ws="$(json 'print(d["value"]["capabilities"].get("webSocketUrl") or "")' <<<"${resp}")"
hub_hostport="${HUB#*://}"
if [[ -z "${ws}" ]]; then
    printf '  [WARN] no BiDi websocket offered: console logs will not be captured\n'
elif [[ "${ws}" == "ws://${hub_hostport}/"* || "${ws}" == "wss://${hub_hostport}/"* ]]; then
    ok "BiDi websocket via hub: ${ws%%/session*}"
else
    printf '  [WARN] BiDi websocket %s is not at %s: re-run node install with --grid-url http://%s\n' "${ws}" "${hub_hostport}" "${hub_hostport}"
fi

if [[ -n "${URL}" ]]; then
    if ! nav="$("${CURL[@]}" --max-time 120 -H 'Content-Type: application/json; charset=utf-8' \
        -d "{\"url\": \"${URL}\"}" "${HUB}/session/${sid}/url" 2>/dev/null)"; then
        bad "node browser could not load ${URL}: $(json 'print(d["value"].get("message","?").splitlines()[0][:300])' <<<"${nav}" 2>/dev/null || echo "${nav}")"
    fi
    landed="$("${CURL[@]}" "${HUB}/session/${sid}/url" | json 'print(d["value"])')"
    title="$("${CURL[@]}" "${HUB}/session/${sid}/title" | json 'print(d["value"])')"
    ok "node browser loaded ${URL} -> ${landed} (title: ${title:-<none>})"
fi
echo "All checks passed."
