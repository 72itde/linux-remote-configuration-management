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

# SemVer says 1.0.0-rc.1 precedes 1.0.0; dpkg says the opposite, because '-'
# introduces the Debian revision and any revision sorts above none. '~' is the
# one character that sorts before the empty string (deb-version(7)), so a
# pre-release has to use it or every release candidate machine would refuse the
# final release as a downgrade.
DEB_VERSION="${VERSION/-/\~}"

# Single source of truth for the maintainer, shared by control and changelog.
MAINTAINER="$(sed -n 's/^Maintainer: //p' "${SCRIPT_DIR}/control.in")"
if [ -z "${MAINTAINER}" ]; then
    echo "error: no Maintainer field in control.in" >&2
    exit 1
fi

STAGING="$(mktemp -d)"
cleanup() { rm -rf "${STAGING}"; }
trap cleanup EXIT
# mktemp creates the directory 0700; that mode is recorded for "./" in the
# package, so give it the mode the filesystem root actually has.
chmod 0755 "${STAGING}"

echo "building lrcm ${VERSION} (deb version ${DEB_VERSION})"

# --- payload ---------------------------------------------------------------

install -d -m 0755 "${STAGING}/opt/lrcm/templates"
install -m 0755 "${REPO_ROOT}/lrcm.py" "${STAGING}/opt/lrcm/lrcm.py"
install -m 0644 "${REPO_ROOT}/templates/cronjob.yaml.j2" "${STAGING}/opt/lrcm/templates/"

# /etc/lrcm holds the git token once the administrator fills it in, so the
# directory itself is root-only. postinst re-applies this on every configure.
install -d -m 0700 "${STAGING}/etc/lrcm"

# The template is shipped under /usr/share, not /etc: a file in /etc that dpkg
# does not know as a conffile is a Policy 10.7 violation, and postinst copies
# this one into /etc/lrcm/lrcm.conf on first install anyway.
install -d -m 0755 "${STAGING}/usr/share/lrcm"
install -m 0644 "${REPO_ROOT}/lrcm.conf.template" "${STAGING}/usr/share/lrcm/lrcm.conf.template"

# convenience entry point, so `lrcm --help` works without knowing /opt
install -d -m 0755 "${STAGING}/usr/bin"
ln -s /opt/lrcm/lrcm.py "${STAGING}/usr/bin/lrcm"

install -d -m 0755 "${STAGING}/usr/share/man/man1"
gzip -9 -n -c "${SCRIPT_DIR}/lrcm.1" > "${STAGING}/usr/share/man/man1/lrcm.1.gz"
chmod 0644 "${STAGING}/usr/share/man/man1/lrcm.1.gz"

install -d -m 0755 "${STAGING}/usr/share/doc/lrcm"
install -m 0644 "${REPO_ROOT}/README.md" "${STAGING}/usr/share/doc/lrcm/"
install -m 0644 "${REPO_ROOT}/LICENSE" "${STAGING}/usr/share/doc/lrcm/copyright"

# Policy 12.7: for a native version, /usr/share/doc/<pkg>/changelog.gz must be
# a Debian-format changelog. CHANGELOG.md is markdown, so it ships beside it
# under its own name and this entry points at it.
# SOURCE_DATE_EPOCH keeps the build reproducible when the caller sets it.
if [ -n "${SOURCE_DATE_EPOCH:-}" ]; then
    BUILD_DATE="$(date -u -R -d "@${SOURCE_DATE_EPOCH}")"
else
    BUILD_DATE="$(date -R)"
fi
cat > "${STAGING}/changelog" <<EOF
lrcm (${DEB_VERSION}) stable; urgency=medium

  * Release ${VERSION}. See /usr/share/doc/lrcm/changelog.md.gz for the full
    list of changes, or CHANGELOG.md in the source repository.

 -- ${MAINTAINER}  ${BUILD_DATE}
EOF
gzip -9 -n -c "${STAGING}/changelog" > "${STAGING}/usr/share/doc/lrcm/changelog.gz"
rm -f "${STAGING}/changelog"
chmod 0644 "${STAGING}/usr/share/doc/lrcm/changelog.gz"

gzip -9 -n -c "${REPO_ROOT}/CHANGELOG.md" > "${STAGING}/usr/share/doc/lrcm/changelog.md.gz"
chmod 0644 "${STAGING}/usr/share/doc/lrcm/changelog.md.gz"

# Two lintian tags are deliberate; the file says why, and ships with the
# package so the reasoning travels with it.
install -d -m 0755 "${STAGING}/usr/share/lintian/overrides"
install -m 0644 "${SCRIPT_DIR}/lintian-overrides" "${STAGING}/usr/share/lintian/overrides/lrcm"

# --- control area ----------------------------------------------------------

install -d -m 0755 "${STAGING}/DEBIAN"

# Installed-Size is in KiB and covers the payload only, not the control area.
INSTALLED_SIZE="$(du -sk --exclude=DEBIAN "${STAGING}" | cut -f1)"

sed -e "s|@VERSION@|${DEB_VERSION}|g" \
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

PACKAGE="${OUTPUT_DIR}/lrcm_${DEB_VERSION}_all.deb"
rm -f "${PACKAGE}"
dpkg-deb --root-owner-group --build "${STAGING}" "${PACKAGE}" >/dev/null

echo "built ${PACKAGE}"
dpkg-deb --contents "${PACKAGE}"
