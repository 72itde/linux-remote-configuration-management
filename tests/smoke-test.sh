#!/usr/bin/env bash
#
# End-to-end test, executed inside a throwaway container of a supported
# distribution. Installs lrcm, then drives it against a local git repository so
# the test needs no network beyond the package mirror.
#
# Usage: smoke-test.sh <package|source>
#   package  install the built .deb   (Debian, Ubuntu and their rebuilds)
#   source   run straight from the checkout (Fedora - there is no .rpm yet)
#
# Expects the repository, including dist/ for the package mode, mounted at
# /workspace.

set -euo pipefail

MODE="${1:-}"
WORKSPACE="${WORKSPACE:-/workspace}"
MARKER=/tmp/lrcm-smoke-marker
HOST_MARKER=/tmp/lrcm-smoke-host-marker
TESTREPO=/tmp/lrcm-testrepo
CONFIG=/tmp/lrcm-smoke.conf
RUNLOG=/tmp/lrcm-run.log

log() { printf '\n=== %s\n' "$1"; }

fail() {
    printf 'SMOKE TEST FAILED: %s\n' "$1" >&2
    exit 1
}

case "${MODE}" in
    package | source) ;;
    *) fail "usage: smoke-test.sh <package|source>" ;;
esac

log "distribution under test (mode: ${MODE})"
cat /etc/os-release

# --- install ---------------------------------------------------------------

install_package() {
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    local package
    package="$(find "${WORKSPACE}/dist" -maxdepth 1 -name 'lrcm_*.deb' -print -quit)"
    [ -n "${package}" ] || fail "no .deb found in ${WORKSPACE}/dist"
    apt-get install -y -qq "${package}"

    log "verifying the installed layout"
    [ -x /opt/lrcm/lrcm.py ] || fail "/opt/lrcm/lrcm.py is missing or not executable"
    [ -f /opt/lrcm/templates/cronjob.yaml.j2 ] || fail "the cronjob template is missing"
    [ -L /usr/bin/lrcm ] || fail "/usr/bin/lrcm symlink is missing"
    [ -f /etc/lrcm/lrcm.conf ] || fail "postinst did not seed /etc/lrcm/lrcm.conf"
    [ -f /usr/share/lrcm/lrcm.conf.template ] || fail "the config template is missing"
    # Policy 10.7: nothing may sit in /etc that dpkg does not know as a conffile
    [ ! -e /etc/lrcm/lrcm.conf.template ] || fail "the template must not be in /etc"
    [ -f /usr/share/man/man1/lrcm.1.gz ] || fail "the manual page is missing"

    local mode
    mode="$(stat -c '%a %U:%G' /etc/lrcm/lrcm.conf)"
    [ "${mode}" = "600 root:root" ] || fail "/etc/lrcm/lrcm.conf is ${mode}, expected 600 root:root"

    LRCM=(lrcm)
    CLIENT_SETUP="${WORKSPACE}/client-setup/playbook-debian-family.yaml"
}

install_from_source() {
    # The package names lrcm's own documentation tells Fedora users to install.
    dnf install -y -q \
        python3 python3-GitPython python3-ansible-runner python3-jinja2 \
        python3-validators python3-distro ansible-core git cronie

    [ -x "${WORKSPACE}/lrcm.py" ] || fail "${WORKSPACE}/lrcm.py is not executable"
    LRCM=("${WORKSPACE}/lrcm.py")
    CLIENT_SETUP="${WORKSPACE}/client-setup/playbook-fedora.yaml"
}

log "installing lrcm"
if [ "${MODE}" = "package" ]; then
    install_package
else
    install_from_source
fi

log "lrcm --version"
"${LRCM[@]}" --version

# --- prepare a local playbook repository -----------------------------------

log "building a local test repository"
hostname_now="$(uname -n)"
mkdir -p "${TESTREPO}"
cat > "${TESTREPO}/playbook.yaml" <<EOF
---
- name: lrcm smoke test
  hosts: 127.0.0.1
  connection: local
  gather_facts: false
  tasks:
    - name: Create the smoke test marker
      ansible.builtin.copy:
        content: "lrcm smoke test ok\n"
        dest: ${MARKER}
        mode: "0644"
EOF

# exercises the host-specific playbook code path
cat > "${TESTREPO}/${hostname_now}-playbook.yaml" <<EOF
---
- name: lrcm host specific smoke test
  hosts: 127.0.0.1
  connection: local
  gather_facts: false
  tasks:
    - name: Create the host specific marker
      ansible.builtin.copy:
        content: "lrcm host specific playbook ok\n"
        dest: ${HOST_MARKER}
        mode: "0644"
EOF

# a decoy project/ directory: ansible-runner treats <private_data_dir>/project
# specially, and a repository containing one used to break playbook resolution
mkdir -p "${TESTREPO}/project"
echo decoy > "${TESTREPO}/project/README"

git -C "${TESTREPO}" init -q -b main
git -C "${TESTREPO}" -c user.email=ci@example.invalid -c user.name=ci add .
git -C "${TESTREPO}" -c user.email=ci@example.invalid -c user.name=ci commit -q -m "smoke test"

