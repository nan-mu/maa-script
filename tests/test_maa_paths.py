import json
from pathlib import Path

import pytest

from maa_runner.config import ConfigError, MaaConfig, load_config
from maa_runner.maa import find_task_file, read_connection


def _cfg(tmp_path: Path, bin_path: str = "/usr/bin/maa"):
    from maa_runner.config import (
        CleanupConfig,
        Config,
        DeviceConfig,
        NetworkConfig,
        ScheduleConfig,
        TelegramConfig,
    )

    return Config(
        root=tmp_path,
        device=DeviceConfig(adb="", serial=""),
        network=NetworkConfig(proxy="", probe_timeout_sec=1, probe_urls=("https://example.com",)),
        maa=MaaConfig(
            bin=bin_path,
            task="daily",
            extra_args=(),
            timeout_sec=10,
            log_dir="logs",
            profile="default",
        ),
        telegram=TelegramConfig(enabled=True, bot_token="t", chat_id="1"),
        cleanup=CleanupConfig(mode="reboot", boot_timeout_sec=10),
        schedule=ScheduleConfig(cron="0 5 * * *"),
    )


def test_read_connection_from_profile_json(tmp_path: Path):
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "default.json").write_text(
        json.dumps(
            {
                "connection": {
                    "preset": "ADB",
                    "adb_path": "/opt/homebrew/bin/adb",
                    "device": "cab5aaea",
                }
            }
        ),
        encoding="utf-8",
    )
    adb, serial = read_connection(_cfg(tmp_path), config_dir=tmp_path)
    assert adb == "/opt/homebrew/bin/adb"
    assert serial == "cab5aaea"


def test_read_connection_address_fallback(tmp_path: Path):
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "default.json").write_text(
        json.dumps({"connection": {"adb_path": "/bin/adb", "address": "127.0.0.1:5555"}}),
        encoding="utf-8",
    )
    adb, serial = read_connection(_cfg(tmp_path), config_dir=tmp_path)
    assert adb == "/bin/adb"
    assert serial == "127.0.0.1:5555"


def test_find_task_file_accepts_toml(tmp_path: Path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    path = tasks / "daily.toml"
    path.write_text("{}", encoding="utf-8")
    assert find_task_file(_cfg(tmp_path), config_dir=tmp_path) == path


def test_find_task_file_missing(tmp_path: Path):
    (tmp_path / "tasks").mkdir()
    with pytest.raises(Exception, match="missing tasks/daily"):
        find_task_file(_cfg(tmp_path), config_dir=tmp_path)


def test_load_config_rejects_device_adb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path
    (root / "pixi.toml").write_text("[workspace]\nname='t'\n", encoding="utf-8")
    (root / "config.toml").write_text(
        """
[device]
adb = "adb"
serial = ""

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
    monkeypatch.chdir(root)
    with pytest.raises(ConfigError, match="no longer used"):
        load_config(root)
