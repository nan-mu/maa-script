from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import tomllib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from maa_runner.config import Config, ConfigError, with_device
from maa_runner.logs import append_section, daily_log_path
from maa_runner.net import proxy_env

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
        adb_path, serial = read_connection(cfg)
    except MaaDirError as exc:
        raise ConfigError(str(exc)) from exc
    return with_device(cfg, adb=adb_path, serial=serial)


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


@dataclass
class MaaResult:
    stdout: str
    stderr: str
    returncode: int | None
    timed_out: bool
    summary_path: Path
    log_path: Path
    cmd: list[str]
    started_at: datetime
    ended_at: datetime
    maa_log_path: Path | None


def _with_log_file(extra_args: tuple[str, ...], log_path: Path) -> list[str]:
    """Pass through extra_args unchanged.

    ``--log-file`` must stay a bare flag so maa writes into its own rotated
    log directory. Do not inject or replace a path after it.
    ``log_path`` is unused and kept only for call-site compatibility.
    """
    del log_path
    return list(extra_args)


def build_cmd(cfg: Config, log_path: Path) -> list[str]:
    extra = _with_log_file(cfg.maa.extra_args, log_path)
    return [cfg.maa.bin, "run", cfg.maa.task, *extra]


def _kill_group(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass


def run_maa(
    cfg: Config,
    *,
    timestamp: str,
    on_tick=None,
) -> MaaResult:
    del timestamp
    log_dir = cfg.log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = daily_log_path(log_dir, datetime.now().date())
    cmd = build_cmd(cfg, log_path)
    env = os.environ.copy()
    env.update(proxy_env(cfg.network.proxy))

    started_at = datetime.now()
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            start_new_session=True,
        )
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"maa not found: {cfg.maa.bin}") from exc

    stop = threading.Event()

    def _heartbeat() -> None:
        elapsed = 0
        while not stop.wait(60):
            elapsed += 60
            if on_tick is not None:
                on_tick(elapsed)

    beat = threading.Thread(target=_heartbeat, daemon=True)
    beat.start()
    timed_out = False
    try:
        try:
            stdout_b, stderr_b = proc.communicate(timeout=cfg.maa.timeout_sec)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_group(proc)
            try:
                stdout_b, stderr_b = proc.communicate(timeout=15)
            except subprocess.TimeoutExpired:
                stdout_b, stderr_b = b"", b""
        except KeyboardInterrupt:
            _kill_group(proc)
            raise
    finally:
        stop.set()

    ended_at = datetime.now()
    stdout = (stdout_b or b"").decode("utf-8", "replace")
    stderr = (stderr_b or b"").decode("utf-8", "replace")
    daily_path = daily_log_path(log_dir, started_at.date())
    append_section(daily_path, "MAA", stdout, when=started_at)

    maa_log_path = None
    try:
        maa_log_path = find_maa_log(maa_dir(cfg, "log"), started_at, ended_at)
    except Exception:
        maa_log_path = None

    return MaaResult(
        stdout=stdout,
        stderr=stderr,
        returncode=proc.returncode,
        timed_out=timed_out,
        summary_path=daily_path,
        log_path=daily_path,
        cmd=cmd,
        started_at=started_at,
        ended_at=ended_at,
        maa_log_path=maa_log_path,
    )
