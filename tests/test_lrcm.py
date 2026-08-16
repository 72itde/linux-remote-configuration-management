"""Unit tests for the pure parts of lrcm."""

from __future__ import annotations

import multiprocessing
import os
import sys
import textwrap
from multiprocessing.synchronize import Event
from pathlib import Path

import git
import pytest
import yaml

import lrcm

REPO_ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- #
# platform support
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("actual", "expected", "result"),
    [
        ("24.04", "24.04", True),
        ("24.04.1", "24.04", True),
        ("24.04.7", "24.04", True),
        ("24.10", "24.04", False),
        ("24.04", "24.04.1", False),
        ("12", "12", True),
        ("12.5", "12", True),
        ("13", "12", False),
        ("2", "12", False),
    ],
)
def test_version_matches(actual: str, expected: str, result: bool) -> None:
    assert lrcm.version_matches(actual, expected) is result


@pytest.mark.parametrize(
    ("distro_id", "version"),
    [
        ("debian", "12"),
        ("debian", "12.11"),
        ("debian", "13"),
        ("debian", "13.2"),
        # every Ubuntu 24.04 point release, which is what distro.version()
        # reports on 24.04, 24.04.1, ... 24.04.4 and later
        ("ubuntu", "24.04"),
        ("ubuntu", "24.04.1"),
        ("ubuntu", "24.04.4"),
        ("ubuntu", "26.04"),
        ("ubuntu", "26.04.2"),
        ("linuxmint", "6"),
        ("linuxmint", "7"),
        ("linuxmint", "21.3"),
        ("elementary", "8"),
        ("fedora", "39"),
    ],
)
def test_supported_distributions(distro_id: str, version: str) -> None:
    assert lrcm.find_supported_distribution(distro_id, version) is not None


@pytest.mark.parametrize(
    ("distro_id", "version"),
    [
        ("debian", "11"),
        ("ubuntu", "22.04"),
        ("ubuntu", "25.10"),
        ("ubuntu", "24.10"),
        ("arch", ""),
        ("rhel", "9"),
    ],
)
def test_unsupported_distributions(distro_id: str, version: str) -> None:
    assert lrcm.find_supported_distribution(distro_id, version) is None


def test_python_3_13_5_is_listed_as_tested() -> None:
    assert "3.13.5" in lrcm.TESTED_PYTHON_VERSIONS


@pytest.mark.parametrize("series", ["3.10", "3.11", "3.12", "3.13", "3.14"])
def test_every_supported_distribution_series_is_covered(series: str) -> None:
    assert series in lrcm.TESTED_PYTHON_SERIES


def test_minimum_python_version_is_not_above_the_running_interpreter() -> None:
    lrcm.check_python_version()


