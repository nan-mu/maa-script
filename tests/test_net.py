from pathlib import Path

import pytest

from maa_runner.config import ConfigError, NetworkConfig, load_config, with_proxy
from maa_runner.net import ProbeResult, proxy_candidates, select_working_proxy


def _write_minimal_config(root: Path, network_block: str) -> None:
    (root / "pixi.toml").write_text("[workspace]\nname='t'\n", encoding="utf-8")
    (root / "config.toml").write_text(
        f"""
{network_block}

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


def test_load_proxies_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _write_minimal_config(
        tmp_path,
        """
[network]
proxies = ["http://a:1", "http://b:2"]
probe_timeout_sec = 1
probe_urls = ["https://example.com"]
""",
    )
    monkeypatch.chdir(tmp_path)
    cfg = load_config(tmp_path)
    assert cfg.network.proxies == ("http://a:1", "http://b:2")
    assert cfg.network.proxy == "http://a:1"


def test_load_legacy_proxy_string(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _write_minimal_config(
        tmp_path,
        """
[network]
proxy = "http://legacy:7890"
probe_timeout_sec = 1
probe_urls = ["https://example.com"]
""",
    )
    monkeypatch.chdir(tmp_path)
    cfg = load_config(tmp_path)
    assert cfg.network.proxies == ("http://legacy:7890",)
    assert cfg.network.proxy == "http://legacy:7890"


def test_proxy_candidates_append_direct():
    net = NetworkConfig(
        proxies=("http://a:1", "http://b:2"),
        proxy="http://a:1",
        probe_timeout_sec=1,
        probe_urls=("https://example.com",),
    )
    from maa_runner.config import (
        CleanupConfig,
        Config,
        DeviceConfig,
        MaaConfig,
        ScheduleConfig,
        TelegramConfig,
    )

    cfg = Config(
        root=Path("/tmp"),
        device=DeviceConfig(adb="", serial=""),
        network=net,
        maa=MaaConfig(bin="maa", task="daily", extra_args=(), timeout_sec=1, log_dir="logs"),
        telegram=TelegramConfig(enabled=True, bot_token="t", chat_id="1"),
        cleanup=CleanupConfig(mode="reboot", boot_timeout_sec=1),
        schedule=ScheduleConfig(cron="0 5 * * *"),
    )
    assert proxy_candidates(cfg) == ("http://a:1", "http://b:2", "")


def test_select_working_proxy_falls_through(monkeypatch: pytest.MonkeyPatch):
    from maa_runner.config import (
        CleanupConfig,
        Config,
        DeviceConfig,
        MaaConfig,
        ScheduleConfig,
        TelegramConfig,
    )

    cfg = Config(
        root=Path("/tmp"),
        device=DeviceConfig(adb="", serial=""),
        network=NetworkConfig(
            proxies=("http://bad:1", "http://good:2"),
            proxy="http://bad:1",
            probe_timeout_sec=1,
            probe_urls=("https://a.example", "https://b.example"),
        ),
        maa=MaaConfig(bin="maa", task="daily", extra_args=(), timeout_sec=1, log_dir="logs"),
        telegram=TelegramConfig(enabled=True, bot_token="t", chat_id="1"),
        cleanup=CleanupConfig(mode="reboot", boot_timeout_sec=1),
        schedule=ScheduleConfig(cron="0 5 * * *"),
    )

    def fake_probe_all(config, *, proxy=None):
        chosen = config.network.proxy if proxy is None else proxy
        ok = chosen == "http://good:2"
        return [
            ProbeResult(url=u, ok=ok, detail="200" if ok else "fail")
            for u in config.network.probe_urls
        ]

    monkeypatch.setattr("maa_runner.net.probe_all", fake_probe_all)
    winner, attempts = select_working_proxy(cfg)
    assert winner is not None
    assert winner.proxy == "http://good:2"
    assert [a.proxy for a in attempts] == ["http://bad:1", "http://good:2"]
    assert with_proxy(cfg, winner.proxy).network.proxy == "http://good:2"


def test_select_working_proxy_uses_direct(monkeypatch: pytest.MonkeyPatch):
    from maa_runner.config import (
        CleanupConfig,
        Config,
        DeviceConfig,
        MaaConfig,
        ScheduleConfig,
        TelegramConfig,
    )

    cfg = Config(
        root=Path("/tmp"),
        device=DeviceConfig(adb="", serial=""),
        network=NetworkConfig(
            proxies=("http://bad:1",),
            proxy="http://bad:1",
            probe_timeout_sec=1,
            probe_urls=("https://example.com",),
        ),
        maa=MaaConfig(bin="maa", task="daily", extra_args=(), timeout_sec=1, log_dir="logs"),
        telegram=TelegramConfig(enabled=True, bot_token="t", chat_id="1"),
        cleanup=CleanupConfig(mode="reboot", boot_timeout_sec=1),
        schedule=ScheduleConfig(cron="0 5 * * *"),
    )

    def fake_probe_all(config, *, proxy=None):
        chosen = config.network.proxy if proxy is None else proxy
        ok = chosen == ""
        return [
            ProbeResult(url=u, ok=ok, detail="200" if ok else "fail")
            for u in config.network.probe_urls
        ]

    monkeypatch.setattr("maa_runner.net.probe_all", fake_probe_all)
    winner, attempts = select_working_proxy(cfg)
    assert winner is not None
    assert winner.proxy == ""
    assert winner.label == "直连"
    assert [a.proxy for a in attempts] == ["http://bad:1", ""]


def test_missing_proxy_keys_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _write_minimal_config(
        tmp_path,
        """
[network]
probe_timeout_sec = 1
probe_urls = ["https://example.com"]
""",
    )
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError, match="proxies"):
        load_config(tmp_path)
