from __future__ import annotations

import os
import signal
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from maa_runner.config import Config
from maa_runner.maa_paths import find_maa_log, maa_dir
from maa_runner.net import proxy_env


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
    log_dir = cfg.log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{timestamp}.log"
    summary_path = log_dir / f"{timestamp}.summary.txt"
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
    summary_path.write_text(stdout, encoding="utf-8")

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
        summary_path=summary_path,
        log_path=log_path,
        cmd=cmd,
        started_at=started_at,
        ended_at=ended_at,
        maa_log_path=maa_log_path,
    )
