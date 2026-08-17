from datetime import date, datetime
from pathlib import Path

import pytest

from maa_runner.config import LogsConfig
from maa_runner.logs import (
    append_section,
    archive_stale_weeks,
    delete_legacy_summaries,
    extract_archive_text,
    harvest_cron,
    iso_week_folder,
    list_archive_names,
    prepare_logs,
    resolve_7z,
    stale_logs_by_week,
    subtract_months,
    week_folder_thursday,
)


def test_iso_week_folder_uses_thursday_month():
    assert iso_week_folder(date(2026, 8, 17)) == "2026-08-week-34"


def test_subtract_months_and_week_thursday():
    assert subtract_months(date(2026, 8, 17), 3) == date(2026, 5, 17)
    assert week_folder_thursday("2026-08-week-34") == date(2026, 8, 20)


def test_stale_logs_skips_current_iso_week(tmp_path: Path):
    today = date(2026, 8, 17)
    (tmp_path / "2026-08-17.log").write_text("today\n", encoding="utf-8")
    last_week = tmp_path / "2026-08-16.log"
    last_week.write_text("sun\n", encoding="utf-8")
    (tmp_path / "cron.log").write_text("ignore\n", encoding="utf-8")
    groups = stale_logs_by_week(tmp_path, today)
    assert list(groups) == ["2026-08-week-33"]
    assert groups["2026-08-week-33"] == [last_week]


def test_delete_legacy_summaries(tmp_path: Path):
    old = tmp_path / "20260816-050000.summary.txt"
    old.write_text("Summary\n", encoding="utf-8")
    keep = tmp_path / "2026-08-16.log"
    keep.write_text("keep\n", encoding="utf-8")
    removed = delete_legacy_summaries(tmp_path)
    assert removed == [old]
    assert not old.exists()
    assert keep.exists()


def test_harvest_cron_appends_and_truncates(tmp_path: Path):
    dest = tmp_path / "2026-08-17.log"
    dest.write_text("maa\n", encoding="utf-8")
    (tmp_path / "cron.log").write_text("[1/5] device\n", encoding="utf-8")
    assert harvest_cron(tmp_path, dest, when=datetime(2026, 8, 17, 5, 25, 0))
    text = dest.read_text(encoding="utf-8")
    assert "maa" in text
    assert "======== 2026-08-17 05:25:00 runner ========" in text
    assert "[1/5] device" in text
    assert (tmp_path / "cron.log").read_text(encoding="utf-8") == ""


def test_archive_non_current_week_and_prune(tmp_path: Path):
    resolve_7z()
    today = date(2026, 8, 17)
    stale = tmp_path / "2026-08-16.log"
    stale.write_text("week 33\n", encoding="utf-8")
    current = tmp_path / "2026-08-17.log"
    current.write_text("week 34\n", encoding="utf-8")
    cfg = LogsConfig(compression_level=1, retain_months=3)

    archived = archive_stale_weeks(tmp_path, today, cfg)
    assert archived == ["2026-08-week-33"]
    assert not stale.exists()
    assert current.exists()

    archive = tmp_path / "archive.7z"
    names = list_archive_names(archive)
    assert "2026-08-week-33/2026-08-16.log" in names

    ancient = tmp_path / "2024-12-30.log"
    ancient.write_text("ancient\n", encoding="utf-8")
    archive_stale_weeks(tmp_path, today, cfg)
    names = list_archive_names(archive)
    assert not any(name.startswith("2024-12-week-") or name.startswith("2025-01-week-") for name in names)
    assert "2026-08-week-33/2026-08-16.log" in names
    assert not ancient.exists()


def test_prepare_logs_harvests_then_archives(tmp_path: Path):
    resolve_7z()
    today = date(2026, 8, 17)
    last_week = tmp_path / "2026-08-16.log"
    last_week.write_text("sun maa\n", encoding="utf-8")
    (tmp_path / "cron.log").write_text("leftover from sunday\n", encoding="utf-8")
    (tmp_path / "old.summary.txt").write_text("drop me\n", encoding="utf-8")
    cfg = LogsConfig(compression_level=1, retain_months=3)

    daily = prepare_logs(tmp_path, cfg, today)
    assert daily == tmp_path / "2026-08-17.log"
    assert not last_week.exists()
    assert not (tmp_path / "old.summary.txt").exists()
    assert (tmp_path / "cron.log").read_text(encoding="utf-8") == ""

    archive = tmp_path / "archive.7z"
    body = extract_archive_text(archive, "2026-08-week-33/2026-08-16.log")
    assert "sun maa" in body
    assert "leftover from sunday" in body


def test_append_same_day_twice(tmp_path: Path):
    path = tmp_path / "2026-08-17.log"
    append_section(path, "MAA", "first\n", when=datetime(2026, 8, 17, 5, 0, 0))
    append_section(path, "MAA", "second\n", when=datetime(2026, 8, 17, 17, 0, 0))
    text = path.read_text(encoding="utf-8")
    assert text.count(" MAA ========") == 2
    assert "first" in text and "second" in text


def test_load_config_logs_optional(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from maa_runner.config import load_config

    (tmp_path / "pixi.toml").write_text("[workspace]\nname='t'\n", encoding="utf-8")
    (tmp_path / "config.toml").write_text(
        """
[network]
proxy = ""
probe_timeout_sec = 1
probe_urls = ["https://example.com"]

[maa]
bin = "/bin/maa"
task = "daily"
extra_args = []
timeout_sec = 10
log_dir = "logs"

[telegram]
enabled = true
bot_token = "t"
chat_id = "1"

[cleanup]
mode = "reboot"
boot_timeout_sec = 10

[schedule]
cron = "0 5 * * *"
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    cfg = load_config(tmp_path)
    assert cfg.logs.compression_level == 9
    assert cfg.logs.retain_months == 3
