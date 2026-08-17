from __future__ import annotations

from datetime import datetime

from maa_runner import adb, net, notify
from maa_runner.adb import AdbError
from maa_runner.config import Config, ConfigError
from maa_runner.maa import (
    MaaDirError,
    MaaResult,
    build_cmd,
    enrich_from_maa_profile,
    find_task_file,
    maa_dir,
    run_maa,
)

EXIT_OK = 0
EXIT_CONFIG = 1
EXIT_STAGE = 2
EXIT_TIMEOUT = 3
EXIT_TELEGRAM = 4
EXIT_INTERRUPT = 130
from maa_runner.notify import NotifyError
from maa_runner.parse import parse_summary
from maa_runner.report import build_report, scan_log_file


class StageError(Exception):
    def __init__(self, message: str, *, exit_code: int = EXIT_STAGE):
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code


def title(n: int, name: str) -> None:
    print(f"[{n}/5] {name}", flush=True)


def detail(msg: str) -> None:
    print(f"  {msg}", flush=True)


def alert(cfg: Config, text: str) -> bool:
    try:
        notify.send_text(cfg, text)
        return True
    except NotifyError as exc:
        detail(f"Telegram 发送失败: {exc}")
        return False


def prepare_config(cfg: Config) -> Config:
    return enrich_from_maa_profile(cfg)


def run_preflight(cfg: Config) -> list[str]:
    failures: list[str] = []

    print("[doctor] MAA 配置", flush=True)
    try:
        config_dir = maa_dir(cfg, "config")
        detail(f"config dir {config_dir}")
        cfg = enrich_from_maa_profile(cfg)
        detail(f"adb={cfg.device.adb}")
        detail(f"serial={cfg.device.serial or '(empty → require single device)'}")
        task_file = find_task_file(cfg, config_dir)
        detail(f"task file {task_file}")
    except (MaaDirError, ConfigError) as exc:
        detail(f"FAIL ({exc})")
        failures.append(f"MAA config: {exc}")

    print("[doctor] Telegram", flush=True)
    try:
        info = notify.verify(cfg)
        detail(f"ok ({info})")
    except NotifyError as exc:
        detail(f"FAIL ({exc})")
        failures.append(f"Telegram: {exc}")

    print("[doctor] 网络", flush=True)
    for result in net.probe_all(cfg):
        status = "ok" if result.ok else "FAIL"
        detail(f"{status} {result.url} -> {result.detail}")
        if not result.ok:
            failures.append(f"Proxy {result.url}: {result.detail}")

    print("[doctor] 设备", flush=True)
    if any(f.startswith("MAA config:") for f in failures):
        detail("SKIP (maa profile unresolved)")
        failures.append("Device: skipped because maa profile failed")
    else:
        try:
            serial = adb.require_online(cfg)
            detail(f"serial {serial} status=device")
            luma = adb.ensure_awake(cfg, log=detail)
            detail(f"luma={luma:.1f} (awake)")
        except AdbError as exc:
            detail(f"FAIL ({exc})")
            failures.append(f"Device: {exc}")

    return failures


def _phase1(cfg: Config) -> None:
    title(1, "设备校验")
    serial = adb.require_online(cfg)
    detail(f"serial {serial} status=device")
    luma = adb.ensure_awake(cfg, log=detail)
    detail(f"luma={luma:.1f} (awake)")


def _phase2(cfg: Config) -> None:
    title(2, "网络")
    failures: list[str] = []
    for result in net.probe_all(cfg):
        detail(f"{result.url} -> {result.detail}")
        if not result.ok:
            failures.append(f"{result.url}: {result.detail}")
    if failures:
        raise StageError("proxy probe failed: " + "; ".join(failures))


def _phase3(cfg: Config, timestamp: str) -> MaaResult:
    title(3, "MAA 调度")
    log_path = cfg.log_dir() / f"{timestamp}.log"
    detail(" ".join(build_cmd(cfg, log_path)))

    def on_tick(elapsed: int) -> None:
        detail(f"运行中 ({elapsed}s)")

    result = run_maa(cfg, timestamp=timestamp, on_tick=on_tick)
    if result.timed_out:
        detail(f"超时 {cfg.maa.timeout_sec:.0f}s")
    else:
        detail(f"退出码 {result.returncode}")
    detail(f"stdout -> {result.summary_path}")
    if result.maa_log_path:
        detail(f"maa log -> {result.maa_log_path}")
    else:
        detail("maa log -> (not found)")
    if result.returncode not in (0, None) or result.timed_out:
        err = (result.stderr or "").strip()
        if err:
            for line in err.splitlines()[:20]:
                detail(f"stderr: {line}")
    return result


