#!/usr/bin/env bash
#
# Build the lrcm .deb package.
#
# The staging tree is assembled from scratch in a temporary directory, so the
# resulting package can never pick up stray repository files (.gitkeep,
# .gitignore, __pycache__, a previously built .deb, ...).
#
# Usage: packaging/debian/build-deb.sh [output-directory]
#        default output directory: <repository root>/dist

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
OUTPUT_DIR="$(mkdir -p "${1:-${REPO_ROOT}/dist}" && cd -- "${1:-${REPO_ROOT}/dist}" && pwd)"

VERSION="$(tr -d '[:space:]' < "${REPO_ROOT}/VERSION")"
if [[ ! "${VERSION}" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.]+)?$ ]]; then
    echo "error: VERSION does not contain a valid version: '${VERSION}'" >&2
    exit 1
fi

STAGING="$(mktemp -d)"
cleanup() { rm -rf "${STAGING}"; }
trap cleanup EXIT
# mktemp creates the directory 0700; that mode is recorded for "./" in the
# package, so give it the mode the filesystem root actually has.
chmod 0755 "${STAGING}"

echo "building lrcm ${VERSION}"

# --- payload ---------------------------------------------------------------

install -d -m 0755 "${STAGING}/opt/lrcm/templates"
install -m 0755 "${REPO_ROOT}/lrcm.py" "${STAGING}/opt/lrcm/lrcm.py"
install -m 0644 "${REPO_ROOT}/templates/cronjob.yaml.j2" "${STAGING}/opt/lrcm/templates/"

# /etc/lrcm holds the git token once the administrator fills it in, so the
# directory itself is root-only. postinst re-applies this on every configure.
install -d -m 0700 "${STAGING}/etc/lrcm"
install -m 0600 "${REPO_ROOT}/lrcm.conf.template" "${STAGING}/etc/lrcm/lrcm.conf.template"

# convenience entry point, so `lrcm --help` works without knowing /opt
install -d -m 0755 "${STAGING}/usr/bin"
ln -s /opt/lrcm/lrcm.py "${STAGING}/usr/bin/lrcm"

install -d -m 0755 "${STAGING}/usr/share/doc/lrcm"
install -m 0644 "${REPO_ROOT}/README.md" "${STAGING}/usr/share/doc/lrcm/"
install -m 0644 "${REPO_ROOT}/LICENSE" "${STAGING}/usr/share/doc/lrcm/copyright"
gzip -9 -n -c "${REPO_ROOT}/CHANGELOG.md" > "${STAGING}/usr/share/doc/lrcm/changelog.gz"
chmod 0644 "${STAGING}/usr/share/doc/lrcm/changelog.gz"

# --- control area ----------------------------------------------------------

install -d -m 0755 "${STAGING}/DEBIAN"

# Installed-Size is in KiB and covers the payload only, not the control area.
INSTALLED_SIZE="$(du -sk --exclude=DEBIAN "${STAGING}" | cut -f1)"

sed -e "s|@VERSION@|${VERSION}|g" \
    -e "s|@INSTALLED_SIZE@|${INSTALLED_SIZE}|g" \
    "${SCRIPT_DIR}/control.in" > "${STAGING}/DEBIAN/control"
chmod 0644 "${STAGING}/DEBIAN/control"

install -m 0755 "${SCRIPT_DIR}/postinst" "${STAGING}/DEBIAN/postinst"
install -m 0755 "${SCRIPT_DIR}/postrm" "${STAGING}/DEBIAN/postrm"

# dpkg-deb does not generate md5sums; without it `dpkg --verify` and every
# integrity check on the client has nothing to work with. Symlinks are excluded,
# which is what dpkg itself does.
(
    cd "${STAGING}"
    find . -type f ! -path './DEBIAN/*' -printf '%P\0' \
        | sort -z \
        | xargs -0 --no-run-if-empty md5sum > DEBIAN/md5sums
)
chmod 0644 "${STAGING}/DEBIAN/md5sums"

# --- build -----------------------------------------------------------------

PACKAGE="${OUTPUT_DIR}/lrcm_${VERSION}_all.deb"
rm -f "${PACKAGE}"
dpkg-deb --root-owner-group --build "${STAGING}" "${PACKAGE}" >/dev/null

echo "built ${PACKAGE}"
dpkg-deb --contents "${PACKAGE}"
