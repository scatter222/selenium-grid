#!/usr/bin/env bash
# Install the Selenium Grid hub on the dual-homed hub VM (RHEL/Rocky/Alma). Idempotent.
#
#   sudo infra/hub/install.sh [--mgmt-zone internal] [--workstation-zone trusted] [--no-firewall]
#
#   --mgmt-zone         firewalld zone of the management NIC; opens hub port 4444.
#   --workstation-zone  firewalld zone of the workstation NIC; opens event bus 4442-4443.
#   --no-firewall       don't touch firewalld.
# shellcheck source=../lib/common.sh
source "$(dirname "$0")/../lib/common.sh"

MGMT_ZONE="public"
WS_ZONE="public"
FIREWALL=true
while [[ $# -gt 0 ]]; do
    case "$1" in
        --mgmt-zone) MGMT_ZONE="$2"; shift 2 ;;
        --workstation-zone) WS_ZONE="$2"; shift 2 ;;
        --no-firewall) FIREWALL=false; shift ;;
        -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
        *) die "unknown argument: $1" ;;
    esac
done

require_root
require_rhel_like
require_artifacts hub

install_packages "${JAVA_PACKAGE}"
ensure_user
install_jar

render "${INFRA_DIR}/hub/hub.toml.tmpl" "${SELENIUM_CONF}/hub.toml" \
    "HUB_PORT=${HUB_PORT}" \
    "EVENT_BUS_PUBLISH_PORT=${EVENT_BUS_PUBLISH_PORT}" \
    "EVENT_BUS_SUBSCRIBE_PORT=${EVENT_BUS_SUBSCRIBE_PORT}"
log "Wrote ${SELENIUM_CONF}/hub.toml"

install -m 0644 "${INFRA_DIR}/hub/selenium-hub.service" /etc/systemd/system/selenium-hub.service
systemctl daemon-reload
systemctl enable selenium-hub.service >/dev/null
systemctl restart selenium-hub.service
log "selenium-hub.service enabled and (re)started"

if ${FIREWALL}; then
    open_ports "${MGMT_ZONE}" "${HUB_PORT}"
    open_ports "${WS_ZONE}" "${EVENT_BUS_PUBLISH_PORT}" "${EVENT_BUS_SUBSCRIBE_PORT}"
fi

log "Done. Join nodes with:"
log "  sudo infra/node/install.sh --hub http://<hub workstation addr>:${HUB_PORT} --grid-url http://<hub mgmt addr>:${HUB_PORT}"
log "Then from the runner:  infra/verify.sh --hub http://<hub mgmt addr>:${HUB_PORT}"
