#!/usr/bin/env bash
# Shared helpers for the infra scripts. Source it; don't run it.
set -euo pipefail

INFRA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=../versions.env
source "${INFRA_DIR}/versions.env"
ARTIFACT_DIR="${INFRA_DIR}/artifacts"
JAR_NAME="selenium-server-${SELENIUM_VERSION}.jar"
GECKO_TARBALL="geckodriver-v${GECKODRIVER_VERSION}-linux64.tar.gz"

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mWARN:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

require_root() {
    [[ ${EUID} -eq 0 ]] || die "run as root (sudo $0 ...)"
}

require_rhel_like() {
    [[ -r /etc/os-release ]] || die "/etc/os-release missing; expected RHEL/Rocky/Alma"
    # shellcheck disable=SC1091
    source /etc/os-release
    case " ${ID:-} ${ID_LIKE:-} " in
        *" rhel "*|*" fedora "*|*" centos "*) ;;
        *) die "unsupported OS '${PRETTY_NAME:-unknown}'; these scripts target RHEL-family (dnf)" ;;
    esac
}

# verify_sha256 FILE EXPECTED
verify_sha256() {
    local actual
    actual="$(sha256sum "$1" | awk '{print $1}')"
    [[ "${actual}" == "$2" ]] || die "checksum mismatch for $1
  expected ${2}
  actual   ${actual}"
}

# require_artifacts: the jar (and geckodriver, if $1 == node) must be staged in artifacts/.
require_artifacts() {
    [[ -f "${ARTIFACT_DIR}/${JAR_NAME}" ]] \
        || die "missing ${ARTIFACT_DIR}/${JAR_NAME}; run infra/bundle.sh on a connected machine first"
    verify_sha256 "${ARTIFACT_DIR}/${JAR_NAME}" "${SELENIUM_JAR_SHA256}"
    if [[ "${1:-}" == "node" ]]; then
        [[ -f "${ARTIFACT_DIR}/${GECKO_TARBALL}" ]] || die "missing ${ARTIFACT_DIR}/${GECKO_TARBALL}"
        verify_sha256 "${ARTIFACT_DIR}/${GECKO_TARBALL}" "${GECKODRIVER_SHA256}"
    fi
}

# install_packages PKG...: from the bundle's rpms/ if present (fully offline), else dnf repos.
install_packages() {
    if compgen -G "${INFRA_DIR}/rpms/*.rpm" >/dev/null; then
        log "Installing $* from bundled RPMs (offline)"
        dnf install -y --disablerepo='*' "${INFRA_DIR}"/rpms/*.rpm
    else
        log "Installing $* from configured dnf repositories"
        dnf install -y "$@"
    fi
}

ensure_user() {
    if ! id -u "${SELENIUM_USER}" >/dev/null 2>&1; then
        log "Creating system user ${SELENIUM_USER}"
        useradd --system --create-home --home-dir "/var/lib/${SELENIUM_USER}" \
            --shell /sbin/nologin "${SELENIUM_USER}"
    fi
}

install_jar() {
    install -d -m 0755 "${SELENIUM_HOME}" "${SELENIUM_CONF}"
    install -m 0644 "${ARTIFACT_DIR}/${JAR_NAME}" "${SELENIUM_HOME}/${JAR_NAME}"
    ln -sfn "${SELENIUM_HOME}/${JAR_NAME}" "${SELENIUM_HOME}/selenium-server.jar"
    log "Installed ${SELENIUM_HOME}/${JAR_NAME}"
}

# render TEMPLATE DEST KEY=VALUE...: replace @KEY@ placeholders; fail on any left over.
render() {
    local template="$1" dest="$2" content
    shift 2
    content="$(<"${template}")"
    local pair key value
    for pair in "$@"; do
        key="${pair%%=*}"
        value="${pair#*=}"
        content="${content//@${key}@/${value}}"
    done
    if grep -q '@[A-Z_]\+@' <<<"${content}"; then
        die "unfilled placeholders in ${template}: $(grep -o '@[A-Z_]\+@' <<<"${content}" | sort -u | tr '\n' ' ')"
    fi
    printf '%s\n' "${content}" >"${dest}"
}

# open_ports ZONE PORT...: open TCP ports in a firewalld zone (no-op without firewalld).
open_ports() {
    local zone="$1"
    shift
    if ! systemctl is-active --quiet firewalld; then
        warn "firewalld not running; open TCP $* yourself"
        return
    fi
    local port
    for port in "$@"; do
        firewall-cmd --permanent --zone="${zone}" --add-port="${port}/tcp" >/dev/null
    done
    firewall-cmd --reload >/dev/null
    log "firewalld zone ${zone}: opened TCP $*"
}

# allow_from ZONE SOURCE PORT: open PORT only for SOURCE (IP/CIDR) via a rich rule.
allow_from() {
    local zone="$1" source="$2" port="$3"
    if ! systemctl is-active --quiet firewalld; then
        warn "firewalld not running; allow TCP ${port} from ${source} yourself"
        return
    fi
    firewall-cmd --permanent --zone="${zone}" --add-rich-rule \
        "rule family=\"ipv4\" source address=\"${source}\" port port=\"${port}\" protocol=\"tcp\" accept" \
        >/dev/null
    firewall-cmd --reload >/dev/null
    log "firewalld zone ${zone}: TCP ${port} allowed from ${source} only"
}

primary_ip() {
    hostname -I 2>/dev/null | awk '{print $1}'
}
