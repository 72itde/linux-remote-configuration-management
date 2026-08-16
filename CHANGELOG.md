# changelog

## 0.8.0

Added support for Debian 13, every Ubuntu 24.04 point release and Ubuntu 26.04,
reworked the agent along current best practices and automated the packaging.

### added

- Support for **Debian GNU/Linux 13 (trixie)** and **Ubuntu 26.04 LTS**.
- Support for **every Ubuntu 24.04 point release**. Distribution support is now
  matched on `distro.id()` plus the `major.minor` version instead of the exact
  pretty name, so `24.04`, `24.04.1` and `24.04.7` all match a single entry.
  Previously every point release had to be added by hand and clients broke on
  upgrade.
- Python **3.13.5** (Debian 13, LMDE 7) and **3.14.0** (Ubuntu 26.04) added to
  the tested versions. The check now requires 3.10 or newer and only *warns*
  about untested versions, so a patch level bump no longer stops a whole fleet.
- `--version`, `--verbose`, `--no-cronjobs`, `--no-delay` and `--syslog`
  command line options.
- Unit tests (`tests/`) and a container based end-to-end test that installs the
  built `.deb` on Debian 12/13 and Ubuntu 24.04/26.04 and drives lrcm through a
  full run, including cron entry creation and removal.
- GitHub Actions: `ci.yml` (ruff, mypy, pytest, ansible-lint production
  profile, yamllint, shellcheck, package build, install test on four
  distributions) and `release.yml`, which builds the `.deb`, generates
  `SHA256SUMS` and publishes a GitHub release when a `v*` tag is pushed.
- `LICENSE` (MIT), shipped as `/usr/share/doc/lrcm/copyright`.
- A `/usr/bin/lrcm` entry point.

### fixed

- The host-specific playbook was looked up as `<hostname>-<playbook>` but
  executed as `<playbook>-<hostname>`, so it never actually ran.
- The "playbook found" check tested the *directory* the playbook lives in, which
  always exists, so a missing playbook was only noticed by ansible.
- A failing playbook was ignored: `ansible-runner`'s status was logged but never
  inspected and lrcm always exited `0`. Failures now exit `2`.
- The authenticated repository url was built as `scheme://user:token@host/` +
  `/path`, producing a double slash, and username and token were not
  url-encoded, so any `@`, `/` or `#` in a token broke the clone.
- `delay_before_start_random_max_seconds: 0` crashed with a `ValueError` from
  `random.randrange(0, 0)`.
- The cron section was read twice: once with a fallback and once without, so a
  configuration file lacking `[CRONJOB]` raised `NoOptionError` instead of using
  the documented defaults.
- `manage_cronjob()` took a `state` argument it ignored and read the actual
  state from two globals assigned by the caller.
- The temporary work directory and the pidfile were left behind whenever a step
  raised, because there was no `try`/`finally`.
- `remove_pidfile_and_quit()` ended in `return true`, which would have raised
  `NameError`, and exited `0` when the playbook was missing.
- `gc.enable` was referenced without being called.
- The cron playbook template used the unqualified `file:` module and an
  unquoted `mode: 0600`, which YAML reads as decimal `384`.
- The package build script copied into `lrcm/opt/lrcm/templates/`, a directory
  that does not exist in a fresh clone; without `set -e` it carried on and
  produced a `.deb` without the cron template.
- The `.deb` contained the `.gitkeep` and `.gitignore` files of the committed
  package tree.
- `python3-jinja2` was missing from the package dependencies although the code
  imports it.
- `lrcm.conf` was committed although `.gitignore` lists it.
- A `%` in the git token raised `InterpolationSyntaxError`, because
  `ConfigParser` ran its default interpolation over the value.
- The cloned repository was used directly as ansible-runner's
  `private_data_dir`. A playbook repository that happened to contain a
  `project/` directory silently changed where ansible looked for playbooks, so
  the configured playbook was no longer found. The checkout now goes into
  `<private_data_dir>/project/`, which is the layout ansible-runner documents.
- A pidfile path without a directory component (`pidfile: lrcm.pid`) made the
  writability check test the empty string and abort every run.
- The `.deb` carried no `md5sums`, so `dpkg --verify` had nothing to check.
- The memory figure ignored the `ansible-playbook` child processes, which are
  what actually dominates the footprint.

### security

- The git token is no longer part of the repository url. It is passed to git
  through `GIT_ASKPASS`, so it no longer appears in the process list
  (`/proc/<pid>/cmdline` is world readable) nor in the cloned repository's
  `.git/config`.
- Git error messages are redacted before they are logged.
- The pidfile is opened with `O_NOFOLLOW` and locked with `flock`, which removes
  the check-then-write race, the symlink attack on the pidfile path and the risk
  of mistaking a recycled pid for a running instance.
- The configured playbook path is rejected if it is absolute or contains `..`.
- The repository url is validated and unsupported schemes such as `ext::` are
  rejected.
- Values rendered into the generated cron playbook are JSON-encoded, so a path
  containing `:`, `#` or `{{` cannot break out of the YAML document.
- `/etc/lrcm` is `0700 root:root` and `/etc/lrcm/lrcm.conf` is `0600 root:root`,
  re-applied by `postinst` on every upgrade.
- Removing the package now also removes the `/etc/cron.d/lrcm_*` entries it
  created, which previously kept firing against a deleted script.
- The playbook repository can no longer influence how ansible-runner itself is
  configured: it is checked out into `project/`, so an `env/` directory in the
  repository is no longer read as runner settings.
- New `timeout_seconds` option (default 3600) bounds a single git transfer and
  a single playbook run, so a hung git server cannot hold the lock forever.

### changed

- lrcm is **quiet by default**. Logging is configured on every run, not only in
  debug mode; use `-v` for the previous `INFO` output.
- `optparse` replaced by `argparse`. `--cronjobs=False` keeps working.
- The script is now organised in typed functions behind a `main()` entry point
  instead of top-level statements, which is what makes it testable.
- `python3-psutil` and the `ansible` boolean parser import are gone; the manual
  `del`/`gc.collect()` calls were removed.
- The package build moved from `build/debian12/` to `packaging/debian/` and
  assembles its staging tree in a temporary directory. `VERSION` is the single
  source of truth, checked against `lrcm.py` and `CHANGELOG.md` in CI.
- The three per-version client-setup playbooks were replaced by
  `playbook-debian-family.yaml` and `playbook-fedora.yaml`, both passing
  ansible-lint's production profile.
- The stale `[LOGGING]` section was removed from the configuration template; the
  code behind it was already deleted in 0.7.0.

## 0.6.0

- Add logging to (remote) Loki. Authentication has to be done via basic auth for now.

## 0.5.2

- Switch back from `SafeConfigParser` to `ConfigParser` because `SafeConfigParser` is deprecated in Python 3.12
- add LOGGING-section and url-parameter for Loki as logging target. I assume authentication is always mandatory and credentials are the same as for Gitlab

## 0.5.1

- remove config file, add demo-config-file

## 0.5

- Add new variable `delay_before_start_random_max_seconds` (default: 60) for a random delay.
- Implement functionality for variables `delay_before_start_seconds` and `delay_before_start_random_max_seconds`
- switch from `ConfigParser` to `SafeConfigParser`
- add defaults for `delay_before_start_seconds`, `delay_before_start_random_max_seconds`, `branch`, `playbook`, `authentication_required`, `reboot_cronjob`, `hourly_cronjob`, `daily_cronjob`, `pidfile` so no breaking changes to v0.4
- fix wrong version in package build
- add changelog file
