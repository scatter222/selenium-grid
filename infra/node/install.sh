#!/usr/bin/env bash
# Turn a laptop-image VM (RHEL/Rocky/Alma) into a Selenium Grid node. Idempotent.
#
#   sudo infra/node/install.sh --hub http://hub.ws.kit.lab:4444 \
#       --grid-url http://hub.mgmt.kit.lab:4444 \
#       [--node-address 10.20.0.31] [--max-sessions 2] [--zone public] [--no-firewall]
#
#   --hub           hub URL as THIS VM sees it (workstation network). Required.
#   --grid-url      hub URL as the RUNNER sees it (management network) = grid.hub_url
#                   in env/*.yaml. Used for the BiDi websocket (console capture).
#                   Default: same as --hub (only right if both networks use one name).
#   --node-address  this VM's workstation IP, which the hub connects back to on 5555.
#                   Default: first address from `hostname -I`.
#   --max-sessions  concurrent browsers on this VM (default 2). Sum across nodes =
#                   grid.expected_slots.firefox in env/*.yaml.
#   --zone          firewalld zone of the workstation NIC (default public).
#   --no-firewall   don't touch firewalld.
#
# The laptop image's own Firefox, policies and CA trust are left alone: they are part
# of what's being tested. Only Java, geckodriver, the Selenium jar and a service
# account are added.
# shellcheck source=../lib/common.sh
source "$(dirname "$0")/../lib/common.sh"

HUB_URL=""
GRID_URL=""
NODE_ADDRESS=""
MAX_SESSIONS=2
ZONE="public"
FIREWALL=true
while [[ $# -gt 0 ]]; do
    case "$1" in
        --hub) HUB_URL="${2%/}"; shift 2 ;;
        --grid-url) GRID_URL="${2%/}"; shift 2 ;;
        --node-address) NODE_ADDRESS="$2"; shift 2 ;;
        --max-sessions) MAX_SESSIONS="$2"; shift 2 ;;
        --zone) ZONE="$2"; shift 2 ;;
        --no-firewall) FIREWALL=false; shift ;;
        -h|--help) sed -n '2,21p' "$0"; exit 0 ;;
        *) die "unknown argument: $1" ;;
    esac
done
[[ "${HUB_URL}" =~ ^https?://[^/]+$ ]] || die "--hub must look like http://host:4444 (see --help)"
if [[ -z "${GRID_URL}" ]]; then
    GRID_URL="${HUB_URL}"
    warn "--grid-url not given; using ${HUB_URL}. If the runner reaches the hub at a"
    warn "different (management) address, re-run with --grid-url or BiDi capture breaks."
fi
[[ "${GRID_URL}" =~ ^https?://[^/]+$ ]] || die "--grid-url must look like http://host:4444"
[[ "${MAX_SESSIONS}" =~ ^[1-9][0-9]*$ ]] || die "--max-sessions must be a positive integer"
NODE_ADDRESS="${NODE_ADDRESS:-$(primary_ip)}"
[[ -n "${NODE_ADDRESS}" ]] || die "could not detect this VM's address; pass --node-address"

require_root
require_rhel_like
require_artifacts node

if command -v firefox >/dev/null; then
    log "Using the laptop image's Firefox: $(firefox --version 2>/dev/null)"
    install_packages "${JAVA_PACKAGE}"
else
    warn "Firefox not found: installing ${FIREFOX_PACKAGE}. Is this really the laptop image?"
    install_packages "${JAVA_PACKAGE}" "${FIREFOX_PACKAGE}"
fi
FIREFOX_VERSION="$(firefox --version 2>/dev/null | awk '{print $NF}')"
[[ -n "${FIREFOX_VERSION}" ]] || die "could not read the Firefox version"

log "Installing geckodriver ${GECKODRIVER_VERSION} to ${GECKODRIVER_PATH}"
tmp="$(mktemp -d)"
trap 'rm -rf "${tmp}"' EXIT
tar -xzf "${ARTIFACT_DIR}/${GECKO_TARBALL}" -C "${tmp}" geckodriver
install -m 0755 "${tmp}/geckodriver" "${GECKODRIVER_PATH}"
restorecon "${GECKODRIVER_PATH}" 2>/dev/null || true

ensure_user
install_jar

render "${INFRA_DIR}/node/node.toml.tmpl" "${SELENIUM_CONF}/node.toml" \
    "NODE_PORT=${NODE_PORT}" \
    "NODE_ADDRESS=${NODE_ADDRESS}" \
    "HUB_URL=${HUB_URL}" \
    "GRID_URL=${GRID_URL}" \
    "MAX_SESSIONS=${MAX_SESSIONS}" \
    "FIREFOX_VERSION=${FIREFOX_VERSION}" \
    "GECKODRIVER_PATH=${GECKODRIVER_PATH}"
log "Wrote ${SELENIUM_CONF}/node.toml (Firefox ${FIREFOX_VERSION}, ${MAX_SESSIONS} slots)"

install -m 0644 "${INFRA_DIR}/node/selenium-node.service" /etc/systemd/system/selenium-node.service
systemctl daemon-reload
systemctl enable selenium-node.service >/dev/null
systemctl restart selenium-node.service
log "selenium-node.service enabled and (re)started"

if ${FIREWALL}; then
    hub_host="$(sed -E 's#^https?://([^:/]+).*#\1#' <<<"${HUB_URL}")"
    hub_ip="$(getent ahostsv4 "${hub_host}" | awk 'NR==1{print $1}')"
    if [[ -n "${hub_ip}" ]]; then
        allow_from "${ZONE}" "${hub_ip}" "${NODE_PORT}"
    else
        warn "could not resolve ${hub_host}; opening ${NODE_PORT} to the whole zone"
        open_ports "${ZONE}" "${NODE_PORT}"
    fi
fi

log "Done. In env/*.yaml set browser.version to \"${FIREFOX_VERSION}\" (or \"\" for any)."
log "Check from the runner:  infra/verify.sh --hub ${GRID_URL}"
