from __future__ import annotations

import re
from dataclasses import dataclass

STATUSES = frozenset({"Completed", "Stopped", "Error", "Unfinished", "Unstarted"})

TASK_LINE_RE = re.compile(
    r"^\[(.+?)\]\s+(\d{2}:\d{2}:\d{2})\s+-\s+(\d{2}:\d{2}:\d{2})\s+\(([^)]+)\)\s+(\w+)\s*$"
)

FIGHT_LINE_RE = re.compile(r"^Fight\s+(\S+)\s+(\d+)\s+times,\s*drops:\s*$", re.I)
TOTAL_DROPS_RE = re.compile(r"^total drops:\s*(.+)\s*$", re.I)
RECRUITED_TIMES_RE = re.compile(r"^Recruited\s+(\d+)\s+times\s*$", re.I)
REFRESHED_TIMES_RE = re.compile(r"^Refreshed\s+(\d+)\s+times\s*$", re.I)
STAR_RE = re.compile(r"[★*]+")


@dataclass(frozen=True)
class TaskLine:
    name: str
    status: str
    start: str
    end: str
    duration: str
    raw: str
    body: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParseResult:
    tasks: tuple[TaskLine, ...]
    summary_text: str

    @property
    def all_completed(self) -> bool:
        return bool(self.tasks) and all(t.status == "Completed" for t in self.tasks)

    @property
    def completed_count(self) -> int:
        return sum(1 for t in self.tasks if t.status == "Completed")

    def find(self, *names: str) -> TaskLine | None:
        wanted = {n.lower() for n in names}
        for task in self.tasks:
            if task.name.lower() in wanted:
                return task
        return None


def extract_summary_text(stdout: str) -> str:
    lines = stdout.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == "Summary":
            return "\n".join(lines[i:]).rstrip() + ("\n" if stdout.endswith("\n") else "")
    return stdout


def parse_summary(stdout: str) -> ParseResult:
    summary_text = extract_summary_text(stdout)
    lines = summary_text.splitlines()
    tasks: list[TaskLine] = []
    i = 0
    while i < len(lines):
        match = TASK_LINE_RE.match(lines[i])
        if not match:
            i += 1
            continue
        name, start, end, duration, status = match.groups()
        i += 1
        body: list[str] = []
        while i < len(lines):
            if TASK_LINE_RE.match(lines[i]):
                break
            if lines[i].strip() == "----------------------------------------":
                i += 1
                break
            if lines[i].strip() and lines[i].strip() != "Summary":
                body.append(lines[i])
            i += 1
        tasks.append(
            TaskLine(
                name=name,
                status=status,
                start=start,
                end=end,
                duration=duration,
                raw=match.string if False else lines[i - 1] if False else "",
                body=tuple(body),
            )
        )
        # fix raw: re-match is cleaner
        tasks[-1] = TaskLine(
            name=name,
            status=status,
            start=start,
            end=end,
            duration=duration,
            raw=f"[{name}] {start} - {end} ({duration}) {status}",
            body=tuple(body),
        )
    return ParseResult(tasks=tuple(tasks), summary_text=summary_text)


def star_count(token: str) -> int | None:
    match = STAR_RE.search(token)
    if not match:
        return None
    stars = match.group(0)
    if "★" in stars:
        return stars.count("★")
    return len(stars)


def parse_fight(body: tuple[str, ...]) -> tuple[str | None, int | None, str | None]:
    """Return (stage, times, total_drops_text)."""
    stage = None
    times = None
    total = None
    for line in body:
        m = FIGHT_LINE_RE.match(line.strip())
        if m:
            stage, times = m.group(1), int(m.group(2))
            continue
        m = TOTAL_DROPS_RE.match(line.strip())
        if m:
            total = m.group(1).strip()
    return stage, times, total


HIDDEN_FIGHT_DROPS = frozenset({"理智 × 1"})


def format_fight_drops(total: str) -> str:
    parts = [
        part.strip()
        for part in total.split(",")
        if part.strip() and part.strip() not in HIDDEN_FIGHT_DROPS
    ]
    return " • ".join(parts)


def parse_recruit(body: tuple[str, ...]) -> tuple[int, int, dict[int, int]]:
    """Return (recruited_times, refreshed_times, star_counts for Recruited only)."""
    recruited = 0
    refreshed = 0
    stars: dict[int, int] = {}
    for line in body:
        stripped = line.strip()
        m = RECRUITED_TIMES_RE.match(stripped)
        if m:
            recruited = int(m.group(1))
            continue
        m = REFRESHED_TIMES_RE.match(stripped)
        if m:
            refreshed = int(m.group(1))
            continue
        if stripped.endswith("Recruited"):
            n = star_count(stripped)
            if n is not None:
                stars[n] = stars.get(n, 0) + 1
            recruited = recruited or 0
        elif stripped.endswith("Refreshed"):
            refreshed = refreshed or 0
    if recruited == 0 and stars:
        recruited = sum(stars.values())
    if refreshed == 0:
        refreshed = sum(1 for line in body if line.strip().endswith("Refreshed"))
    return recruited, refreshed, stars
