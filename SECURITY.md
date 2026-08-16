# Security policy

## Supported versions

Only the latest release receives fixes. See the compatibility table in the
[README](README.md#compatibility) for the distributions it is tested on.

## Reporting a vulnerability

Please report suspected vulnerabilities privately, **not** as a public issue:

- email <florian.gusinde@72it.de>, or
- use GitHub's [private vulnerability reporting](https://github.com/72itde/linux-remote-configuration-management/security/advisories/new).

Please include the lrcm version (`lrcm --version`), the distribution, and what
an attacker would gain. You can expect an acknowledgement within a few working
days.

## What lrcm assumes about its environment

Understanding these makes it easier to judge whether something is a
vulnerability:

- **lrcm runs as root and applies playbooks from a git repository.** Anyone who
  can push to that repository, or to the branch you configured, can run
  arbitrary code as root on every client. The repository is part of your trust
  boundary; treat write access to it as root access to the fleet.
- **There is no signature verification yet.** lrcm trusts the transport (TLS)
  and the git server. Commit signing is on the roadmap.
- **The git token in `/etc/lrcm/lrcm.conf` is a secret.** The package keeps
  that file `0600 root:root` inside a `0700` directory and re-applies both on
  every upgrade. The token is passed to git through `GIT_ASKPASS`, so it does
  not appear in the process list or in the clone's `.git/config`, and a
  redacting log filter keeps it out of log output.
- **A local unprivileged user should not be able to influence a run.** The
  pidfile is opened with `O_NOFOLLOW` and locked with `flock`; the working
  directory is created with `mkstemp` semantics. Reports of a local user
  escalating through lrcm are in scope.

## Out of scope

- Anything requiring push access to the playbook repository, or root on the
  client, which is already full control.
- The playbooks themselves. lrcm executes what you tell it to execute.
