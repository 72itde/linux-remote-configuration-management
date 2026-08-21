# changelog

## 0.9.0

Reworked logging, and widened the supported platforms to every current Debian,
Ubuntu and Fedora release - each one actually exercised in CI.

### added

- **Ubuntu 22.04 LTS**, **Fedora 43** and **Fedora 44** are now supported, and
  Linux Mint's 22 series (22, 22.1, 22.2, 22.3, …) matches as a whole.
- Fedora is verified in CI by running lrcm straight from the checkout, since
  there is no `.rpm` yet. The CI matrix now covers seven containers: Debian
  12/13, Ubuntu 22.04/24.04/26.04 from the built `.deb`, plus Fedora 43/44 from
  source.
- Each supported distribution records either the container image CI proves it
  in, or the distribution it is a rebuild of. A unit test fails if that table
  ever disagrees with `.github/workflows/ci.yml`, so the support claim cannot
  drift away from what is actually tested.
- CI now also applies the matching `client-setup/` playbook inside every
  container, so those playbooks are verified rather than merely linted.
- Python 3.14.6 (Fedora) added to the tested versions.

### changed

- **Log records now carry a date and time.** The format is RFC 3339 with the
  local UTC offset and milliseconds - `2026-08-16T09:12:34.567+02:00` - because
  `logging`'s own `%(asctime)s` emits neither the `T` separator nor any
  timezone, and lines from machines in different timezones cannot be ordered
  without one. Level names are padded so messages line up.
- **Diagnostics moved from stdout to stderr**, which is where the Unix
  convention and `logging`'s own default put them. lrcm writes nothing to
  stdout. Anything redirecting `lrcm >file` should redirect `2>` instead.
- **Ansible's output is now logged at debug level**, one record per line, with
  blank separator lines dropped. It previously came out at info level, so `-v`
  drowned lrcm's own progress in ansible chatter and printed timestamped empty
  records - and it contradicted `--debug`'s documented "including ansible
  output".
- `--syslog` now uses the `daemon` facility and deliberately omits the
  timestamp, since syslog and journald add their own.
- `configure_logging()` clears existing handlers, so calling it twice no longer
  duplicates every line.
- The "distribution is supported" message says how that support was verified
  instead of repeating the distribution name twice.
- The Fedora client-setup playbook uses `ansible.builtin.dnf5`. Fedora 41 and
  later ship dnf5, whose bindings are installed by default, while
  `ansible.builtin.dnf` needs the dnf4 bindings such a system no longer has.

### fixed

- **The generated cron command was never shell-quoted.** `--configfile` is
  operator-supplied and lands verbatim in `/etc/cron.d/lrcm_*`, which cron
  hands to `/bin/sh`; a config path containing a space installed a permanently
  broken root cron entry, and one containing `;` appended a second command.
  Both paths now go through `shlex.quote`.
- **A pre-release version sorted above the final release.** SemVer says
  `1.0.0-rc.1` precedes `1.0.0`; dpkg said the opposite, because `-` starts the
  Debian revision. The build now converts it to `1.0.0~rc.1`, which sorts
  correctly, so release-candidate machines will accept the final release
  instead of treating it as a downgrade. The release workflow's pre-release
  detection also matched only `-rc`, so `-beta` or `-alpha` tags were published
  as stable.
- An unexpected exception exited with status 1, which this program documents as
  "configuration error", and bypassed logging entirely. It is now reported as a
  runtime failure through the logger.
- The random start delay could never reach the configured maximum, because
  `randrange` excludes its upper bound while the option is documented as
  `0..n`.
- `tests/check-version-consistency.sh` piped `sed` into `head` under
  `set -o pipefail`, which can abort on SIGPIPE, and is now portable POSIX awk
  rather than relying on gawk extensions.

### security

- A redacting log filter now strips the git token from every record, installed
  on the handlers rather than at each call site. A handler-level filter sees
  everything that reaches the sink, which a logger-level one does not. This
  closes the sink no call site covered: the playbook output passed through from
  ansible.
- The syslog handler is capped at info level, so `--debug --syslog` no longer
  pushes every line of ansible output into the system log.

### packaging

- The `.deb` now passes `lintian --fail-on error,warning`, and CI enforces it.
  Two tags are overridden with written justification: `dir-or-file-in-opt`
  (FHS 3.0 §3.13 reserves `/opt` for exactly this kind of add-on package;
  Debian Policy forbids it only for packages *in the archive*) and the `0700`
  mode on `/etc/lrcm`, which is deliberate because the directory holds a token.
- `/usr/share/doc/lrcm/changelog.gz` is a proper Debian-format changelog as
  Policy 12.7 requires; the markdown one ships beside it as `changelog.md.gz`.
- Added a manual page, `lrcm(1)`, which Policy 12.1 expects for a program in
  `/usr/bin`.
- The configuration template moved from `/etc/lrcm/lrcm.conf.template` to
  `/usr/share/lrcm/lrcm.conf.template`. A file in `/etc` that dpkg does not
  know as a conffile violates Policy 10.7; `postinst` seeds
  `/etc/lrcm/lrcm.conf` from the new location exactly as before.
- `Depends` is a single line, and the description synopsis capitalises Linux.

### removed

- **Fedora 39** is no longer listed. It reached end of life in May 2024 and its
  packages are gone from the mirrors, so the entry promised something that
  could not work.

### repository

- A `Makefile` is now the single entry point: `make check` runs exactly what CI
  runs, so the README can stop listing six commands that drifted out of step
  with the pipeline.
- Added `SECURITY.md` with a private disclosure channel and, more usefully, a
  written statement of what lrcm assumes about its environment - notably that
  write access to the playbook repository is root access to the fleet.
- ruff now enforces pydocstyle (PEP 257), pep8-naming (PEP 8, including the
  `Error` suffix rule that renamed `RuntimeFailure` to `StepFailedError`),
  blind-except and pylint rules. `from __future__ import annotations` is gone,
  since PEP 604 unions are native in the Python 3.10 this project requires, and
  `__version__` sits where PEP 8 puts module dunders.
- The licence is declared as an SPDX expression per PEP 639.

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
- The stale `[LOGGING]` section was dropped from the configuration template. The
  code behind it went in 0.7.0 and the remote logging target it pointed at no
  longer exists; a leftover `[LOGGING]` section in an existing configuration
  file is simply ignored. Use `--syslog` if you want lrcm's output collected.

## 0.5.2

- Switch back from `SafeConfigParser` to `ConfigParser` because `SafeConfigParser` is deprecated in Python 3.12

## 0.5.1

- remove config file, add demo-config-file

## 0.5

- Add new variable `delay_before_start_random_max_seconds` (default: 60) for a random delay.
- Implement functionality for variables `delay_before_start_seconds` and `delay_before_start_random_max_seconds`
- switch from `ConfigParser` to `SafeConfigParser`
- add defaults for `delay_before_start_seconds`, `delay_before_start_random_max_seconds`, `branch`, `playbook`, `authentication_required`, `reboot_cronjob`, `hourly_cronjob`, `daily_cronjob`, `pidfile` so no breaking changes to v0.4
- fix wrong version in package build
- add changelog file