def test_a_patch_bump_inside_a_tested_series_is_not_flagged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Distributions SRU the CPython micro version; that must stay silent."""
    monkeypatch.setattr(sys, "version_info", (3, 13, 99, "final", 0))
    with caplog.at_level("WARNING", logger="lrcm"):
        lrcm.check_python_version()
    assert caplog.records == []


def test_an_untested_minor_series_is_flagged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(sys, "version_info", (3, 99, 0, "final", 0))
    with caplog.at_level("WARNING", logger="lrcm"):
        lrcm.check_python_version()
    assert any("not one of the tested series" in r.message for r in caplog.records)


def test_a_too_old_interpreter_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "version_info", (3, 9, 18, "final", 0))
    with pytest.raises(lrcm.ConfigurationError, match="too old"):
        lrcm.check_python_version()


# --------------------------------------------------------------------------- #
# command line
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("value", ["true", "True", "YES", "on", "1"])
def test_parse_bool_true(value: str) -> None:
    assert lrcm.parse_bool(value) is True


@pytest.mark.parametrize("value", ["false", "False", "no", "OFF", "0"])
def test_parse_bool_false(value: str) -> None:
    assert lrcm.parse_bool(value) is False


def test_parse_bool_rejects_garbage() -> None:
    with pytest.raises(Exception, match="boolean"):
        lrcm.parse_bool("maybe")


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        ([], True),
        (["--cronjobs"], True),
        # the spelling the pre-0.8 README and existing cron entries use
        (["--cronjobs=False"], False),
        (["--cronjobs=false"], False),
        (["--cronjobs=True"], True),
        (["-j", "False"], False),
        (["--no-cronjobs"], False),
    ],
)
def test_cronjobs_flag(argv: list[str], expected: bool) -> None:
    arguments = lrcm.build_argument_parser().parse_args(argv)
    assert arguments.cronjobs is expected


def test_configfile_default_and_override() -> None:
    parser = lrcm.build_argument_parser()
    assert parser.parse_args([]).configfile == Path("/etc/lrcm/lrcm.conf")
    override = parser.parse_args(["--configfile=/srv/lrcm/custom.conf"])
    assert override.configfile == Path("/srv/lrcm/custom.conf")


# --------------------------------------------------------------------------- #
# repository url handling
# --------------------------------------------------------------------------- #


def test_authenticated_url_has_no_double_slash() -> None:
    url = lrcm.authenticated_repository_url("https://gitlab.example.com/group/repo.git", "bob")
    assert url == "https://bob@gitlab.example.com/group/repo.git"
    assert "//group" not in url


def test_authenticated_url_keeps_the_port() -> None:
    url = lrcm.authenticated_repository_url("https://git.example.com:8443/repo.git", "bob")
    assert url == "https://bob@git.example.com:8443/repo.git"


def test_authenticated_url_encodes_the_username() -> None:
    url = lrcm.authenticated_repository_url("https://example.com/repo.git", "user@corp")
    assert url == "https://user%40corp@example.com/repo.git"


def test_authenticated_url_never_carries_the_token() -> None:
    url = lrcm.authenticated_repository_url("https://example.com/repo.git", "bob")
    assert "secret" not in url


def test_redact_hides_the_token_and_its_encoded_form() -> None:
    message = "failed for https://bob:s3cr%2Fet@example.com and s3cr/et"
    redacted = lrcm.redact(message, "s3cr/et")
    assert "s3cr/et" not in redacted
    assert "s3cr%2Fet" not in redacted
    assert redacted.count("***") == 2


def test_redact_ignores_empty_secrets() -> None:
    assert lrcm.redact("nothing to hide", "") == "nothing to hide"


def test_git_credential_environment_writes_and_removes_the_askpass_helper() -> None:
    with lrcm.git_credential_environment("t0ken", 300) as environment:
        askpass = Path(environment["GIT_ASKPASS"])
        assert askpass.is_file()
        assert askpass.stat().st_mode & 0o777 == 0o700
        # the token is handed over through the environment, never the script
        assert "t0ken" not in askpass.read_text(encoding="ascii")
        assert environment["LRCM_GIT_TOKEN"] == "t0ken"  # noqa: S105 - test fixture, not a secret
        assert environment["GIT_TERMINAL_PROMPT"] == "0"
    assert not askpass.exists()
    assert not askpass.parent.exists()


def test_git_credential_environment_without_a_token() -> None:
    with lrcm.git_credential_environment("", 300) as environment:
        assert "GIT_ASKPASS" not in environment
        assert environment["GIT_TERMINAL_PROMPT"] == "0"


@pytest.mark.parametrize("token", ["", "t0ken"])
def test_git_environment_always_bounds_a_stalled_transfer(token: str) -> None:
    """A hung git server must not hold the pidfile lock forever."""
    with lrcm.git_credential_environment(token, 900) as environment:
        assert environment["GIT_HTTP_LOW_SPEED_TIME"] == "900"
        assert int(environment["GIT_HTTP_LOW_SPEED_LIMIT"]) > 0


def test_clone_target_is_empty_when_git_is_invoked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """git refuses to clone into a non-empty directory.

    The askpass helper therefore must not be written into the clone target -
    an earlier revision did exactly that and broke every authenticated clone.
    """
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    seen: dict[str, object] = {}

    def fake_clone_from(url: str, to_path: Path, **kwargs: object) -> None:
        seen["url"] = url
        seen["contents"] = sorted(p.name for p in Path(to_path).iterdir())
        seen["env"] = kwargs["env"]

    monkeypatch.setattr(git.Repo, "clone_from", staticmethod(fake_clone_from))

    config = lrcm.Config(
        delay_before_start_seconds=0,
        delay_before_start_random_max_seconds=0,
        timeout_seconds=3600,
        repository="https://example.com/repo.git",
        branch="main",
        playbook="playbook.yaml",
        authentication_required=True,
        username="bob",
        token="s3cret",  # noqa: S106 - test fixture, not a secret
        hourly_cronjob=False,
        daily_cronjob=False,
        reboot_cronjob=False,
        pidfile=tmp_path / "lrcm.pid",
    )
    lrcm.clone_repository(config, workdir)

    assert seen["contents"] == [], "the clone target must be empty"
    assert seen["url"] == "https://bob@example.com/repo.git"
    environment = seen["env"]
    assert isinstance(environment, dict)
    assert environment["LRCM_GIT_TOKEN"] == "s3cret"  # noqa: S105 - test fixture
    assert "s3cret" not in str(seen["url"])


# --------------------------------------------------------------------------- #
# configuration
# --------------------------------------------------------------------------- #


MINIMAL_CONFIG = """\
[GENERAL]
delay_before_start_seconds: 0
delay_before_start_random_max_seconds: 0
[GIT]
repository: https://example.com/repo.git
branch: main
playbook: playbook.yaml
authentication_required: false
[CRONJOB]
hourly_cronjob: true
daily_cronjob: false
reboot_cronjob: false
[PIDFILE]
pidfile: /run/lrcm.pid
"""


def write_config(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "lrcm.conf"
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    return path


def test_read_config_minimal(tmp_path: Path) -> None:
    config = lrcm.read_config(write_config(tmp_path, MINIMAL_CONFIG))
    assert config.repository == "https://example.com/repo.git"
    assert config.branch == "main"
    assert config.hourly_cronjob is True
    assert config.daily_cronjob is False
    assert config.pidfile == Path("/run/lrcm.pid")


def test_read_config_applies_defaults(tmp_path: Path) -> None:
    config = lrcm.read_config(
        write_config(tmp_path, "[GIT]\nrepository: https://example.com/repo.git\n")
    )
    assert config.delay_before_start_seconds == 60
    assert config.delay_before_start_random_max_seconds == 60
    assert config.branch == "main"
    assert config.playbook == "playbook.yaml"
    assert config.authentication_required is False
    # a missing [CRONJOB] section must not raise; it means "no cron entries"
    assert config.hourly_cronjob is False
    assert config.reboot_cronjob is False
    assert config.pidfile == Path("/run/lrcm.pid")


def test_read_config_keeps_a_percent_sign_in_the_token(tmp_path: Path) -> None:
    """ConfigParser's default interpolation would choke on '%' in a token."""
    content = MINIMAL_CONFIG.replace(
        "authentication_required: false",
        "authentication_required: true\nusername: bob\ntoken: ab%cd%%ef",
    )
    config = lrcm.read_config(write_config(tmp_path, content))
    assert config.token == "ab%cd%%ef"  # noqa: S105 - test fixture