cat > "${CONFIG}" <<EOF
[GENERAL]
delay_before_start_seconds: 0
delay_before_start_random_max_seconds: 0
timeout_seconds: 600
[GIT]
repository: file://${TESTREPO}
branch: main
playbook: playbook.yaml
authentication_required: false
[CRONJOB]
reboot_cronjob: false
hourly_cronjob: true
daily_cronjob: false
[PIDFILE]
pidfile: /run/lrcm.pid
EOF
chmod 0600 "${CONFIG}"

# --- run -------------------------------------------------------------------

log "running lrcm end to end, cron management disabled"
"${LRCM[@]}" --configfile "${CONFIG}" --debug --no-cronjobs --no-delay 2>&1 | tee "${RUNLOG}"

# The tested python series must stay in step with what the distributions ship.
# A patch bump is deliberately not flagged - only a whole new minor series is,
# because that is the one that can actually break the agent.
if grep -q "is not one of the tested series" "${RUNLOG}"; then
    python_now="$(python3 -c 'import platform; print(platform.python_version())')"
    fail "python ${python_now} is a new minor series; add it to TESTED_PYTHON_VERSIONS in lrcm.py"
fi

# Every record must carry an RFC 3339 timestamp and a level.
if ! grep -qE '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}[+-][0-9]{2}:[0-9]{2} +(DEBUG|INFO|WARNING|ERROR) ' "${RUNLOG}"; then
    head -3 "${RUNLOG}" >&2
    fail "log lines are missing the RFC 3339 timestamp and level prefix"
fi
# Blank ansible passthrough records were pure noise; they must be gone.
if grep -qE '(DEBUG|INFO) +ansible \| *$' "${RUNLOG}"; then
    fail "empty ansible passthrough lines are being logged"
fi

[ -f "${MARKER}" ] || fail "the playbook did not run: ${MARKER} is missing"
[ -f "${HOST_MARKER}" ] || fail "the host-specific playbook did not run: ${HOST_MARKER} is missing"
[ ! -e /run/lrcm.pid ] || fail "the pidfile was left behind"

log "default verbosity must stay quiet"
rm -f "${MARKER}" "${HOST_MARKER}"
"${LRCM[@]}" --configfile "${CONFIG}" --no-cronjobs --no-delay > /tmp/lrcm-quiet.log 2>&1
[ -f "${MARKER}" ] || fail "the playbook did not run in quiet mode"
[ ! -s /tmp/lrcm-quiet.log ] || {
    cat /tmp/lrcm-quiet.log >&2
    fail "a successful default run must not print anything"
}

log "running lrcm with cron management enabled"
"${LRCM[@]}" --configfile "${CONFIG}" --verbose --no-delay
[ -f /etc/cron.d/lrcm_hourly ] || fail "/etc/cron.d/lrcm_hourly was not created"
[ ! -e /etc/cron.d/lrcm_daily ] || fail "/etc/cron.d/lrcm_daily should not exist"
[ ! -e /etc/cron.d/lrcm_reboot ] || fail "/etc/cron.d/lrcm_reboot should not exist"

cron_mode="$(stat -c '%a %U:%G' /etc/cron.d/lrcm_hourly)"
[ "${cron_mode}" = "600 root:root" ] || fail "/etc/cron.d/lrcm_hourly is ${cron_mode}, expected 600 root:root"
grep -q -- "--configfile=${CONFIG}" /etc/cron.d/lrcm_hourly || fail "the cron entry does not reference the config file"

log "disabling the cron entry again"
sed -i 's/^hourly_cronjob: true$/hourly_cronjob: false/' "${CONFIG}"
"${LRCM[@]}" --configfile "${CONFIG}" --verbose --no-delay
[ ! -e /etc/cron.d/lrcm_hourly ] || fail "/etc/cron.d/lrcm_hourly was not removed"

# --- the client preparation playbook this distribution ships ---------------

# --skip-tags service: a container has no running init system, so the systemd
# task cannot succeed here. Everything else - the module names resolving on
# this distribution, and every package existing - is exercised for real.
log "applying ${CLIENT_SETUP##*/}"
ansible-playbook -i 127.0.0.1, -c local --skip-tags service "${CLIENT_SETUP}"

# --- failure behaviour -----------------------------------------------------

log "a missing playbook must be reported as a failure"
sed -i 's/^playbook: playbook.yaml$/playbook: does-not-exist.yaml/' "${CONFIG}"
if "${LRCM[@]}" --configfile "${CONFIG}" --debug --no-cronjobs --no-delay; then
    fail "lrcm exited 0 although the playbook does not exist"
fi
[ ! -e /run/lrcm.pid ] || fail "the pidfile was left behind after a failure"

log "an unreadable config file must be reported as a failure"
if "${LRCM[@]}" --configfile /tmp/definitely-not-here.conf --no-delay; then
    fail "lrcm exited 0 although the config file does not exist"
fi

# --- removal ---------------------------------------------------------------

if [ "${MODE}" = "package" ]; then
    log "purging the package"
    apt-get purge -y -qq lrcm
    [ ! -e /opt/lrcm/lrcm.py ] || fail "/opt/lrcm/lrcm.py survived the purge"
    [ ! -e /etc/lrcm/lrcm.conf ] || fail "/etc/lrcm/lrcm.conf survived the purge"
    [ ! -e /etc/cron.d/lrcm_hourly ] || fail "a cron entry survived the purge"
fi

log "smoke test passed"
