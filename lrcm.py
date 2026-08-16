#!/usr/bin/python3
"""lrcm - linux remote configuration management.

Clones a git repository containing Ansible playbooks and applies them to the
local machine.

Github: https://github.com/72itde/linux-remote-configuration-management
Contact: https://www.72it.de/#tab-contact
"""

from __future__ import annotations

import argparse
import configparser
import fcntl
import json
import logging
import logging.handlers
import os
import random
import resource
import shutil
import signal
import sys
import tempfile
import urllib.parse
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from time import sleep
from types import FrameType
from typing import Final

import ansible_runner
import distro
import git
import validators
from jinja2 import Environment, FileSystemLoader, StrictUndefined

__version__ = "0.8.0"

LOG: Final = logging.getLogger("lrcm")

EXIT_SUCCESS: Final = 0
EXIT_CONFIGURATION_ERROR: Final = 1
EXIT_RUNTIME_ERROR: Final = 2


@dataclass(frozen=True)
class SupportedDistribution:
    """A distribution lrcm is developed and tested on.

    ``version`` is matched as a dotted prefix of what ``distro.version()``
    reports, so a single entry covers every point release: ``24.04`` matches
    ``24.04``, ``24.04.1`` and ``24.04.7`` alike.
    """

    distro_id: str
    version: str
    label: str


# Matching is done on distro.id()/distro.version() rather than on the pretty
# name, because the pretty name changes with every point release ("Ubuntu
# 24.04.1 LTS" -> "Ubuntu 24.04.2 LTS") and previously broke support after
# every upgrade.
SUPPORTED_DISTRIBUTIONS: Final[tuple[SupportedDistribution, ...]] = (
    SupportedDistribution("debian", "12", "Debian GNU/Linux 12 (bookworm)"),
    SupportedDistribution("debian", "13", "Debian GNU/Linux 13 (trixie)"),
    SupportedDistribution("ubuntu", "24.04", "Ubuntu 24.04 LTS (noble numbat)"),
    SupportedDistribution("ubuntu", "26.04", "Ubuntu 26.04 LTS (resolute raccoon)"),
    SupportedDistribution("linuxmint", "6", "LMDE 6 (faye)"),
    SupportedDistribution("linuxmint", "7", "LMDE 7 (gigi)"),
    SupportedDistribution("linuxmint", "21.3", "Linux Mint 21.3"),
    SupportedDistribution("elementary", "8", "elementary OS 8"),
    SupportedDistribution("fedora", "39", "Fedora Linux 39"),
)

# Hard floor. Below this the interpreter cannot run this script at all.
MINIMUM_PYTHON_VERSION: Final[tuple[int, int]] = (3, 10)

# Versions this release was actually exercised against. Running on anything
# else is allowed but produces a warning, so a distribution point release that
# bumps the patch level no longer takes the whole fleet down.
TESTED_PYTHON_VERSIONS: Final[tuple[str, ...]] = (
    "3.10.12",  # Linux Mint 21.3
    "3.11.2",  # Debian 12, LMDE 6
    "3.12.0",
    "3.12.3",  # Ubuntu 24.04, elementary OS 8
    "3.13.5",  # Debian 13, LMDE 7
    "3.14.3",  # Ubuntu 26.04
)

CRONJOB_SPECIAL_TIMES: Final[tuple[str, ...]] = ("hourly", "daily", "reboot")

# ansible-runner looks for the playbooks in <private_data_dir>/project and for
# its own configuration in <private_data_dir>/env. The cloned repository goes
# into the former, so it cannot influence the latter.
PROJECT_SUBDIRECTORY: Final = "project"

# git transports lrcm knows how to handle.
SUPPORTED_URL_SCHEMES: Final[frozenset[str]] = frozenset({"http", "https", "ssh", "git", "file"})
# transports that can carry a username/token pair
AUTHENTICATED_URL_SCHEMES: Final[frozenset[str]] = frozenset({"http", "https"})


class ConfigurationError(Exception):
    """The configuration or the runtime environment is unusable."""


class RuntimeFailure(Exception):
    """A step failed while lrcm was doing its actual work."""


