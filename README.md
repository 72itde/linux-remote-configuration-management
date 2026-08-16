# linux-remote-configuration-management: lrcm

[![ci](https://github.com/72itde/linux-remote-configuration-management/actions/workflows/ci.yml/badge.svg)](https://github.com/72itde/linux-remote-configuration-management/actions/workflows/ci.yml)

![lrcm main image](./lrcm.drawio.png)

## use-case

The main use-case is managing Linux clients without having any management
infrastructure and/or network access to the client devices, e.g. at (remote)
schools, universities, IoT-devices, in science, unattended terminals, marketing
displays, sensors etc.

## main goal

At first we had the need to implement a remote configuration management for some
Linux clients

- somewhere in the world
- not accessible remote
- not always online
- using a secure way
- in a reproducable way
- standardized
- very small memory and cpu footprint (currently below 35 MB)

We had a first client - a bash-script - running for two years doing all the
things we need, but the need for more features brought us here.

## what you get

You get an agent for Linux with a configured dummy backend.

## what you can do

You can change the configuration to use your own git instance and develop your
own playbooks, roles, etc. You can also use Github or another git-compatible
platform as backend. Maybe our commercial offer - a very secure Gitlab instance
- is also interesting for you. We're also offering our engineers to develop the
playbooks you need for configuration management.

## how it works

lrcm is a single python script. You can execute it manually or scheduled by cron
(or whatever). On every run it

1. checks that the distribution and the python version are supported,
2. takes an advisory lock so two runs can never overlap,
3. waits a fixed plus a random delay, so a whole fleet does not hit the git
   server in the same second,
4. shallow-clones the configured branch of your playbook repository into a
   temporary directory,
5. applies `playbook.yaml`, then `<hostname>-playbook.yaml` if it exists,
6. creates or removes its own `/etc/cron.d/lrcm_*` entries, and
7. deletes the temporary directory and releases the lock - also when something
   went wrong.

## installation

### Debian 12, Debian 13, Ubuntu 24.04 LTS, Ubuntu 26.04 LTS, elementary OS 8

Download the `.deb` from [releases](https://github.com/72itde/linux-remote-configuration-management/releases)
and install it:

```sh
sudo apt-get install ./lrcm_<version>_all.deb
```

The package pulls in every dependency, installs the agent to `/opt/lrcm/`, adds
a `/usr/bin/lrcm` entry point and creates `/etc/lrcm/lrcm.conf` from the shipped
template on first install. Your configuration is never overwritten by an
upgrade.

### Fedora, Linux Mint, LMDE

No packages available yet, so use `git clone` and install the dependencies with
the playbooks in [client-setup/](client-setup/).

## configuration

The configuration lives in `/etc/lrcm/lrcm.conf`; see
[lrcm.conf.template](lrcm.conf.template) for a commented example.

| section | option | default | meaning |
| --- | --- | --- | --- |
| `GENERAL` | `delay_before_start_seconds` | `60` | fixed delay before lrcm starts working |
| `GENERAL` | `delay_before_start_random_max_seconds` | `60` | additional random delay of 0..n seconds; `0` disables it |
| `GENERAL` | `timeout_seconds` | `3600` | upper bound for one git transfer and one playbook run |
| `GIT` | `repository` | *required* | url of the playbook repository (`https`, `http`, `ssh`, `git` or `file`) |
| `GIT` | `branch` | `main` | branch to clone |
| `GIT` | `playbook` | `playbook.yaml` | playbook to apply, relative to the repository root |
| `GIT` | `authentication_required` | `false` | use `username`/`token` (https only) |
| `GIT` | `username` | - | git username |
| `GIT` | `token` | - | git token |
| `CRONJOB` | `hourly_cronjob` | `false` | keep `/etc/cron.d/lrcm_hourly` |
| `CRONJOB` | `daily_cronjob` | `false` | keep `/etc/cron.d/lrcm_daily` |
| `CRONJOB` | `reboot_cronjob` | `false` | keep `/etc/cron.d/lrcm_reboot` |
| `PIDFILE` | `pidfile` | `/run/lrcm.pid` | lock file that serialises lrcm runs |

Cron entries set to `false` are actively removed, so switching one off here
uninstalls it on the next run.

## command line

```
lrcm [-c PATH] [-d] [-v] [-j BOOL | --no-cronjobs] [--no-delay] [--syslog]
```

| option | meaning |
| --- | --- |
| `-c`, `--configfile PATH` | configuration file (default `/etc/lrcm/lrcm.conf`) |
| `-v`, `--verbose` | log progress information |
| `-d`, `--debug` | log everything, including ansible output |
| `-j`, `--cronjobs BOOL` | manage the cron entries (default `true`) |
| `--no-cronjobs` | same as `--cronjobs=false` |
| `--no-delay` | skip the configured start delay, for interactive runs |
| `--syslog` | additionally send log records to syslog |
| `--version` | print the version and exit |

Exit codes: `0` success (also when another instance holds the lock), `1`
configuration or environment error, `2` a step failed while working.

## logging

All diagnostics go to **stderr**; lrcm writes nothing to stdout. Every record
carries an RFC 3339 timestamp with the local UTC offset, so lines from a fleet
spread over several timezones can still be ordered:

```
2026-08-16T09:12:34.567+02:00 INFO     repository cloned into /tmp/lrcm-2tdlbisq/project
2026-08-16T09:12:35.881+02:00 INFO     playbook playbook.yaml finished with status successful (rc 0)
```

Three verbosity levels:

| flag | what you get |
| --- | --- |
| *(none)* | warnings and errors only - a successful cron run prints nothing at all |
| `-v` | lrcm's own progress: clone, each playbook, each cron entry |
| `-d` | the above plus ansible's output, one record per line, and memory figures |

`--syslog` additionally sends everything to the local syslog socket under the
`daemon` facility. Those records deliberately carry **no** timestamp of their
own - syslog and journald stamp each line themselves, and the Python level is
mapped to the syslog priority, so `journalctl -p warning -t lrcm` works.

## host-specific tasks

You can add a host-specific playbook to your repository; the naming convention
is

`<hostname>-<playbook-name>`

that means if your hostname for example is `dirtydesktop69` and your
playbook-name (section `[GIT]`/`playbook:` in the config file) is
`playbook.yaml` you just have to add a playbook file called
`dirtydesktop69-playbook.yaml` to your repository and it will be applied to the
host called `dirtydesktop69` after the standard playbook was applied.

## token handling

When `authentication_required` is set, the token is handed to git through
`GIT_ASKPASS` instead of being embedded in the repository url. It therefore
never appears

- in the process list (`/proc/<pid>/cmdline` is world readable),
- in the cloned repository's `.git/config`, or
- in lrcm's log output, including git's own error messages.

`/etc/lrcm` is `0700 root:root` and `/etc/lrcm/lrcm.conf` is `0600 root:root`;
the package re-applies both on every upgrade.

## compatibility

### Linux distributions

Support is matched on the distribution id and the `major.minor` version, so
every point release of a supported version works - `24.04`, `24.04.1` and
`24.04.7` alike.

Every row marked "CI" is installed and driven through a full run - clone,
playbook, host-specific playbook, cron entry creation and removal, failure exit
codes - in that container on every push. The support table in `lrcm.py` carries
the image name, and a unit test fails if it ever disagrees with the CI matrix,
so the column below cannot quietly become a lie.

| distribution | python | verified |
| --- | --- | --- |
| Debian GNU/Linux 12 (bookworm) | 3.11.2 | CI, from the `.deb` |
| Debian GNU/Linux 13 (trixie) | 3.13.5 | CI, from the `.deb` |
| Ubuntu 22.04 LTS (jammy jellyfish) | 3.10.12 | CI, from the `.deb` |
| Ubuntu 24.04 LTS (noble numbat) | 3.12.3 | CI, from the `.deb` |
| Ubuntu 26.04 LTS (resolute raccoon) | 3.14.4 | CI, from the `.deb` |
| Fedora Linux 43 | 3.14.7 | CI, from the checkout |
| Fedora Linux 44 | 3.14.7 | CI, from the checkout |
| Linux Mint 21.3 (virginia) | 3.10.12 | rebuild of Ubuntu 22.04 |
| Linux Mint 22 series (wilma … zena) | 3.12.3 | rebuild of Ubuntu 24.04 |
| LMDE 6 (faye) | 3.11.2 | rebuild of Debian 12 |
| LMDE 7 (gigi) | 3.13.5 | rebuild of Debian 13 |
| elementary OS 8 (circe) | 3.12.3 | rebuild of Ubuntu 24.04 |

The rebuilds have no public container image, so CI cannot run them directly.
They are the named base distribution with a different desktop on top, and lrcm
touches nothing a desktop changes.

Running on an unlisted distribution is refused with exit code 1.

### Python

lrcm requires Python 3.10 or newer, and is exercised on 3.10, 3.11, 3.12, 3.13
and 3.14 through the distributions above.

Compatibility is judged per minor series, not per patch level: distributions
update the CPython micro version inside a stable release - Ubuntu 22.04 went
3.10.4 → 3.10.6 → 3.10.12 - and none of that affects lrcm. A patch bump is
silent; an untested minor series logs a warning and keeps running.

## system requirements

### client preparation

Only needed when you install from git instead of the `.deb`. On Debian, Ubuntu,
Linux Mint, LMDE and elementary OS:

```sh
sudo apt-get update && sudo apt-get -y install \
  python3 python3-git python3-ansible-runner python3-jinja2 \
  python3-validators python3-distro git cron
sudo systemctl enable --now cron
```

There are Ansible playbooks for the same job in [client-setup/](client-setup/).

## testing

### test with the demo repository

```sh
cd /opt/ && sudo git clone https://github.com/72itde/linux-remote-configuration-management.git --branch main
cd linux-remote-configuration-management/
sudo ./lrcm.py --configfile=lrcm.conf.template --debug --no-cronjobs --no-delay
```

### development

```sh
make venv          # .venv with the runtime and development dependencies
. .venv/bin/activate

make check         # everything CI checks, except the container matrix
make format        # rewrite the code to the project style
make help          # list every target
```

`make check` runs ruff, mypy, pytest, ansible-lint's production profile,
yamllint, shellcheck and the version-consistency check - the same set, in the
same order, as the CI workflow. If it passes locally, CI passes too.

### building the package

```sh
make build         # writes dist/lrcm_<version>_all.deb
make lintian       # checks that package against Debian policy
make smoke         # installs it in a Debian 13 container and drives a full run
```

The staging tree is assembled from scratch in a temporary directory, so no
repository file can leak into the package. `make lintian` must come back clean:
CI fails on any lintian error or warning that is not listed, with a reason, in
[packaging/debian/lintian-overrides](packaging/debian/lintian-overrides).

## releasing

1. bump `VERSION` and `__version__` in `lrcm.py`, add a `CHANGELOG.md` section,
2. merge to `main`,
3. push a tag `v<version>`.

The [release workflow](.github/workflows/release.yml) verifies that tag,
`VERSION`, `lrcm.py` and `CHANGELOG.md` agree, builds the `.deb`, generates
`SHA256SUMS` and publishes a GitHub release with the changelog section as
release notes.

## token creation

### Gitlab

A token in Gitlab must have an expiration date that could lead to problems; you
can extend the token by using SQL in the Gitlab database. Use role **Reporter**
and check **read_repository**

## upgrading from 0.7.x

The configuration file format is unchanged and existing cron entries keep
working. Three things changed:

- lrcm is quiet by default. Add `-v` to the cron job to get the old `INFO`
  output, or `--syslog` to send it to the journal.
- A failing playbook is now reported: lrcm exits `2` instead of `0`. Cron will
  mail you about failures that previously went unnoticed.
- `python3-psutil` is no longer needed; the pidfile is now a real advisory lock.

## roadmap

- remote logging
- remote status dashboard
- code signing/verification

## license

[MIT](LICENSE)

## commercial support

If you're interested in commercial support please contact us via
<https://www.72it.de/>
