from __future__ import annotations

import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

DEFAULT_WAKE_KEY = 224
DEFAULT_SLEEP_KEY = 223
DEFAULT_WAKE_RETRIES = 5
DEFAULT_LUMA_BLACK = 10.0
DEFAULT_WAKE_INTERVAL_SEC = 1.5


class ConfigError(Exception):
    """Missing or invalid config.toml."""


@dataclass(frozen=True)
class DeviceConfig:
    """adb/serial come from maa profile at runtime; wake_* are optional overrides."""

    adb: str
    serial: str
    wake_key: int = DEFAULT_WAKE_KEY
    sleep_key: int = DEFAULT_SLEEP_KEY
    wake_retries: int = DEFAULT_WAKE_RETRIES
    luma_black: float = DEFAULT_LUMA_BLACK
    wake_interval_sec: float = DEFAULT_WAKE_INTERVAL_SEC


@dataclass(frozen=True)
class NetworkConfig:
    proxy: str
    probe_timeout_sec: float
    probe_urls: tuple[str, ...]


@dataclass(frozen=True)
class MaaConfig:
    bin: str
    task: str
    extra_args: tuple[str, ...]
    timeout_sec: float
    log_dir: str
    profile: str = "default"


@dataclass(frozen=True)
class TelegramConfig:
    enabled: bool
    bot_token: str
    chat_id: str


@dataclass(frozen=True)
class CleanupConfig:
    mode: str
    boot_timeout_sec: float


@dataclass(frozen=True)
class ScheduleConfig:
    cron: str


@dataclass(frozen=True)
class Config:
    root: Path
    device: DeviceConfig
    network: NetworkConfig
    maa: MaaConfig
    telegram: TelegramConfig
    cleanup: CleanupConfig
    schedule: ScheduleConfig

    def log_dir(self) -> Path:
        path = Path(self.maa.log_dir)
        if not path.is_absolute():
            path = self.root / path
        return path


def project_root() -> Path:
    cwd = Path.cwd()
    if (cwd / "pixi.toml").is_file():
        return cwd.resolve()
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pixi.toml").is_file():
            return parent
    return cwd.resolve()


def _require_str(section: dict, key: str, *, allow_empty: bool = False) -> str:
    if key not in section:
        raise ConfigError(f"missing {key}")
    value = section[key]
    if not isinstance(value, str):
        raise ConfigError(f"{key} must be a string")
    if not allow_empty and not value.strip():
        raise ConfigError(f"{key} must not be empty")
    return value


def _require_bool(section: dict, key: str) -> bool:
    if key not in section:
        raise ConfigError(f"missing {key}")
    value = section[key]
    if not isinstance(value, bool):
        raise ConfigError(f"{key} must be a boolean")
    return value