@dataclass(frozen=True)
class Config:
    """The validated contents of the lrcm ini file."""

    delay_before_start_seconds: int
    delay_before_start_random_max_seconds: int
    timeout_seconds: int
    repository: str
    branch: str
    playbook: str
    authentication_required: bool
    username: str
    token: str
    hourly_cronjob: bool
    daily_cronjob: bool
    reboot_cronjob: bool
    pidfile: Path

    def cronjob_enabled(self, special_time: str) -> bool:
        """Return whether the cron entry for ``special_time`` should exist."""
        return {
            "hourly": self.hourly_cronjob,
            "daily": self.daily_cronjob,
            "reboot": self.reboot_cronjob,
        }[special_time]


# --------------------------------------------------------------------------- #
# command line and logging
# --------------------------------------------------------------------------- #


def parse_bool(value: str) -> bool:
    """Parse a command line boolean, accepting the spellings ini files allow."""
    lowered = value.strip().lower()
    if lowered in {"true", "yes", "on", "1"}:
        return True
    if lowered in {"false", "no", "off", "0"}:
        return False
    raise argparse.ArgumentTypeError(f"expected a boolean value, got {value!r}")


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the command line parser."""
    parser = argparse.ArgumentParser(
        prog="lrcm",
        description=__doc__.split("\n\n")[0] if __doc__ else None,
    )
    parser.add_argument(
        "-c",
        "--configfile",
        default="/etc/lrcm/lrcm.conf",
        type=Path,
        help="path to the configuration file (default: %(default)s)",
    )
    parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="log everything, including ansible output",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="log progress information (implied by --debug)",
    )
    parser.add_argument(
        "-j",
        "--cronjobs",
        nargs="?",
        const=True,
        default=True,
        type=parse_bool,
        metavar="BOOL",
        help="manage the lrcm cron entries (default: true)",
    )
    parser.add_argument(
        "--no-cronjobs",
        dest="cronjobs",
        action="store_const",
        const=False,
        help="do not touch the lrcm cron entries",
    )
    parser.add_argument(
        "--no-delay",
        action="store_true",
        help="skip the configured start delay, for interactive runs",
    )
    parser.add_argument(
        "--syslog",
        action="store_true",
        help="additionally send log records to syslog",
    )
    parser.add_argument("--version", action="version", version=f"lrcm {__version__}")
    return parser


def configure_logging(*, debug: bool, verbose: bool, syslog: bool) -> None:
    """Set up logging once, for every run - not only in debug mode."""
    if debug:
        level = logging.DEBUG
    elif verbose:
        level = logging.INFO
    else:
        # lrcm normally runs from cron, which mails anything on stdout to root.
        # Stay quiet unless something actually needs attention.
        level = logging.WARNING

    LOG.setLevel(level)
    LOG.propagate = False

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    LOG.addHandler(stream_handler)

    if syslog:
        try:
            syslog_handler = logging.handlers.SysLogHandler(address="/dev/log")
        except OSError:
            LOG.warning("syslog requested but /dev/log is not available")
        else:
            syslog_handler.setFormatter(logging.Formatter("lrcm[%(process)d]: %(message)s"))
            LOG.addHandler(syslog_handler)


def log_memory_usage() -> None:
    """Log the peak resident set size; lrcm aims at a small footprint.

    The ansible-playbook children are included, because they are what actually
    dominates the footprint on a client.
    """
    own_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    children_kb = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    LOG.debug(
        "memory usage: %.3fMB (self %.3fMB, children %.3fMB)",
        (own_kb + children_kb) / 1024,
        own_kb / 1024,
        children_kb / 1024,
    )


# --------------------------------------------------------------------------- #
# platform support
# --------------------------------------------------------------------------- #


def version_matches(actual: str, expected: str) -> bool:
    """Return whether ``actual`` is ``expected`` or a point release of it.

    >>> version_matches("24.04.3", "24.04")
    True
    >>> version_matches("24.10", "24.04")
    False
    """
    actual_parts = actual.split(".")
    expected_parts = expected.split(".")
    if len(actual_parts) < len(expected_parts):
        return False
    return actual_parts[: len(expected_parts)] == expected_parts


def find_supported_distribution(distro_id: str, version: str) -> SupportedDistribution | None:
    """Return the matching support entry, or ``None`` if there is none."""
    for candidate in SUPPORTED_DISTRIBUTIONS:
        if candidate.distro_id == distro_id and version_matches(version, candidate.version):
            return candidate
    return None


def check_distribution() -> None:
    """Verify the running distribution is one lrcm supports."""
    distro_id = distro.id()
    version = distro.version()
    pretty = distro.name(pretty=True)

    supported = find_supported_distribution(distro_id, version)
    if supported is None:
        raise ConfigurationError(
            f"distribution {pretty!r} (id={distro_id!r}, version={version!r}) "
            f"is not supported; supported: "
            f"{', '.join(entry.label for entry in SUPPORTED_DISTRIBUTIONS)}"
        )
    LOG.info("distribution %s is supported (%s)", pretty, supported.label)


def check_python_version() -> None:
    """Verify the interpreter is new enough, and note untested versions."""
    current = sys.version_info[:3]
    if current[:2] < MINIMUM_PYTHON_VERSION:
        raise ConfigurationError(
            f"python {'.'.join(map(str, current))} is too old; "
            f"lrcm needs at least {'.'.join(map(str, MINIMUM_PYTHON_VERSION))}"
        )

    current_string = ".".join(map(str, current))
    if current_string in TESTED_PYTHON_VERSIONS:
        LOG.info("python version %s is supported", current_string)
    else:
        LOG.warning(
            "python version %s is not one of the tested versions (%s); continuing",
            current_string,
            ", ".join(TESTED_PYTHON_VERSIONS),
        )


# --------------------------------------------------------------------------- #
# configuration
# --------------------------------------------------------------------------- #


def read_config(path: Path) -> Config:
    """Read and validate the ini file at ``path``."""
    if not os.access(path, os.R_OK):
        raise ConfigurationError(f"configfile {path} is not readable")
    LOG.info("configfile %s is readable", path)

    # interpolation=None: a token containing '%' would otherwise raise
    # InterpolationSyntaxError, or worse, be silently rewritten.
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(path)
    except configparser.Error as error:
        raise ConfigurationError(f"configfile {path} is malformed: {error}") from error

    try:
        repository = parser.get("GIT", "repository")
    except (configparser.NoSectionError, configparser.NoOptionError) as error:
        raise ConfigurationError(f"configfile {path} is incomplete: {error}") from error

    authentication_required = parser.getboolean("GIT", "authentication_required", fallback=False)

    config = Config(
        delay_before_start_seconds=parser.getint(
            "GENERAL", "delay_before_start_seconds", fallback=60
        ),
        delay_before_start_random_max_seconds=parser.getint(
            "GENERAL", "delay_before_start_random_max_seconds", fallback=60
        ),
        timeout_seconds=parser.getint("GENERAL", "timeout_seconds", fallback=3600),
        repository=repository,
        branch=parser.get("GIT", "branch", fallback="main"),
        playbook=parser.get("GIT", "playbook", fallback="playbook.yaml"),
        authentication_required=authentication_required,
        username=parser.get("GIT", "username", fallback=""),
        token=parser.get("GIT", "token", fallback=""),
        hourly_cronjob=parser.getboolean("CRONJOB", "hourly_cronjob", fallback=False),
        daily_cronjob=parser.getboolean("CRONJOB", "daily_cronjob", fallback=False),
        reboot_cronjob=parser.getboolean("CRONJOB", "reboot_cronjob", fallback=False),
        pidfile=Path(parser.get("PIDFILE", "pidfile", fallback="/run/lrcm.pid")),
    )
    validate_config(config)
    return config


def validate_config(config: Config) -> None:
    """Reject configurations that would fail later in a confusing way."""
    if config.delay_before_start_seconds < 0:
        raise ConfigurationError("delay_before_start_seconds must not be negative")
    if config.delay_before_start_random_max_seconds < 0:
        raise ConfigurationError("delay_before_start_random_max_seconds must not be negative")
    if config.timeout_seconds <= 0:
        raise ConfigurationError("timeout_seconds must be greater than zero")

    if not config.playbook or "\x00" in config.playbook:
        raise ConfigurationError("playbook must be a non-empty file name")
    playbook_path = Path(config.playbook)
    if playbook_path.is_absolute() or ".." in playbook_path.parts:
        raise ConfigurationError(
            "playbook must be a path inside the repository, not an absolute path "
            "and not containing '..'"
        )

    scheme = urllib.parse.urlsplit(config.repository).scheme
    if scheme not in SUPPORTED_URL_SCHEMES:
        raise ConfigurationError(
            f"repository url uses unsupported scheme {scheme!r}; supported: "
            f"{', '.join(sorted(SUPPORTED_URL_SCHEMES))}"
        )
    if scheme in {"http", "https"} and not validators.url(config.repository):
        raise ConfigurationError("repository is not a valid url")
    if scheme == "http":
        LOG.warning(
            "repository is fetched over plain http; credentials and playbooks "
            "are transmitted unencrypted"
        )

    if config.authentication_required:
        if scheme not in AUTHENTICATED_URL_SCHEMES:
            raise ConfigurationError(
                f"authentication_required is set but scheme {scheme!r} does not "
                f"take a username and token"
            )
        if not config.username or not config.token:
            raise ConfigurationError(
                "authentication_required is set but username or token is empty"
            )


# --------------------------------------------------------------------------- #
# pidfile locking
# --------------------------------------------------------------------------- #


@contextmanager
def pidfile_lock(pidfile: Path) -> Iterator[bool]:
    """Serialise lrcm runs through an advisory lock on ``pidfile``.

    Yields ``True`` when the lock was acquired and ``False`` when another
    instance holds it. The kernel releases the lock when the process dies, so a
    machine that was powered off mid-run does not stay blocked by a stale
    pidfile - and a recycled pid can never be mistaken for a running instance.
    """
    directory = pidfile.parent
    if not os.access(directory, os.W_OK):
        raise ConfigurationError(f"pidfile directory {directory} is not writable")

    # O_NOFOLLOW: refuse to follow a symlink planted at the pidfile path.
    try:
        file_descriptor = os.open(pidfile, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o644)
    except OSError as error:
        raise ConfigurationError(f"cannot open pidfile {pidfile}: {error}") from error

    try:
        try:
            fcntl.flock(file_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            holder = os.read(file_descriptor, 32).decode("ascii", "replace").strip()
            LOG.info("another lrcm instance is running (pid %s), nothing to do", holder)
            yield False
            return

        os.ftruncate(file_descriptor, 0)
        os.write(file_descriptor, f"{os.getpid()}\n".encode("ascii"))
        os.fsync(file_descriptor)
        LOG.info("pid %d written to pidfile %s", os.getpid(), pidfile)
        try:
            yield True
        finally:
            # Unlink before releasing, so a waiting instance cannot lock a file
            # that is about to disappear.
            pidfile.unlink(missing_ok=True)
            LOG.info("pidfile removed")
    finally:
        os.close(file_descriptor)


# --------------------------------------------------------------------------- #
# git
# --------------------------------------------------------------------------- #


def redact(text: str, *secrets_to_hide: str) -> str:
    """Replace every occurrence of the given secrets with a placeholder."""
    for secret in secrets_to_hide:
        if secret:
            text = text.replace(secret, "***")
            text = text.replace(urllib.parse.quote(secret, safe=""), "***")
    return text


def authenticated_repository_url(repository: str, username: str) -> str:
    """Return ``repository`` with ``username`` in the userinfo part.

    The token deliberately stays out of the url: it is handed to git through
    ``GIT_ASKPASS`` instead, so it never appears in the process command line
    (world readable via /proc) nor in the cloned repository's .git/config.
    """
    parsed = urllib.parse.urlsplit(repository)
    netloc = f"{urllib.parse.quote(username, safe='')}@{parsed.hostname or ''}"
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    return urllib.parse.urlunsplit(
        (parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment)
    )


@contextmanager
def git_credential_environment(token: str, timeout_seconds: int) -> Iterator[dict[str, str]]:
    """Yield the environment lrcm runs git in.

    The token is picked up out of band through ``GIT_ASKPASS``. The helper
    script gets its own temporary directory - it must not live in the clone
    target, because git refuses to clone into a non-empty directory.

    ``GIT_HTTP_LOW_SPEED_*`` aborts a transfer that has stalled, so a hung git
    server cannot keep the pidfile lock forever and block every later run.
    """
    environment = {
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_HTTP_LOW_SPEED_LIMIT": "1000",
        "GIT_HTTP_LOW_SPEED_TIME": str(timeout_seconds),
    }
    if not token:
        yield environment
        return

    directory = Path(tempfile.mkdtemp(prefix="lrcm-askpass-"))
    try:
        askpass = directory / "askpass.sh"
        askpass.touch(mode=0o700)
        askpass.write_text('#!/bin/sh\nprintf "%s" "${LRCM_GIT_TOKEN}"\n', encoding="ascii")
        yield {**environment, "GIT_ASKPASS": str(askpass), "LRCM_GIT_TOKEN": token}
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def clone_repository(config: Config, target: Path) -> None:
    """Shallow-clone the configured branch into ``target``."""
    if config.authentication_required:
        url = authenticated_repository_url(config.repository, config.username)
    else:
        url = config.repository
    LOG.debug("cloning %s (branch %s)", redact(url, config.token), config.branch)

    with git_credential_environment(config.token, config.timeout_seconds) as environment:
        try:
            git.Repo.clone_from(
                url,
                target,
                branch=config.branch,
                depth=1,
                single_branch=True,
                env=environment,
            )
        except git.GitError as error:
            # git echoes the url back in its error messages; make sure a token
            # that ended up there anyway never reaches the log.
            raise RuntimeFailure(
                f"cloning the repository failed: {redact(str(error), config.token)}"
            ) from None

    LOG.info("repository cloned into %s", target)


# --------------------------------------------------------------------------- #
# ansible
# --------------------------------------------------------------------------- #


def ansible_event_handler(event: dict[str, object]) -> bool:
    """Forward ansible-runner output into our own logger."""
    stdout = event.get("stdout")
    if stdout:
        LOG.info("ansible: %s", stdout)
    return True


def run_playbook(private_data_dir: Path, playbook: str, timeout_seconds: int) -> None:
    """Run ``playbook`` and raise if ansible reports failure.

    ``private_data_dir`` is *not* the checkout: the repository lives in its
    ``project/`` subdirectory. ansible-runner reads its own settings from
    ``env/`` and ``inventory/`` next to it, and keeping the two apart means a
    playbook repository that happens to contain a ``project/`` or ``env/``
    directory cannot change how the runner itself is configured.
    """
    log_memory_usage()
    LOG.info("running playbook %s", playbook)

    runner_config = ansible_runner.RunnerConfig(
        private_data_dir=str(private_data_dir),
        playbook=playbook,
        timeout=timeout_seconds,
    )
    runner_config.prepare()
    # ansible-runner would otherwise dump the full ansible output to stdout a
    # second time, on top of what the event handler already logged.
    runner_config.suppress_ansible_output = True

    runner = ansible_runner.Runner(event_handler=ansible_event_handler, config=runner_config)
    status, return_code = runner.run()
    LOG.info("playbook %s finished with status %s (rc %s)", playbook, status, return_code)
    log_memory_usage()

    if status != "successful" or return_code != 0:
        raise RuntimeFailure(f"playbook {playbook} failed with status {status} (rc {return_code})")


def render_cronjob_playbook(
    *,
    template_directory: Path,
    output_path: Path,
    special_time: str,
    job: str,
    enabled: bool,
) -> None:
    """Render the cron playbook for one special time into ``output_path``."""
    environment = Environment(
        loader=FileSystemLoader(template_directory),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        autoescape=False,  # noqa: S701 - the output is YAML, html escaping would corrupt it
    )
    template = environment.get_template("cronjob.yaml.j2")

    # json.dumps produces a double quoted scalar that is valid YAML, so a path
    # or job line containing ':', '#' or '{' cannot break the document.
    rendered = template.render(
        cronjob_special_time=special_time,
        cronjob_name=json.dumps(f"Manage lrcm {special_time} cronjob file"),
        cronjob_job=json.dumps(job),
        cronjob_file=json.dumps(f"lrcm_{special_time}"),
        cronjob_file_path=json.dumps(f"/etc/cron.d/lrcm_{special_time}"),
        cronjob_state="present" if enabled else "absent",
        cronjob_file_state="file" if enabled else "absent",
    )
    output_path.write_text(rendered, encoding="utf-8")


def manage_cronjobs(config: Config, private_data_dir: Path, configfile: Path) -> None:
    """Create or remove the lrcm cron entries according to the configuration."""
    # __file__ may be reached through the /usr/bin/lrcm symlink; resolve() gets
    # us the real location, next to which the templates directory lives.
    script_path = Path(__file__).resolve()
    template_directory = script_path.parent / "templates"
    job = f"{script_path} --configfile={configfile.resolve()}"
    LOG.info("managing cronjobs for %s", script_path)

    for special_time in CRONJOB_SPECIAL_TIMES:
        enabled = config.cronjob_enabled(special_time)
        LOG.info("cronjob %s: %s", special_time, "present" if enabled else "absent")
        playbook_name = f"lrcm_generated_cronjob_{special_time}.yaml"
        render_cronjob_playbook(
            template_directory=template_directory,
            output_path=private_data_dir / PROJECT_SUBDIRECTORY / playbook_name,
            special_time=special_time,
            job=job,
            enabled=enabled,
        )
        run_playbook(private_data_dir, playbook_name, config.timeout_seconds)


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #


def start_delay(config: Config) -> None:
    """Sleep for the configured, partly randomised amount of time.

    The random part staggers a whole fleet so that a git server does not see
    every client at the same second.
    """
    jitter = (
        random.randrange(config.delay_before_start_random_max_seconds)  # noqa: S311
        if config.delay_before_start_random_max_seconds > 0
        else 0
    )
    delay = config.delay_before_start_seconds + jitter
    LOG.info("delaying start by %d seconds", delay)
    if delay:
        sleep(delay)


def install_signal_handlers() -> None:
    """Turn SIGTERM/SIGINT into SystemExit so cleanup handlers still run."""

    def handler(signal_number: int, _frame: FrameType | None) -> None:
        LOG.warning("received signal %d, shutting down", signal_number)
        raise SystemExit(EXIT_RUNTIME_ERROR)

    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT, handler)


def apply_configuration(config: Config, arguments: argparse.Namespace) -> None:
    """Do the actual work: clone, run playbooks, manage cron entries."""
    workdir = Path(tempfile.mkdtemp(prefix="lrcm-"))
    checkout = workdir / PROJECT_SUBDIRECTORY
    LOG.info("workdir: %s", workdir)
    try:
        clone_repository(config, checkout)

        if not (checkout / config.playbook).is_file():
            raise RuntimeFailure(f"playbook {config.playbook} not found in the repository")
        run_playbook(workdir, config.playbook, config.timeout_seconds)

        hostname = os.uname().nodename
        host_playbook = f"{hostname}-{config.playbook}"
        if (checkout / host_playbook).is_file():
            LOG.info("host-specific playbook found: %s", host_playbook)
            run_playbook(workdir, host_playbook, config.timeout_seconds)
        else:
            LOG.info("no host-specific playbook %s in the repository", host_playbook)

        if arguments.cronjobs:
            manage_cronjobs(config, workdir, arguments.configfile)
        else:
            LOG.info("cronjob management disabled")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
        LOG.info("workdir deleted")


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns the process exit code."""
    arguments = build_argument_parser().parse_args(argv)
    configure_logging(debug=arguments.debug, verbose=arguments.verbose, syslog=arguments.syslog)
    install_signal_handlers()
    LOG.info("lrcm %s starting on %s", __version__, os.uname().nodename)
    log_memory_usage()

    try:
        check_distribution()
        check_python_version()
        config = read_config(arguments.configfile)

        with pidfile_lock(config.pidfile) as acquired:
            if not acquired:
                return EXIT_SUCCESS
            if not arguments.no_delay:
                start_delay(config)
            apply_configuration(config, arguments)
    except ConfigurationError as error:
        LOG.error("%s", error)
        LOG.debug("configuration error detail", exc_info=True)
        return EXIT_CONFIGURATION_ERROR
    except RuntimeFailure as error:
        LOG.error("%s", error)
        LOG.debug("runtime failure detail", exc_info=True)
        return EXIT_RUNTIME_ERROR

    log_memory_usage()
    LOG.info("done")
    return EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main())