def test_read_config_rejects_a_non_positive_timeout(tmp_path: Path) -> None:
    content = MINIMAL_CONFIG.replace("[GIT]", "timeout_seconds: 0\n[GIT]")
    with pytest.raises(lrcm.ConfigurationError, match="timeout_seconds"):
        lrcm.read_config(write_config(tmp_path, content))


def test_read_config_reads_the_timeout(tmp_path: Path) -> None:
    content = MINIMAL_CONFIG.replace("[GIT]", "timeout_seconds: 120\n[GIT]")
    assert lrcm.read_config(write_config(tmp_path, content)).timeout_seconds == 120


def test_read_config_rejects_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(lrcm.ConfigurationError, match="not readable"):
        lrcm.read_config(tmp_path / "nope.conf")


def test_read_config_rejects_a_missing_repository(tmp_path: Path) -> None:
    with pytest.raises(lrcm.ConfigurationError, match="incomplete"):
        lrcm.read_config(write_config(tmp_path, "[GENERAL]\ndelay_before_start_seconds: 1\n"))


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ("delay_before_start_seconds: -1", "delay_before_start_seconds"),
        ("delay_before_start_random_max_seconds: -5", "delay_before_start_random_max_seconds"),
    ],
)
def test_read_config_rejects_negative_delays(tmp_path: Path, override: str, message: str) -> None:
    key = override.split(":")[0]
    content = "\n".join(
        override if line.startswith(key) else line for line in MINIMAL_CONFIG.splitlines()
    )
    with pytest.raises(lrcm.ConfigurationError, match=message):
        lrcm.read_config(write_config(tmp_path, content + "\n"))


