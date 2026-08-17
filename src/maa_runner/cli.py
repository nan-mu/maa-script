from __future__ import annotations

import shutil
import sys

from maa_runner.config import ConfigError, load_config, project_root
from maa_runner.notify import NotifyError, send_message
from maa_runner.pipeline import EXIT_CONFIG, EXIT_OK, run_daily, run_preflight
from maa_runner.schedule import (
    ScheduleError,
    build_cron_line,
    read_crontab,
    remove_managed_lines,
    resolve_pixi,
    upsert_managed_line,
    write_crontab,
)

COMMANDS = (
    "init",
    "doctor",
    "install",
    "uninstall",
    "daily",
    "notify-test",
    "test",
)


def cmd_init() -> int:
    root = project_root()
    src = root / "config.example.toml"
    dest = root / "config.toml"
    if dest.exists():
        print(f"config.toml already exists: {dest}", file=sys.stderr)
        return EXIT_CONFIG
    if not src.is_file():
        print(f"missing template: {src}", file=sys.stderr)
        return EXIT_CONFIG
    shutil.copy(src, dest)
    print(f"Wrote {dest}")
    print("Edit config.toml, then: pixi run doctor")
    return EXIT_OK


def cmd_doctor() -> int:
    cfg = load_config()
    failures = run_preflight(cfg)
    if failures:
        print("doctor failed:", file=sys.stderr)
        for item in failures:
            print(f"  {item}", file=sys.stderr)
        return EXIT_CONFIG
    print("doctor ok")
    return EXIT_OK


def cmd_install() -> int:
    cfg = load_config()
    failures = run_preflight(cfg)
    if failures:
        print("install aborted; crontab unchanged", file=sys.stderr)
        for item in failures:
            print(f"  {item}", file=sys.stderr)
        return EXIT_CONFIG
    try:
        pixi = resolve_pixi()
        cfg.log_dir().mkdir(parents=True, exist_ok=True)
        line = build_cron_line(cfg.schedule.cron, cfg.root, pixi)
        updated = upsert_managed_line(read_crontab(), line)
        write_crontab(updated)
    except ScheduleError as exc:
        print(f"crontab error: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    print(line)
    return EXIT_OK


def cmd_uninstall() -> int:
    try:
        current = read_crontab()
        updated = remove_managed_lines(current)
        if current == updated:
            print("no MAA_RUNNER_MANAGED crontab line")
            return EXIT_OK
        write_crontab(updated)
    except ScheduleError as exc:
        print(f"crontab error: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    print("removed MAA_RUNNER_MANAGED crontab line")
    return EXIT_OK


def cmd_daily() -> int:
    cfg = load_config()
    return run_daily(cfg)


def cmd_notify_test() -> int:
    cfg = load_config()
    try:
        send_message(cfg, "[MAA Runner] notify-test ok")
    except NotifyError as exc:
        print(f"Telegram 发送失败: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    print("notify-test ok")
    return EXIT_OK


def cmd_test() -> int:
    import pytest

    root = project_root()
    return pytest.main([str(root / "tests")])


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv or argv[0] not in COMMANDS:
        names = "|".join(COMMANDS)
        print(f"usage: python -m maa_runner <{names}>", file=sys.stderr)
        raise SystemExit(EXIT_CONFIG)
    if len(argv) > 1:
        print("no extra CLI arguments; edit config.toml", file=sys.stderr)
        raise SystemExit(EXIT_CONFIG)

    command = argv[0]
    dispatch = {
        "init": cmd_init,
        "doctor": cmd_doctor,
        "install": cmd_install,
        "uninstall": cmd_uninstall,
        "daily": cmd_daily,
        "notify-test": cmd_notify_test,
        "test": cmd_test,
    }
    try:
        code = dispatch[command]()
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        raise SystemExit(EXIT_CONFIG) from exc
    raise SystemExit(code)
