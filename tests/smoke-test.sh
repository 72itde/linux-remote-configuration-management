#!/usr/bin/env bash
#
# End-to-end test of the built .deb, executed inside a throwaway container of a
# supported distribution. Installs the package, then drives lrcm against a
# local git repository so the test needs no network beyond the package mirror.
#
# Expects the repository (including dist/) mounted at /workspace.

set -euo pipefail

WORKSPACE="${WORKSPACE:-/workspace}"
MARKER=/tmp/lrcm-smoke-marker
HOST_MARKER=/tmp/lrcm-smoke-host-marker
TESTREPO=/tmp/lrcm-testrepo
CONFIG=/tmp/lrcm-smoke.conf

log() { printf '\n=== %s\n' "$1"; }

fail() {
    printf 'SMOKE TEST FAILED: %s\n' "$1" >&2
    exit 1
}

# --- install ---------------------------------------------------------------

log "distribution under test"
cat /etc/os-release

log "installing the package"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
package="$(find "${WORKSPACE}/dist" -maxdepth 1 -name 'lrcm_*.deb' -print -quit)"
[ -n "${package}" ] || fail "no .deb found in ${WORKSPACE}/dist"
apt-get install -y -qq "${package}"

log "verifying the installed layout"
[ -x /opt/lrcm/lrcm.py ] || fail "/opt/lrcm/lrcm.py is missing or not executable"
[ -f /opt/lrcm/templates/cronjob.yaml.j2 ] || fail "the cronjob template is missing"
[ -L /usr/bin/lrcm ] || fail "/usr/bin/lrcm symlink is missing"
[ -f /etc/lrcm/lrcm.conf ] || fail "postinst did not seed /etc/lrcm/lrcm.conf"

config_mode="$(stat -c '%a %U:%G' /etc/lrcm/lrcm.conf)"
[ "${config_mode}" = "600 root:root" ] || fail "/etc/lrcm/lrcm.conf is ${config_mode}, expected 600 root:root"

log "lrcm --version"
lrcm --version

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

git -C "${TESTREPO}" init -q -b main
git -C "${TESTREPO}" -c user.email=ci@example.invalid -c user.name=ci add .
git -C "${TESTREPO}" -c user.email=ci@example.invalid -c user.name=ci commit -q -m "smoke test"

cat > "${CONFIG}" <<EOF
[GENERAL]
delay_before_start_seconds: 0
delay_before_start_random_max_seconds: 0
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
lrcm --configfile "${CONFIG}" --debug --no-cronjobs --no-delay | tee /tmp/lrcm-run.log
# The tested python series must stay in step with what the distributions ship.
# A patch bump is deliberately not flagged - only a whole new minor series is,
# because that is the one that can actually break the agent.
if grep -q "is not one of the tested series" /tmp/lrcm-run.log; then
    python_now="$(python3 -c 'import platform; print(platform.python_version())')"
    fail "python ${python_now} is a new minor series; add it to TESTED_PYTHON_VERSIONS in lrcm.py"
fi
[ -f "${MARKER}" ] || fail "the playbook did not run: ${MARKER} is missing"
[ -f "${HOST_MARKER}" ] || fail "the host-specific playbook did not run: ${HOST_MARKER} is missing"
[ ! -e /run/lrcm.pid ] || fail "the pidfile was left behind"

log "running lrcm with cron management enabled"
lrcm --configfile "${CONFIG}" --debug --no-delay
[ -f /etc/cron.d/lrcm_hourly ] || fail "/etc/cron.d/lrcm_hourly was not created"
[ ! -e /etc/cron.d/lrcm_daily ] || fail "/etc/cron.d/lrcm_daily should not exist"
[ ! -e /etc/cron.d/lrcm_reboot ] || fail "/etc/cron.d/lrcm_reboot should not exist"

cron_mode="$(stat -c '%a %U:%G' /etc/cron.d/lrcm_hourly)"
[ "${cron_mode}" = "600 root:root" ] || fail "/etc/cron.d/lrcm_hourly is ${cron_mode}, expected 600 root:root"
grep -q -- "--configfile=${CONFIG}" /etc/cron.d/lrcm_hourly || fail "the cron entry does not reference the config file"

log "disabling the cron entry again"
sed -i 's/^hourly_cronjob: true$/hourly_cronjob: false/' "${CONFIG}"
lrcm --configfile "${CONFIG}" --debug --no-delay
[ ! -e /etc/cron.d/lrcm_hourly ] || fail "/etc/cron.d/lrcm_hourly was not removed"

# --- failure behaviour -----------------------------------------------------

log "a missing playbook must be reported as a failure"
sed -i 's/^playbook: playbook.yaml$/playbook: does-not-exist.yaml/' "${CONFIG}"
if lrcm --configfile "${CONFIG}" --debug --no-cronjobs --no-delay; then
    fail "lrcm exited 0 although the playbook does not exist"
fi
[ ! -e /run/lrcm.pid ] || fail "the pidfile was left behind after a failure"

log "an unreadable config file must be reported as a failure"
if lrcm --configfile /tmp/definitely-not-here.conf --no-delay; then
    fail "lrcm exited 0 although the config file does not exist"
fi

# --- removal ---------------------------------------------------------------

log "purging the package"
lrcm --configfile /etc/lrcm/lrcm.conf --version >/dev/null
apt-get purge -y -qq lrcm
[ ! -e /opt/lrcm/lrcm.py ] || fail "/opt/lrcm/lrcm.py survived the purge"
[ ! -e /etc/lrcm/lrcm.conf ] || fail "/etc/lrcm/lrcm.conf survived the purge"
[ ! -e /etc/cron.d/lrcm_hourly ] || fail "a cron entry survived the purge"

log "smoke test passed"
