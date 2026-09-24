#!/usr/bin/env bash
# Run this VM's node in the foreground, inside the logged-in DESKTOP session, so you
# can watch Firefox being driven (set browser.headless: false in your env file).
# Uses the same /etc/selenium/node.toml as the service; stop the service first:
#
#   sudo systemctl stop selenium-node
#   infra/node/run-foreground.sh          # Ctrl-C to stop
#   sudo systemctl start selenium-node    # back to headless service mode
# shellcheck source=../lib/common.sh
source "$(dirname "$0")/../lib/common.sh"

[[ -f "${SELENIUM_CONF}/node.toml" ]] || die "no ${SELENIUM_CONF}/node.toml; run infra/node/install.sh first"
[[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]] || die "no DISPLAY/WAYLAND_DISPLAY: run this from the desktop session"
if systemctl is-active --quiet selenium-node; then
    die "selenium-node.service is running; stop it first: sudo systemctl stop selenium-node"
fi
export SE_OFFLINE=true
unset MOZ_HEADLESS
exec java -jar "${SELENIUM_HOME}/selenium-server.jar" node --config "${SELENIUM_CONF}/node.toml"