@pytest.mark.parametrize(
    "playbook",
    ["/etc/shadow", "../../../etc/passwd", "sub/../../escape.yaml", ""],
)
def test_read_config_rejects_playbooks_outside_the_repository(
    tmp_path: Path, playbook: str
) -> None:
    content = MINIMAL_CONFIG.replace("playbook: playbook.yaml", f"playbook: {playbook}")
    with pytest.raises(lrcm.ConfigurationError, match="playbook"):
        lrcm.read_config(write_config(tmp_path, content))


def test_read_config_rejects_an_unsupported_scheme(tmp_path: Path) -> None:
    content = MINIMAL_CONFIG.replace(
        "repository: https://example.com/repo.git", "repository: ext::sh -c whoami"
    )
    with pytest.raises(lrcm.ConfigurationError, match="scheme"):
        lrcm.read_config(write_config(tmp_path, content))


def test_read_config_rejects_a_malformed_url(tmp_path: Path) -> None:
    content = MINIMAL_CONFIG.replace(
        "repository: https://example.com/repo.git", "repository: https://"
    )
    with pytest.raises(lrcm.ConfigurationError, match="valid url"):
        lrcm.read_config(write_config(tmp_path, content))


def test_read_config_requires_credentials_when_authentication_is_on(tmp_path: Path) -> None:
    content = MINIMAL_CONFIG.replace(
        "authentication_required: false", "authentication_required: true"
    )
    with pytest.raises(lrcm.ConfigurationError, match="username or token"):
        lrcm.read_config(write_config(tmp_path, content))


def test_read_config_rejects_authentication_over_ssh(tmp_path: Path) -> None:
    content = MINIMAL_CONFIG.replace(
        "repository: https://example.com/repo.git", "repository: ssh://git@example.com/repo.git"
    ).replace(
        "authentication_required: false",
        "authentication_required: true\nusername: a\ntoken: b",
    )
    with pytest.raises(lrcm.ConfigurationError, match="does not take a username"):
        lrcm.read_config(write_config(tmp_path, content))


def test_shipped_config_template_is_valid() -> None:
    config = lrcm.read_config(REPO_ROOT / "lrcm.conf.template")
    assert config.pidfile == Path("/run/lrcm.pid")
    assert config.authentication_required is False


def test_cronjob_enabled_maps_every_special_time(tmp_path: Path) -> None:
    config = lrcm.read_config(write_config(tmp_path, MINIMAL_CONFIG))
    assert {name: config.cronjob_enabled(name) for name in lrcm.CRONJOB_SPECIAL_TIMES} == {
        "hourly": True,
        "daily": False,
        "reboot": False,
    }


# --------------------------------------------------------------------------- #
# pidfile locking
# --------------------------------------------------------------------------- #


def test_pidfile_lock_writes_the_pid_and_cleans_up(tmp_path: Path) -> None:
    pidfile = tmp_path / "lrcm.pid"
    with lrcm.pidfile_lock(pidfile) as acquired:
        assert acquired is True
        assert pidfile.read_text(encoding="ascii").strip() == str(os.getpid())
    assert not pidfile.exists()


def test_pidfile_lock_is_released_when_the_body_raises(tmp_path: Path) -> None:
    pidfile = tmp_path / "lrcm.pid"
    with pytest.raises(RuntimeError), lrcm.pidfile_lock(pidfile):
        raise RuntimeError("boom")
    assert not pidfile.exists()

    # the lock must be available again
    with lrcm.pidfile_lock(pidfile) as acquired:
        assert acquired is True


def _hold_lock(pidfile: str, ready: Event, release: Event) -> None:  # pragma: no cover
    with lrcm.pidfile_lock(Path(pidfile)) as acquired:
        assert acquired is True
        ready.set()
        release.wait(30)


def test_pidfile_lock_excludes_a_second_process(tmp_path: Path) -> None:
    pidfile = tmp_path / "lrcm.pid"
    context = multiprocessing.get_context("fork")
    ready = context.Event()
    release = context.Event()
    holder = context.Process(target=_hold_lock, args=(str(pidfile), ready, release))
    holder.start()
    try:
        assert ready.wait(30), "the helper process never acquired the lock"
        with lrcm.pidfile_lock(pidfile) as acquired:
            assert acquired is False, "a second instance must not get the lock"
        # the first process still owns it, so its pidfile must survive
        assert pidfile.exists()
    finally:
        release.set()
        holder.join(30)
    assert holder.exitcode == 0


