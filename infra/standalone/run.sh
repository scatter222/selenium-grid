#!/usr/bin/env bash
# Development only: run a standalone Grid (hub + node in one process) in the
# foreground on a laptop-image VM, as your own user. Run pytest on the same VM with
# grid.hub_url: http://localhost:4444. Run it from the desktop session to watch
# Firefox, or add --headless.
#
#   infra/standalone/run.sh [--max-sessions 2] [--headless]
#
# Needs Java, Firefox and geckodriver. Install them with:
#   sudo infra/node/install.sh --hub http://localhost:4444 --no-firewall
#   sudo systemctl disable --now selenium-node    # standalone replaces the node service
# shellcheck source=../lib/common.sh
source "$(dirname "$0")/../lib/common.sh"

MAX_SESSIONS=2
while [[ $# -gt 0 ]]; do
    case "$1" in
        --max-sessions) MAX_SESSIONS="$2"; shift 2 ;;
        --headless) export MOZ_HEADLESS=1; shift ;;
        -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
        *) die "unknown argument: $1" ;;
    esac
done

[[ ${EUID} -ne 0 ]] || die "run as your desktop user, not root (Firefox refuses to run as root)"
command -v java >/dev/null || die "java not found (sudo dnf install ${JAVA_PACKAGE})"
command -v firefox >/dev/null || die "firefox not found"
[[ -x "${GECKODRIVER_PATH}" ]] || die "no geckodriver at ${GECKODRIVER_PATH} (see --help)"
JAR="${SELENIUM_HOME}/selenium-server.jar"
[[ -f "${JAR}" ]] || JAR="${ARTIFACT_DIR}/${JAR_NAME}"
[[ -f "${JAR}" ]] || die "no Selenium jar; run infra/bundle.sh or infra/node/install.sh first"

FIREFOX_VERSION="$(firefox --version | awk '{print $NF}')"
conf="$(mktemp --suffix=.toml)"
trap 'rm -f "${conf}"' EXIT
render "${INFRA_DIR}/standalone/standalone.toml.tmpl" "${conf}" \
    "HUB_PORT=${HUB_PORT}" \
    "MAX_SESSIONS=${MAX_SESSIONS}" \
    "FIREFOX_VERSION=${FIREFOX_VERSION}" \
    "GECKODRIVER_PATH=${GECKODRIVER_PATH}"

log "Standalone Grid on http://localhost:${HUB_PORT} (Firefox ${FIREFOX_VERSION}, ${MAX_SESSIONS} slots)"
export SE_OFFLINE=true
java -jar "${JAR}" standalone --config "${conf}"
