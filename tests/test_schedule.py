from pathlib import Path

from maa_runner.schedule import (
    MARKER,
    build_cron_line,
    remove_managed_lines,
    upsert_managed_line,
)


def test_build_cron_line_is_self_contained():
    line = build_cron_line(
        "0 4 * * *",
        Path("/Users/nan/maa-script"),
        Path("/Users/nan/.pixi/bin/pixi"),
    )
    assert line == (
        "0 4 * * * cd /Users/nan/maa-script && /Users/nan/.pixi/bin/pixi run daily "
        ">> /Users/nan/maa-script/logs/cron.log 2>&1 # MAA_RUNNER_MANAGED"
    )


def test_upsert_into_empty_crontab():
    line = "0 4 * * * cd /tmp/p && /bin/pixi run daily >> /tmp/p/logs/cron.log 2>&1 # MAA_RUNNER_MANAGED"
    assert upsert_managed_line("", line) == line + "\n"


def test_upsert_replaces_existing_managed_line_without_duplicating():
    other = "0 1 * * * /usr/bin/true"
    old = (
        "0 3 * * * cd /old && /bin/pixi run daily >> /old/logs/cron.log 2>&1 "
        f"# {MARKER}"
    )
    new = (
        "0 4 * * * cd /new && /bin/pixi run daily >> /new/logs/cron.log 2>&1 "
        f"# {MARKER}"
    )
    crontab = f"{other}\n{old}\n"
    updated = upsert_managed_line(crontab, new)
    assert updated == f"{other}\n{new}\n"
    assert updated.count(MARKER) == 1


def test_upsert_collapses_duplicate_managed_lines():
    a = f"0 3 * * * echo a # {MARKER}"
    b = f"0 4 * * * echo b # {MARKER}"
    new = f"0 5 * * * echo c # {MARKER}"
    updated = upsert_managed_line(f"{a}\n{b}\n", new)
    assert updated == new + "\n"


def test_remove_managed_lines_keeps_others():
    other = "MAILTO=root"
    managed = f"0 4 * * * pixi run daily # {MARKER}"
    crontab = f"{other}\n{managed}\n"
    assert remove_managed_lines(crontab) == f"{other}\n"


def test_remove_managed_lines_empty_when_only_managed():
    crontab = f"0 4 * * * pixi run daily # {MARKER}\n"
    assert remove_managed_lines(crontab) == ""


def test_uninstall_is_noop_without_marker():
    crontab = "0 1 * * * /usr/bin/true\n"
    assert remove_managed_lines(crontab) == crontab