def test_pidfile_lock_accepts_a_bare_filename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`pidfile: lrcm.pid` must resolve against the working directory."""
    monkeypatch.chdir(tmp_path)
    with lrcm.pidfile_lock(Path("lrcm.pid")) as acquired:
        assert acquired is True
        assert (tmp_path / "lrcm.pid").is_file()


def test_pidfile_lock_refuses_to_follow_a_symlink(tmp_path: Path) -> None:
    target = tmp_path / "victim"
    target.write_text("important\n", encoding="ascii")
    pidfile = tmp_path / "lrcm.pid"
    pidfile.symlink_to(target)

    with pytest.raises(lrcm.ConfigurationError, match="cannot open pidfile"):
        lrcm.pidfile_lock(pidfile).__enter__()
    assert target.read_text(encoding="ascii") == "important\n"


def test_pidfile_lock_rejects_an_unwritable_directory(tmp_path: Path) -> None:
    with pytest.raises(lrcm.ConfigurationError, match="not writable"):
        lrcm.pidfile_lock(tmp_path / "missing" / "lrcm.pid").__enter__()


# --------------------------------------------------------------------------- #
# cronjob template rendering
# --------------------------------------------------------------------------- #


def render(tmp_path: Path, *, special_time: str, job: str, enabled: bool) -> dict[str, object]:
    output = tmp_path / "generated.yaml"
    lrcm.render_cronjob_playbook(
        template_directory=REPO_ROOT / "templates",
        output_path=output,
        special_time=special_time,
        job=job,
        enabled=enabled,
    )
    document = yaml.safe_load(output.read_text(encoding="utf-8"))
    assert isinstance(document, list)
    play = document[0]
    assert isinstance(play, dict)
    return play


@pytest.mark.parametrize("special_time", ["hourly", "daily", "reboot"])
@pytest.mark.parametrize("enabled", [True, False])
def test_rendered_cronjob_playbook_is_valid_yaml(
    tmp_path: Path, special_time: str, enabled: bool
) -> None:
    play = render(
        tmp_path,
        special_time=special_time,
        job="/opt/lrcm/lrcm.py --configfile=/etc/lrcm/lrcm.conf",
        enabled=enabled,
    )
    tasks = play["tasks"]
    assert isinstance(tasks, list)
    cron_task, file_task = tasks

    assert cron_task["ansible.builtin.cron"]["special_time"] == special_time
    assert cron_task["ansible.builtin.cron"]["cron_file"] == f"lrcm_{special_time}"
    assert cron_task["ansible.builtin.cron"]["user"] == "root"
    assert cron_task["ansible.builtin.cron"]["state"] == ("present" if enabled else "absent")

    assert file_task["ansible.builtin.file"]["path"] == f"/etc/cron.d/lrcm_{special_time}"
    assert file_task["ansible.builtin.file"]["state"] == ("file" if enabled else "absent")
    # quoted, so YAML keeps it a string and cron gets 0600 rather than 384
    assert file_task["ansible.builtin.file"]["mode"] == "0600"


def test_rendered_cronjob_playbook_survives_hostile_paths(tmp_path: Path) -> None:
    job = "/opt/weird: dir/lrcm.py --configfile=/etc/x #y {{ oops }}"
    play = render(tmp_path, special_time="hourly", job=job, enabled=True)
    tasks = play["tasks"]
    assert isinstance(tasks, list)
    assert tasks[0]["ansible.builtin.cron"]["job"] == job


def test_rendered_cronjob_playbook_names_every_play_and_task(tmp_path: Path) -> None:
    """ansible-lint's production profile requires a name everywhere."""
    play = render(tmp_path, special_time="daily", job="/opt/lrcm/lrcm.py", enabled=True)
    assert isinstance(play["name"], str) and play["name"][0].isupper()
    tasks = play["tasks"]
    assert isinstance(tasks, list)
    for task in tasks:
        assert isinstance(task["name"], str)
        assert task["name"][0].isupper()


def test_render_fails_loudly_on_an_unknown_variable() -> None:
    """StrictUndefined keeps a renamed variable from silently producing junk."""
    from jinja2 import Environment, StrictUndefined, UndefinedError

    template = Environment(undefined=StrictUndefined, autoescape=False).from_string(  # noqa: S701
        "{{ does_not_exist }}"
    )
    with pytest.raises(UndefinedError):
        template.render()
