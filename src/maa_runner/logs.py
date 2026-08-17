from __future__ import annotations

import calendar
import re
import shutil
import subprocess
import tempfile
from datetime import date, datetime
from pathlib import Path

from maa_runner.config import LogsConfig

DAILY_LOG_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.log$")
WEEK_FOLDER_RE = re.compile(r"^(\d{4})-\d{2}-week-(\d{2})$")
CRON_LOG_NAME = "cron.log"
ARCHIVE_NAME = "archive.7z"


class ArchiveError(Exception):
    """7z archive read/write failure."""


def daily_log_path(log_dir: Path, day: date) -> Path:
    return log_dir / f"{day:%Y-%m-%d}.log"


def cron_log_path(log_dir: Path) -> Path:
    return log_dir / CRON_LOG_NAME


def archive_path(log_dir: Path) -> Path:
    return log_dir / ARCHIVE_NAME


def iso_week_folder(day: date) -> str:
    iso_year, iso_week, _ = day.isocalendar()
    thursday = date.fromisocalendar(iso_year, iso_week, 4)
    return f"{iso_year}-{thursday:%m}-week-{iso_week:02d}"


def parse_daily_log_date(path: Path) -> date | None:
    match = DAILY_LOG_RE.match(path.name)
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def list_daily_logs(log_dir: Path) -> list[tuple[Path, date]]:
    if not log_dir.is_dir():
        return []
    found: list[tuple[Path, date]] = []
    for path in log_dir.iterdir():
        if not path.is_file():
            continue
        day = parse_daily_log_date(path)
        if day is not None:
            found.append((path, day))
    found.sort(key=lambda item: item[1])
    return found


def subtract_months(day: date, months: int) -> date:
    year = day.year
    month = day.month - months
    while month <= 0:
        month += 12
        year -= 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last))


def week_folder_thursday(folder: str) -> date | None:
    match = WEEK_FOLDER_RE.match(folder)
    if not match:
        return None
    year, week = int(match.group(1)), int(match.group(2))
    try:
        return date.fromisocalendar(year, week, 4)
    except ValueError:
        return None


def delete_legacy_summaries(log_dir: Path) -> list[Path]:
    if not log_dir.is_dir():
        return []
    removed: list[Path] = []
    for path in log_dir.glob("*.summary.txt"):
        if path.is_file():
            path.unlink()
            removed.append(path)
    return removed


def stale_logs_by_week(log_dir: Path, today: date) -> dict[str, list[Path]]:
    current = today.isocalendar()[:2]
    groups: dict[str, list[Path]] = {}
    for path, day in list_daily_logs(log_dir):
        if day.isocalendar()[:2] == current:
            continue
        folder = iso_week_folder(day)
        groups.setdefault(folder, []).append(path)
    return groups


def append_section(path: Path, kind: str, body: str, *, when: datetime | None = None) -> None:
    text = body if body.endswith("\n") or body == "" else body + "\n"
    if not text.strip():
        return
    when = when or datetime.now()
    header = f"======== {when:%Y-%m-%d %H:%M:%S} {kind} ========\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    prefix = "\n" if path.is_file() and path.stat().st_size > 0 else ""
    with path.open("a", encoding="utf-8") as fh:
        fh.write(prefix)
        fh.write(header)
        fh.write(text)


def harvest_cron(log_dir: Path, dest: Path, *, when: datetime | None = None) -> bool:
    cron = cron_log_path(log_dir)
    if not cron.is_file() or cron.stat().st_size == 0:
        return False
    text = cron.read_text(encoding="utf-8", errors="replace")
    append_section(dest, "runner", text, when=when)
    cron.write_text("", encoding="utf-8")
    return True


def latest_daily_log(log_dir: Path) -> Path | None:
    items = list_daily_logs(log_dir)
    if not items:
        return None
    return items[-1][0]


def resolve_7z() -> str:
    for name in ("7z", "7za", "7zz"):
        found = shutil.which(name)
        if found:
            return found
    raise ArchiveError("7z not found on PATH (install 7-Zip / p7zip)")


