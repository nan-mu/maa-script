from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from maa_runner.parse import ParseResult, format_fight_drops, parse_fight, parse_recruit

LOG_LEVEL_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) (\w+)\]")
ALLOWED_LEVELS = frozenset({"INFO", "DEBUG"})
MAX_ANOMALY_LINES = 10

SERVICE_ALIASES = {
    "infrast": ("Infrast", "基建"),
    "mall": ("Mall", "购物", "商店"),
    "award": ("Award", "奖励"),
    "recruit": ("Recruit", "公招", "招聘"),
}


@dataclass(frozen=True)
class LogAnomaly:
    counts: dict[str, int]
    lines: tuple[str, ...]
    truncated: int = 0

    @property
    def empty(self) -> bool:
        return not self.counts


@dataclass(frozen=True)
class ReportBundle:
    text: str
    attach_summary: bool
    attach_maa_log: bool
    tasks_ok: bool
    log_warned: bool


def _hms_to_seconds(value: str) -> int:
    h, m, s = (int(x) for x in value.split(":"))
    return h * 3600 + m * 60 + s


def _format_duration(seconds: int) -> str:
    if seconds < 0:
        seconds += 24 * 3600
    if seconds < 60:
        return f"{seconds}s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {sec}s" if sec else f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    if minutes and sec:
        return f"{hours}h {minutes}m {sec}s"
    if minutes:
        return f"{hours}h {minutes}m"
    return f"{hours}h"


def time_span(parsed: ParseResult) -> tuple[str, str, str] | None:
    if not parsed.tasks:
        return None
    start = parsed.tasks[0].start
    end = parsed.tasks[-1].end
    duration = _format_duration(_hms_to_seconds(end) - _hms_to_seconds(start))
    return start, end, duration


def scan_log_levels(text: str) -> LogAnomaly:
    counts: dict[str, int] = {}
    lines: list[str] = []
    truncated = 0
    for line in text.splitlines():
        match = LOG_LEVEL_RE.match(line)
        if not match:
            continue
        level = match.group(2)
        if level in ALLOWED_LEVELS:
            continue
        counts[level] = counts.get(level, 0) + 1
        if len(lines) < MAX_ANOMALY_LINES:
            lines.append(line.rstrip())
        else:
            truncated += 1
    return LogAnomaly(counts=counts, lines=tuple(lines), truncated=truncated)


def scan_log_file(path: Path | None) -> LogAnomaly:
    if path is None or not path.is_file():
        return LogAnomaly(counts={}, lines=())
    try:
        return scan_log_levels(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return LogAnomaly(counts={}, lines=())


def _stars_text(stars: dict[int, int]) -> str:
    if not stars:
        return ""
    parts = [f"{n}★ × {stars[n]}" for n in sorted(stars)]
    return " ".join(parts)


def _format_anomaly_block(anomaly: LogAnomaly) -> list[str]:
    if anomaly.empty:
        return []
    count_bits = " · ".join(f"{level} × {n}" for level, n in sorted(anomaly.counts.items()))
    lines = ["", "日志异常", f"• {count_bits}"]
    for line in anomaly.lines:
        lines.append(f"• {line}")
    if anomaly.truncated:
        lines.append(f"• … 另有 {anomaly.truncated} 行")
    return lines


def _service_line(parsed: ParseResult) -> str | None:
    parts: list[str] = []
    mapping = [
        ("🏭 基建", SERVICE_ALIASES["infrast"]),
        ("🛒 购物", SERVICE_ALIASES["mall"]),
        ("🎁 奖励", SERVICE_ALIASES["award"]),
    ]
    for label, names in mapping:
        task = parsed.find(*names)
        if task is not None and task.status == "Completed":
            parts.append(label)
    if not parts:
        return None
    return " · ".join(parts) + " · 完成"


def format_success_body(parsed: ParseResult) -> list[str]:
    lines: list[str] = []
    for task in parsed.tasks:
        if task.status != "Completed":
            continue
        stage, times, total = parse_fight(task.body)
        drops = format_fight_drops(total) if total else ""
        if stage and times is not None and drops:
            lines.append(f"⚔ {task.name} · {stage} × {times} 收获：{drops}")
            continue
        if task.name.lower() in {n.lower() for n in SERVICE_ALIASES["recruit"]} or task.name == "公招":
            recruited, refreshed, stars = parse_recruit(task.body)
            if recruited or refreshed:
                star_bit = _stars_text(stars)
                extra = f" {star_bit}" if star_bit else ""
                lines.append(f"🎟 公招：招募 {recruited} · 刷新 {refreshed}{extra}")
            continue
    service = _service_line(parsed)
    if service:
        lines.append(service)
    return lines


def build_report(
    parsed: ParseResult,
    *,
    process_ok: bool,
    timed_out: bool,
    returncode: int | None,
    anomaly: LogAnomaly,
) -> ReportBundle:
    total = len(parsed.tasks)
    done = parsed.completed_count
    span = time_span(parsed)
    time_line = (
        f"🕐 {span[0]} → {span[1]} · 耗时 {span[2]}" if span else "🕐 时间未知"
    )

    failed_tasks = [t for t in parsed.tasks if t.status != "Completed"]
    tasks_ok = process_ok and not failed_tasks and not timed_out
    log_warned = not anomaly.empty

    if tasks_ok and not log_warned:
        head = f"✅ MAA daily 完成 · {done}/{total}"
        body = format_success_body(parsed)
        text = "\n".join([head, time_line, "", *body] if body else [head, time_line, "", "今日无额外掉落明细"])
        return ReportBundle(
            text=text.rstrip() + "\n",
            attach_summary=False,
            attach_maa_log=False,
            tasks_ok=True,
            log_warned=False,
        )

    if tasks_ok and log_warned:
        head = f"⚠️ MAA daily 完成 · {done}/{total} · 有日志告警"
        body = format_success_body(parsed)
        lines = [head, time_line, ""]
        lines.extend(body or ["今日无额外掉落明细"])
        lines.extend(_format_anomaly_block(anomaly))
        return ReportBundle(
            text="\n".join(lines).rstrip() + "\n",
            attach_summary=False,
            attach_maa_log=True,
            tasks_ok=True,
            log_warned=True,
        )

    # failure
    if timed_out:
        head = f"❌ MAA daily 失败 · 超时 · {done}/{total} Completed"
    elif returncode not in (0, None):
        head = f"❌ MAA daily 失败 · 退出码 {returncode} · {done}/{total} Completed"
    else:
        head = f"❌ MAA daily 失败 · {done}/{total} Completed"
    lines = [head, time_line, "", "未完成"]
    if failed_tasks:
        for task in failed_tasks:
            lines.append(f"• [{task.name}] {task.status}")
    else:
        lines.append("• （无任务行或 Summary 为空）")
    lines.extend(_format_anomaly_block(anomaly))
    return ReportBundle(
        text="\n".join(lines).rstrip() + "\n",
        attach_summary=True,
        attach_maa_log=True,
        tasks_ok=False,
        log_warned=log_warned,
    )


def clock_now() -> datetime:
    return datetime.now()


def elapsed_label(started: datetime, ended: datetime) -> str:
    return _format_duration(int((ended - started).total_seconds()))
