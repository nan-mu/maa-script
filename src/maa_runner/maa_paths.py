from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

from maa_runner.config import Config, ConfigError, with_device

TASK_EXTENSIONS = (".toml", ".json", ".yml", ".yaml")


class MaaDirError(Exception):
    """maa dir / profile / task lookup failure."""


def maa_dir(cfg: Config, kind: str, *, timeout: float = 15) -> Path:
    """Run ``maa dir <kind>`` (e.g. config, log) and return the path."""
    try:
        proc = subprocess.run(
            [cfg.maa.bin, "dir", kind],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise MaaDirError(f"maa not found: {cfg.maa.bin}") from exc
    except subprocess.TimeoutExpired as exc:
        raise MaaDirError(f"maa dir {kind} timed out") from exc
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        raise MaaDirError(f"maa dir {kind} failed: {err}")
    text = (proc.stdout or "").strip()
    if not text:
        raise MaaDirError(f"maa dir {kind} returned empty path")
    return Path(text.splitlines()[0].strip())


def _load_profile_dict(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
    elif path.suffix.lower() in {".toml"}:
        import tomllib

        data = tomllib.loads(text)
    else:
        raise MaaDirError(f"unsupported profile format: {path}")
    if not isinstance(data, dict):
        raise MaaDirError(f"profile root must be an object: {path}")
    return data


def profile_path(cfg: Config, config_dir: Path | None = None) -> Path:
    root = config_dir or maa_dir(cfg, "config")
    profiles = root / "profiles"
    name = cfg.maa.profile
    for ext in (".json", ".toml"):
        candidate = profiles / f"{name}{ext}"
        if candidate.is_file():
            return candidate
    raise MaaDirError(
        f"missing profile {name}.json/.toml under {profiles}"
    )


def read_connection(cfg: Config, config_dir: Path | None = None) -> tuple[str, str]:
    """Return (adb_path, serial) from maa profile connection."""
    path = profile_path(cfg, config_dir)
    data = _load_profile_dict(path)
    connection = data.get("connection")
    if not isinstance(connection, dict):
        raise MaaDirError(f"profile missing connection object: {path}")
    adb = connection.get("adb_path")
    if not isinstance(adb, str) or not adb.strip():
        raise MaaDirError(f"connection.adb_path missing in {path}")
    serial = ""
    for key in ("device", "address", "adb_serial", "serial"):
        value = connection.get(key)
        if isinstance(value, str) and value.strip():
            serial = value.strip()
            break
    return adb.strip(), serial


def enrich_from_maa_profile(cfg: Config) -> Config:
    try:
        adb, serial = read_connection(cfg)
    except MaaDirError as exc:
        raise ConfigError(str(exc)) from exc
    return with_device(cfg, adb=adb, serial=serial)


def find_task_file(cfg: Config, config_dir: Path | None = None) -> Path:
    root = config_dir or maa_dir(cfg, "config")
    tasks = root / "tasks"
    name = cfg.maa.task
    found = [tasks / f"{name}{ext}" for ext in TASK_EXTENSIONS if (tasks / f"{name}{ext}").is_file()]
    if not found:
        exts = "/".join(TASK_EXTENSIONS)
        raise MaaDirError(f"missing tasks/{name}{{{exts}}} under {root}")
    return found[0]


def find_maa_log(log_root: Path, started: datetime, ended: datetime | None = None) -> Path | None:
    """Locate ``YYYY/MM/DD/HH:MM:SS.log`` under maa log dir for this run."""
    day_dir = log_root / f"{started:%Y}" / f"{started:%m}" / f"{started:%d}"
    exact = day_dir / f"{started:%H:%M:%S}.log"
    if exact.is_file():
        return exact
    if not day_dir.is_dir():
        return None
    candidates: list[Path] = []
    for path in day_dir.glob("*.log"):
        try:
            stamp = datetime.strptime(
                f"{started:%Y-%m-%d} {path.stem}", "%Y-%m-%d %H:%M:%S"
            )
        except ValueError:
            continue
        if stamp < started:
            continue
        if ended is not None and stamp > ended:
            continue
        candidates.append(path)
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda p: abs(
            datetime.strptime(f"{started:%Y-%m-%d} {p.stem}", "%Y-%m-%d %H:%M:%S")
            - started
        ),
    )