def _phase4(cfg: Config, result: MaaResult) -> tuple[bool, bool]:
    title(4, "解析与回传")
    parsed = parse_summary(result.stdout)
    detail(f"任务 {parsed.completed_count}/{len(parsed.tasks)} Completed")

    process_ok = (
        not result.timed_out
        and result.returncode == 0
        and parsed.all_completed
    )
    anomaly = scan_log_file(result.maa_log_path)
    if not anomaly.empty:
        detail(f"日志异常 levels={dict(anomaly.counts)}")

    report = build_report(
        parsed,
        process_ok=process_ok,
        timed_out=result.timed_out,
        returncode=result.returncode,
        anomaly=anomaly,
    )
    detail(report.text.splitlines()[0] if report.text else "(empty report)")

    sent_ok = True
    try:
        notify.send_report(
            cfg,
            report.text,
            summary_path=result.summary_path,
            attach_summary=report.attach_summary,
            maa_log_path=result.maa_log_path,
            attach_maa_log=report.attach_maa_log,
        )
        detail("Telegram 已发送")
        if report.attach_maa_log and result.maa_log_path is None:
            detail("⚠ 需要附 maa 日志但未找到文件")
    except NotifyError as exc:
        sent_ok = False
        detail(f"Telegram 发送失败: {exc}")

    return report.tasks_ok, sent_ok


def _phase5(cfg: Config, mode: str) -> None:
    title(5, "后置清理")
    if mode == "sleep_only":
        detail("mode=sleep_only")
        luma = adb.ensure_asleep(cfg, log=detail)
        detail(f"luma={luma:.1f} (black)")
        return
    detail("adb reboot")
    adb.reboot(cfg)
    detail("wait-for-device / boot_completed")
    adb.wait_for_boot(cfg, log=detail)
    luma = adb.ensure_asleep(cfg, log=detail)
    detail(f"luma={luma:.1f} (black)")


def _best_effort_sleep(cfg: Config) -> None:
    detail("清理: sleep_only")
    adb.try_sleep(cfg)


def _interrupted(cfg: Config) -> int:
    print("用户中断", flush=True)
    alert(cfg, "[MAA Runner] 用户中断")
    _best_effort_sleep(cfg)
    return EXIT_INTERRUPT


def run_daily(cfg: Config) -> int:
    cfg = prepare_config(cfg)
    cfg.log_dir().mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    try:
        try:
            _phase1(cfg)
            _phase2(cfg)
        except AdbError as exc:
            raise StageError(str(exc)) from exc
    except StageError as exc:
        alert(cfg, f"[MAA Runner] {exc.message}")
        _best_effort_sleep(cfg)
        return exc.exit_code
    except KeyboardInterrupt:
        return _interrupted(cfg)

    try:
        result = _phase3(cfg, timestamp)
    except FileNotFoundError as exc:
        alert(cfg, f"[MAA Runner] {exc}")
        _best_effort_sleep(cfg)
        return EXIT_STAGE
    except KeyboardInterrupt:
        return _interrupted(cfg)

    try:
        process_ok, sent_ok = _phase4(cfg, result)
    except KeyboardInterrupt:
        return _interrupted(cfg)

    if result.timed_out:
        exit_code = EXIT_TIMEOUT
    elif not process_ok:
        exit_code = EXIT_STAGE
    else:
        exit_code = EXIT_OK

    try:
        _phase5(cfg, cfg.cleanup.mode)
    except AdbError as exc:
        alert(cfg, f"[MAA Runner] cleanup failed: {exc}")
        return EXIT_STAGE
    except KeyboardInterrupt:
        return _interrupted(cfg)

    if exit_code == EXIT_OK and not sent_ok:
        return EXIT_TELEGRAM
    return exit_code
