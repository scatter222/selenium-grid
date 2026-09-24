#!/usr/bin/env bash
# Build the offline Grid bundle on a machine WITH internet (or artifact-mirror) access.
#
#   infra/bundle.sh                 # jar + geckodriver, verified, into infra/artifacts/
#   infra/bundle.sh --with-rpms     # also download Java + Firefox RPMs with all deps
#                                   # (run on a MINIMAL box matching the nodes' OS release)
#   ARTIFACT_MIRROR=https://artifactory.internal/github infra/bundle.sh
#
# Produces dist/selenium-grid-bundle-<version>.tar.gz containing infra/ with artifacts
# staged. Copy it to the hub and nodes, extract, and run the install scripts.
# shellcheck source=lib/common.sh
source "$(dirname "$0")/lib/common.sh"

WITH_RPMS=false
for arg in "$@"; do
    case "${arg}" in
        --with-rpms) WITH_RPMS=true ;;
        -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
        *) die "unknown argument: ${arg}" ;;
    esac
done

GITHUB="${ARTIFACT_MIRROR:-https://github.com}"
JAR_URL="${GITHUB}/SeleniumHQ/selenium/releases/download/selenium-${SELENIUM_VERSION}/${JAR_NAME}"
GECKO_URL="${GITHUB}/mozilla/geckodriver/releases/download/v${GECKODRIVER_VERSION}/${GECKO_TARBALL}"

mkdir -p "${ARTIFACT_DIR}"

fetch() {  # fetch URL DEST SHA256
    if [[ -f "$2" ]] && [[ "$(sha256sum "$2" | awk '{print $1}')" == "$3" ]]; then
        log "Already have $(basename "$2")"
        return
    fi
    log "Downloading $1"
    curl --fail --location --silent --show-error --output "$2.part" "$1"
    mv "$2.part" "$2"
    verify_sha256 "$2" "$3"
}

fetch "${JAR_URL}" "${ARTIFACT_DIR}/${JAR_NAME}" "${SELENIUM_JAR_SHA256}"
fetch "${GECKO_URL}" "${ARTIFACT_DIR}/${GECKO_TARBALL}" "${GECKODRIVER_SHA256}"

if ${WITH_RPMS}; then
    command -v dnf >/dev/null || die "--with-rpms needs dnf (run on a RHEL-family box)"
    mkdir -p "${INFRA_DIR}/rpms"
    log "Downloading ${JAVA_PACKAGE} ${FIREFOX_PACKAGE} and dependencies"
    # --resolve only fetches deps missing on THIS box, so build on a minimal install
    # of the same OS release as the nodes.
    dnf download --resolve --destdir "${INFRA_DIR}/rpms" "${JAVA_PACKAGE}" "${FIREFOX_PACKAGE}"
fi

REPO_ROOT="$(cd "${INFRA_DIR}/.." && pwd)"
mkdir -p "${REPO_ROOT}/dist"
OUT="${REPO_ROOT}/dist/selenium-grid-bundle-${SELENIUM_VERSION}.tar.gz"
tar -C "${REPO_ROOT}" -czf "${OUT}" infra
log "Bundle ready: ${OUT}"
(cd "${REPO_ROOT}/dist" && sha256sum "$(basename "${OUT}")" > "$(basename "${OUT}").sha256")
log "Checksum:     ${OUT}.sha256"