def _run_7z(seven: str, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        [seven, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode not in (0, 1):
        err = (proc.stderr or proc.stdout or f"exit {proc.returncode}").strip()
        raise ArchiveError(err)
    return proc


def list_archive_names(archive: Path) -> list[str]:
    if not archive.is_file():
        return []
    proc = _run_7z(resolve_7z(), "l", "-slt", str(archive))
    names: list[str] = []
    current: str | None = None
    is_folder = False
    for line in proc.stdout.splitlines():
        if line.startswith("Path = "):
            if current and not is_folder:
                names.append(current.replace("\\", "/"))
            current = line[len("Path = ") :]
            is_folder = False
        elif line.startswith("Folder = "):
            is_folder = line.split(" = ", 1)[1].strip() in {"+", "true", "True"}
    if current and not is_folder:
        names.append(current.replace("\\", "/"))
    kept: list[str] = []
    for name in names:
        name = name.replace("\\", "/")
        folder = name.split("/", 1)[0]
        if WEEK_FOLDER_RE.match(folder) and "/" in name:
            kept.append(name)
    return kept


def extract_archive_text(archive: Path, member: str) -> str:
    seven = resolve_7z()
    with tempfile.TemporaryDirectory(prefix="maa-7z-x-") as tmp:
        _run_7z(seven, "x", str(archive), f"-o{tmp}", member, "-y")
        path = Path(tmp) / member
        return path.read_text(encoding="utf-8", errors="replace")


def _add_week_to_archive(
    archive: Path, folder: str, files: list[Path], compression_level: int
) -> None:
    seven = resolve_7z()
    level = max(0, min(9, compression_level))
    with tempfile.TemporaryDirectory(prefix="maa-7z-a-") as tmp:
        week_dir = Path(tmp) / folder
        week_dir.mkdir()
        for path in files:
            shutil.copy2(path, week_dir / path.name)
        _run_7z(
            seven,
            "a",
            f"-mx={level}",
            "-m0=lzma2",
            "-ms=on",
            str(archive.resolve()),
            folder,
            cwd=Path(tmp),
        )


def _prune_archive(archive: Path, today: date, retain_months: int, compression_level: int) -> int:
    if not archive.is_file():
        return 0
    cutoff = subtract_months(today, retain_months)
    names = list_archive_names(archive)
    drop_folders: set[str] = set()
    drop = 0
    keep = 0
    for name in names:
        folder = name.split("/", 1)[0]
        thursday = week_folder_thursday(folder)
        if thursday is not None and thursday < cutoff:
            drop_folders.add(folder)
            drop += 1
        else:
            keep += 1
    if drop == 0:
        return 0
    if keep == 0:
        archive.unlink()
        return drop
    seven = resolve_7z()
    level = max(0, min(9, compression_level))
    for folder in sorted(drop_folders):
        _run_7z(seven, "d", f"-mx={level}", str(archive), f"{folder}/*")
    return drop


def archive_stale_weeks(
    log_dir: Path,
    today: date,
    logs_cfg: LogsConfig,
    log=lambda *_args, **_kwargs: None,
) -> list[str]:
    groups = stale_logs_by_week(log_dir, today)
    archived: list[str] = []
    dest = archive_path(log_dir)
    for folder, files in sorted(groups.items()):
        try:
            _add_week_to_archive(dest, folder, files, logs_cfg.compression_level)
        except ArchiveError as exc:
            log(f"归档 {folder} 失败，保留热日志: {exc}")
            continue
        for path in files:
            path.unlink(missing_ok=True)
        archived.append(folder)
        log(f"已归档 {folder}（{len(files)} 个文件）")
    if dest.is_file():
        try:
            dropped = _prune_archive(
                dest, today, logs_cfg.retain_months, logs_cfg.compression_level
            )
        except ArchiveError as exc:
            log(f"7z 清理失败: {exc}")
        else:
            if dropped:
                log(f"7z 已去掉 {dropped} 个过期条目")
    return archived


def prepare_logs(
    log_dir: Path,
    logs_cfg: LogsConfig,
    today: date,
    log=lambda *_args, **_kwargs: None,
) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    removed = delete_legacy_summaries(log_dir)
    if removed:
        log(f"已删除 {len(removed)} 个旧 summary.txt")

    leftover_dest = latest_daily_log(log_dir) or daily_log_path(log_dir, today)
    if harvest_cron(log_dir, leftover_dest):
        log(f"已回收 cron.log → {leftover_dest.name}")

    archive_stale_weeks(log_dir, today, logs_cfg, log=log)
    return daily_log_path(log_dir, today)
