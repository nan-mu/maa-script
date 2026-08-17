from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

MARKER = "MAA_RUNNER_MANAGED"


class ScheduleError(Exception):
    """crontab read/write failure."""


def resolve_pixi() -> Path:
    found = shutil.which("pixi")
    if found:
        return Path(found).resolve()
    fallback = Path.home() / ".pixi" / "bin" / "pixi"
    if fallback.is_file():
        return fallback.resolve()
    raise ScheduleError("pixi not found in PATH or ~/.pixi/bin/pixi")


def read_crontab() -> str:
    proc = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    if proc.returncode != 0:
        return ""
    return proc.stdout


def write_crontab(text: str) -> None:
    if not text.strip():
        proc = subprocess.run(["crontab", "-r"], capture_output=True, text=True)
        if proc.returncode != 0 and "no crontab" not in (proc.stderr or "").lower():
            raise ScheduleError(proc.stderr.strip() or "crontab -r failed")
        return
    proc = subprocess.run(
        ["crontab", "-"],
        input=text,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise ScheduleError(proc.stderr.strip() or "crontab write failed")


def build_cron_line(cron_expr: str, project_root: Path, pixi_bin: Path) -> str:
    root = project_root.resolve()
    pixi = pixi_bin.resolve()
    cron_log = root / "logs" / "cron.log"
    return (
        f"{cron_expr} cd {root} && {pixi} run daily "
        f">> {cron_log} 2>&1 # {MARKER}"
    )


def upsert_managed_line(crontab_text: str, new_line: str) -> str:
    lines = crontab_text.splitlines()
    kept = [line for line in lines if MARKER not in line]
    while kept and kept[-1].strip() == "":
        kept.pop()
    kept.append(new_line.rstrip("\n"))
    return "\n".join(kept) + "\n"


def remove_managed_lines(crontab_text: str) -> str:
    lines = crontab_text.splitlines()
    kept = [line for line in lines if MARKER not in line]
    if not kept:
        return ""
    while kept and kept[-1].strip() == "":
        kept.pop()
    if not kept:
        return ""
    return "\n".join(kept) + "\n"
