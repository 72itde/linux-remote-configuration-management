#!/usr/bin/env bash
#
# The version lives in three places that must never drift apart:
#   VERSION            - read by the package build
#   lrcm.py            - reported by `lrcm --version` on the client
#   CHANGELOG.md       - the release notes attached to the GitHub release

set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

version_file="$(tr -d '[:space:]' < "${REPO_ROOT}/VERSION")"
version_code="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "${REPO_ROOT}/lrcm.py")"
# awk rather than `sed | head`: under `set -o pipefail` head exiting early
# sends SIGPIPE to sed, which would abort the script with status 141.
# Kept to POSIX awk - Debian and Ubuntu default to mawk, which has no gawk
# extensions such as the three-argument match().
version_changelog="$(awk '/^## [0-9]/ { sub(/^## /, ""); print; exit }' \
    "${REPO_ROOT}/CHANGELOG.md")"

status=0

if [ "${version_file}" != "${version_code}" ]; then
    echo "error: VERSION is '${version_file}' but lrcm.py says '${version_code}'" >&2
    status=1
fi

if [ "${version_file}" != "${version_changelog}" ]; then
    echo "error: VERSION is '${version_file}' but the newest CHANGELOG.md entry is '${version_changelog}'" >&2
    status=1
fi

if [ "${status}" -eq 0 ]; then
    echo "version ${version_file} is consistent across VERSION, lrcm.py and CHANGELOG.md"
fi

exit "${status}"
