from __future__ import annotations

import subprocess
import time

from maa_runner.config import Config
from maa_runner.screen import is_black, mean_luma


class AdbError(Exception):
    """adb command or device state failure."""


def _adb_bin(cfg: Config) -> str:
    return cfg.device.adb


def _serial_args(cfg: Config, serial: str | None = None) -> list[str]:
    value = cfg.device.serial.strip() if serial is None else serial
    if value:
        return ["-s", value]
    return []


def run_adb(
    cfg: Config,
    args: list[str],
    *,
    serial: str | None = None,
    timeout: float | None = 30,
    binary: bool = False,
    with_serial: bool = True,
) -> subprocess.CompletedProcess:
    cmd = [_adb_bin(cfg)]
    if with_serial:
        cmd.extend(_serial_args(cfg, serial))
    cmd.extend(args)
    try:
        return subprocess.run(
            cmd,
            timeout=timeout,
            capture_output=True,
            text=not binary,
            check=False,
        )
    except FileNotFoundError as exc:
        raise AdbError(f"adb not found: {cfg.device.adb}") from exc
    except subprocess.TimeoutExpired as exc:
        raise AdbError(f"adb timed out: {' '.join(cmd)}") from exc


def list_devices(cfg: Config) -> list[tuple[str, str]]:
    proc = run_adb(cfg, ["devices"], with_serial=False)
    if proc.returncode != 0:
        err = (proc.stderr or "").strip() or f"exit {proc.returncode}"
        raise AdbError(f"adb devices failed: {err}")
    devices: list[tuple[str, str]] = []
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if not line or line.startswith("List of devices"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            devices.append((parts[0], parts[1]))
    return devices


def require_online(cfg: Config) -> str:
    devices = list_devices(cfg)
    wanted = cfg.device.serial.strip()
    if wanted:
        statuses = {serial: status for serial, status in devices}
        status = statuses.get(wanted)
        if status is None:
            raise AdbError(f"serial {wanted} not in adb devices")
        if status != "device":
            raise AdbError(f"serial {wanted} status is {status}, want device")
        return wanted
    ready = [serial for serial, status in devices if status == "device"]
    if len(ready) == 0:
        others = ", ".join(f"{s}:{st}" for s, st in devices) or "none"
        raise AdbError(f"no device in state device (seen: {others})")
    if len(ready) > 1:
        raise AdbError(
            f"multiple devices; set connection.device in maa profile "
            f"({', '.join(ready)})"
        )
    return ready[0]


def screencap_png(cfg: Config) -> bytes:
    proc = run_adb(cfg, ["exec-out", "screencap", "-p"], binary=True, timeout=30)
    if proc.returncode != 0:
        err = (proc.stderr or b"").decode("utf-8", "replace").strip()
        raise AdbError(f"screencap failed: {err or proc.returncode}")
    data = proc.stdout or b""
    if not data.startswith(b"\x89PNG"):
        raise AdbError("screencap did not return a PNG (use exec-out, not shell)")
    return data


def keyevent(cfg: Config, key: int) -> None:
    proc = run_adb(cfg, ["shell", "input", "keyevent", str(key)])
    if proc.returncode != 0:
        err = (proc.stderr or "").strip()
        raise AdbError(f"keyevent {key} failed: {err or proc.returncode}")


def capture_luma(cfg: Config) -> float:
    return mean_luma(screencap_png(cfg))


def ensure_awake(cfg: Config, log=lambda *_args, **_kwargs: None) -> float:
    retries = cfg.device.wake_retries
    for attempt in range(retries + 1):
        luma = capture_luma(cfg)
        if not is_black(luma, cfg.device.luma_black):
            return luma
        if attempt >= retries:
            break
        log(f"黑屏 luma={luma:.1f}，唤醒 {attempt + 1}/{retries}")
        keyevent(cfg, cfg.device.wake_key)
        time.sleep(cfg.device.wake_interval_sec)
    luma = capture_luma(cfg)
    if is_black(luma, cfg.device.luma_black):
        raise AdbError(f"still black after {retries} wake attempts (luma={luma:.1f})")
    return luma


def try_sleep(cfg: Config) -> None:
    try:
        keyevent(cfg, cfg.device.sleep_key)
    except AdbError:
        pass


def ensure_asleep(cfg: Config, log=lambda *_args, **_kwargs: None) -> float:
    luma = capture_luma(cfg)
    if is_black(luma, cfg.device.luma_black):
        return luma
    log(f"非黑屏 luma={luma:.1f}，发送 keyevent {cfg.device.sleep_key}")
    keyevent(cfg, cfg.device.sleep_key)
    time.sleep(cfg.device.wake_interval_sec)
    luma = capture_luma(cfg)
    if not is_black(luma, cfg.device.luma_black):
        raise AdbError(f"still not black after sleep key (luma={luma:.1f})")
    return luma


def reboot(cfg: Config) -> None:
    proc = run_adb(cfg, ["reboot"], timeout=30)
    if proc.returncode != 0:
        err = (proc.stderr or "").strip()
        raise AdbError(f"adb reboot failed: {err or proc.returncode}")


def wait_for_boot(cfg: Config, log=lambda *_args, **_kwargs: None) -> None:
    timeout = cfg.cleanup.boot_timeout_sec
    proc = run_adb(
        cfg,
        ["wait-for-device"],
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise AdbError("wait-for-device failed")

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        proc = run_adb(
            cfg,
            ["shell", "getprop", "sys.boot_completed"],
            timeout=15,
        )
        value = (proc.stdout or "").strip()
        if proc.returncode == 0 and value == "1":
            return
        log(f"sys.boot_completed={value or 'n/a'}")
        time.sleep(2)
    raise AdbError(f"boot_completed not 1 within {timeout:.0f}s")