def _require_number(section: dict, key: str) -> float:
    if key not in section:
        raise ConfigError(f"missing {key}")
    value = section[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{key} must be a number")
    return float(value)


def _require_int(section: dict, key: str) -> int:
    value = _require_number(section, key)
    if not float(value).is_integer():
        raise ConfigError(f"{key} must be an integer")
    return int(value)


def _optional_int(section: dict, key: str, default: int) -> int:
    if key not in section:
        return default
    return _require_int(section, key)


def _optional_number(section: dict, key: str, default: float) -> float:
    if key not in section:
        return default
    return _require_number(section, key)


def _parse_device(device_raw: dict | None) -> DeviceConfig:
    raw = device_raw or {}
    if "adb" in raw or "serial" in raw:
        raise ConfigError(
            "device.adb / device.serial are no longer used; "
            "they are read from $(maa dir config)/profiles/<profile>.json"
        )
    return DeviceConfig(
        adb="",  # filled by enrich_from_maa_profile
        serial="",
        wake_key=_optional_int(raw, "wake_key", DEFAULT_WAKE_KEY),
        sleep_key=_optional_int(raw, "sleep_key", DEFAULT_SLEEP_KEY),
        wake_retries=_optional_int(raw, "wake_retries", DEFAULT_WAKE_RETRIES),
        luma_black=_optional_number(raw, "luma_black", DEFAULT_LUMA_BLACK),
        wake_interval_sec=_optional_number(
            raw, "wake_interval_sec", DEFAULT_WAKE_INTERVAL_SEC
        ),
    )


def load_config(root: Path | None = None, *, require_telegram: bool = True) -> Config:
    root = (root or project_root()).resolve()
    path = root / "config.toml"
    if not path.is_file():
        raise ConfigError(f"missing {path}; run: pixi run init")

    with path.open("rb") as fh:
        raw = tomllib.load(fh)

    try:
        network_raw = raw["network"]
        maa_raw = raw["maa"]
        telegram_raw = raw["telegram"]
        cleanup_raw = raw["cleanup"]
        schedule_raw = raw["schedule"]
    except KeyError as exc:
        raise ConfigError(f"missing section {exc}") from exc

    device_raw = raw.get("device")
    if device_raw is not None and not isinstance(device_raw, dict):
        raise ConfigError("[device] must be a table")

    for name, section in (
        ("network", network_raw),
        ("maa", maa_raw),
        ("telegram", telegram_raw),
        ("cleanup", cleanup_raw),
        ("schedule", schedule_raw),
    ):
        if not isinstance(section, dict):
            raise ConfigError(f"[{name}] must be a table")

    probe_urls = network_raw.get("probe_urls")
    if not isinstance(probe_urls, list) or not probe_urls:
        raise ConfigError("network.probe_urls must be a non-empty list")
    if not all(isinstance(u, str) and u.strip() for u in probe_urls):
        raise ConfigError("network.probe_urls entries must be non-empty strings")

    extra_args = maa_raw.get("extra_args", [])
    if not isinstance(extra_args, list) or not all(isinstance(a, str) for a in extra_args):
        raise ConfigError("maa.extra_args must be a list of strings")

    cleanup_mode = _require_str(cleanup_raw, "mode")
    if cleanup_mode not in {"reboot", "sleep_only"}:
        raise ConfigError("cleanup.mode must be reboot or sleep_only")

    telegram = TelegramConfig(
        enabled=_require_bool(telegram_raw, "enabled"),
        bot_token=_require_str(telegram_raw, "bot_token", allow_empty=True),
        chat_id=_require_str(telegram_raw, "chat_id", allow_empty=True),
    )
    if require_telegram:
        if not telegram.enabled:
            raise ConfigError("telegram.enabled must be true")
        if not telegram.bot_token.strip() or not telegram.chat_id.strip():
            raise ConfigError("telegram.bot_token and telegram.chat_id are required")

    profile = maa_raw.get("profile", "default")
    if not isinstance(profile, str) or not profile.strip():
        raise ConfigError("maa.profile must be a non-empty string")

    return Config(
        root=root,
        device=_parse_device(device_raw),
        network=NetworkConfig(
            proxy=_require_str(network_raw, "proxy", allow_empty=True),
            probe_timeout_sec=_require_number(network_raw, "probe_timeout_sec"),
            probe_urls=tuple(probe_urls),
        ),
        maa=MaaConfig(
            bin=_require_str(maa_raw, "bin"),
            task=_require_str(maa_raw, "task"),
            extra_args=tuple(extra_args),
            timeout_sec=_require_number(maa_raw, "timeout_sec"),
            log_dir=_require_str(maa_raw, "log_dir"),
            profile=profile.strip(),
        ),
        telegram=telegram,
        cleanup=CleanupConfig(
            mode=cleanup_mode,
            boot_timeout_sec=_require_number(cleanup_raw, "boot_timeout_sec"),
        ),
        schedule=ScheduleConfig(
            cron=_require_str(schedule_raw, "cron"),
        ),
    )


def with_device(cfg: Config, *, adb: str, serial: str) -> Config:
    return replace(cfg, device=replace(cfg.device, adb=adb, serial=serial))
