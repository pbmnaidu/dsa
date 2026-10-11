#!/usr/bin/env python3
"""Generate and update the README dashboard from repository data."""

from __future__ import annotations

import datetime as dt
import re
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
README_PATH = ROOT / "README.md"
SOLUTIONS_DIR = ROOT / "solutions"
NOTES_DIR = ROOT / "notes"
AUTO_START = "<!-- AUTO-GENERATED:START -->"
AUTO_END = "<!-- AUTO-GENERATED:END -->"

DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
NOTE_DATE_RE = re.compile(r"Day_(\d{1,2})_([A-Za-z]{3})_(\d{4})")

EXT_LANGUAGE_MAP = {
    ".py": "Python",
    ".java": "Java",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".cpp": "C++",
    ".c": "C",
    ".go": "Go",
    ".rb": "Ruby",
    ".rs": "Rust",
    ".md": "Markdown",
    ".txt": "Text",
    "": "Text",
}

PLATFORM_HINTS = {
    "geeksforgeeks.org": "GeeksforGeeks",
    "leetcode.com": "LeetCode",
    "codeforces.com": "Codeforces",
    "codechef.com": "CodeChef",
    "hackerrank.com": "HackerRank",
}

KEYWORD_PLATFORM_HINTS = {
    "leetcode": "LeetCode",
    "geeksforgeeks": "GeeksforGeeks",
    "codeforces": "Codeforces",
    "codechef": "CodeChef",
    "hackerrank": "HackerRank",
    "dsa404": "DSA404",
}


@dataclass
class ProblemEntry:
    path: Path
    title: str
    category: str
    topic: str
    language: str
    date: dt.date | None
    platform: str
    link: str


@dataclass
class NoteEntry:
    path: Path
    title: str
    date: dt.date | None
    link: str


class ReadmeUpdateError(RuntimeError):
    pass


def run_git(args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        return ""
    return result.stdout.strip()


def markdown_link(path: Path) -> str:
    rel = path.relative_to(ROOT).as_posix()
    return quote(rel, safe="/-_.()")


def parse_iso_date(text: str, context: str) -> dt.date:
    try:
        return dt.date.fromisoformat(text)
    except ValueError as exc:
        raise ReadmeUpdateError(f"Malformed date '{text}' in {context}") from exc


def parse_note_date(path: Path) -> dt.date | None:
    match = NOTE_DATE_RE.search(path.name)
    if not match:
        return None
    day, month_abbr, year = match.groups()
    try:
        month = dt.datetime.strptime(month_abbr, "%b").month
    except ValueError as exc:
        raise ReadmeUpdateError(f"Malformed note month in {path}") from exc
    return dt.date(int(year), month, int(day))


def parse_date_from_filename(path: Path) -> dt.date | None:
    match = DATE_RE.search(path.name)
    if not match:
        return None
    return parse_iso_date(match.group(1), str(path))


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        raise ReadmeUpdateError(f"Unable to read {path}: {exc}") from exc


def detect_problem_file(path: Path) -> bool:
    if path.is_relative_to(SOLUTIONS_DIR):
        return True
    if path.parent != ROOT or not path.is_file() or path.name.startswith("."):
        return False
    if path.name in {"README.md"}:
        return False
    lower_name = path.name.lower()
    if any(keyword in lower_name for keyword in ("leet", "problem", "design")):
        return True
    content = read_text(path)[:2000].lower()
    return "problem statement" in content or "problem name" in content


def infer_platform(content: str) -> str:
    urls = re.findall(r"https?://[^\s)]+", content)
    platforms = []
    for url in urls:
        for domain, name in PLATFORM_HINTS.items():
            if domain in url.lower():
                platforms.append(name)
    if platforms:
        return Counter(platforms).most_common(1)[0][0]

    lower = content.lower()
    for keyword, platform in KEYWORD_PLATFORM_HINTS.items():
        if keyword in lower:
            return platform
    return "Unspecified"


def infer_language(path: Path) -> str:
    return EXT_LANGUAGE_MAP.get(path.suffix.lower(), path.suffix.lstrip(".").upper() or "Text")


def infer_title(path: Path, content: str) -> str:
    for pattern in (r"^PROBLEM:\s*(.+)$", r"^#\s+(.+)$"):
        match = re.search(pattern, content, flags=re.MULTILINE)
        if match:
            return match.group(1).strip()
    return path.stem.replace("_", " ").strip() or path.name


def infer_topic(path: Path, content: str) -> str:
    match = re.search(r"^TOPIC:\s*(.+)$", content, flags=re.MULTILINE)
    if match:
        return match.group(1).strip()
    if path.is_relative_to(SOLUTIONS_DIR):
        rel = path.relative_to(SOLUTIONS_DIR)
        if len(rel.parts) > 1:
            return rel.parts[0]
    return "General"


def infer_category(path: Path) -> str:
    if path.is_relative_to(SOLUTIONS_DIR):
        rel = path.relative_to(SOLUTIONS_DIR)
        return rel.parts[0] if len(rel.parts) > 1 else "solutions"
    return "Root Problems"


def collect_problem_entries() -> list[ProblemEntry]:
    candidates: list[Path] = []
    if SOLUTIONS_DIR.exists():
        candidates.extend([p for p in SOLUTIONS_DIR.rglob("*") if p.is_file()])
    candidates.extend([p for p in ROOT.iterdir() if p.is_file() and not p.name.startswith(".")])

    entries: list[ProblemEntry] = []
    for path in sorted(set(candidates)):
        if not detect_problem_file(path):
            continue
        content = read_text(path)

        date = parse_date_from_filename(path)
        date_match = re.search(r"^DATE:\s*(\d{4}-\d{2}-\d{2})$", content, flags=re.MULTILINE)
        if date is None and date_match:
            date = parse_iso_date(date_match.group(1), str(path))

        entries.append(
            ProblemEntry(
                path=path,
                title=infer_title(path, content),
                category=infer_category(path),
                topic=infer_topic(path, content),
                language=infer_language(path),
                date=date,
                platform=infer_platform(content),
                link=markdown_link(path),
            )
        )

    if not entries:
        raise ReadmeUpdateError("No problem/solution files found. Cannot generate dashboard.")
    return entries


def collect_notes() -> list[NoteEntry]:
    if not NOTES_DIR.exists():
        return []
    notes: list[NoteEntry] = []
    for path in sorted([p for p in NOTES_DIR.rglob("*") if p.is_file()]):
        title = path.stem.replace("_", " ")
        notes.append(
            NoteEntry(
                path=path,
                title=title,
                date=parse_date_from_filename(path) or parse_note_date(path),
                link=markdown_link(path),
            )
        )
    return notes


def git_dates_for_paths(paths: Iterable[Path]) -> set[dt.date]:
    rel_paths = [str(p.relative_to(ROOT)) for p in paths]
    if not rel_paths:
        return set()
    out = run_git(["log", "--date=short", "--pretty=format:%ad", "--", *rel_paths])
    if not out:
        return set()
    dates: set[dt.date] = set()
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        dates.add(parse_iso_date(line, "git history"))
    return dates


def git_last_modified(path: Path) -> dt.date | None:
    rel = str(path.relative_to(ROOT))
    out = run_git(["log", "-1", "--date=short", "--pretty=format:%ad", "--", rel])
    if not out:
        return None
    return parse_iso_date(out.strip(), rel)


def compute_streak(dates: set[dt.date]) -> int:
    if not dates:
        return 0
    current = max(dates)
    streak = 0
    while current in dates:
        streak += 1
        current -= dt.timedelta(days=1)
    return streak


def format_date(value: dt.date | None) -> str:
    return value.isoformat() if value else "Unknown"


def progress_bar(value: int, total: int, width: int = 20) -> str:
    if total <= 0:
        return "░" * width
    fill = round((value / total) * width)
    fill = min(max(fill, 0), width)
    return "█" * fill + "░" * (width - fill)


def render_tree(problem_entries: list[ProblemEntry], notes: list[NoteEntry]) -> str:
    lines = ["```text", ".", "├── README.md"]
    root_problem_paths = sorted([e.path for e in problem_entries if e.category == "Root Problems"], key=lambda p: p.name)
    for path in root_problem_paths:
        lines.append(f"├── {path.name}")

    if notes:
        lines.append("├── notes/")
        for idx, note in enumerate(notes):
            prefix = "└──" if idx == len(notes) - 1 else "├──"
            lines.append(f"│   {prefix} {note.path.name}")

    grouped: dict[str, list[ProblemEntry]] = defaultdict(list)
    for entry in problem_entries:
        if entry.category != "Root Problems":
            grouped[entry.category].append(entry)

    if grouped:
        lines.append("└── solutions/")
        categories = sorted(grouped.keys())
        for cat_index, category in enumerate(categories):
            cat_entries = sorted(grouped[category], key=lambda e: e.path.name)
            cat_prefix = "└──" if cat_index == len(categories) - 1 else "├──"
            lines.append(f"    {cat_prefix} {category}/")
            for file_index, entry in enumerate(cat_entries):
                file_prefix = "└──" if file_index == len(cat_entries) - 1 else "├──"
                connector = "    " if cat_prefix == "└──" else "│   "
                lines.append(f"    {connector}{file_prefix} {entry.path.name}")

    lines.append("```")
    return "\n".join(lines)


def build_generated_section(problem_entries: list[ProblemEntry], notes: list[NoteEntry]) -> str:
    tracked_dates = {entry.date for entry in problem_entries if entry.date is not None}
    tracked_dates |= {note.date for note in notes if note.date is not None}
    tracked_dates |= git_dates_for_paths([*(e.path for e in problem_entries), *(n.path for n in notes)])

    tracked_days = len(tracked_dates)
    latest_update = max(tracked_dates) if tracked_dates else None
    streak = compute_streak(tracked_dates)

    category_counts = Counter(entry.category for entry in problem_entries)
    topic_counts = Counter(entry.topic for entry in problem_entries)
    platform_counts = Counter(entry.platform for entry in problem_entries)
    language_counts = Counter(entry.language for entry in problem_entries)

    total_problems = len(problem_entries)
    total_categories = len(category_counts)

    recent_items = []
    for entry in problem_entries:
        when = entry.date or git_last_modified(entry.path)
        recent_items.append((when, "Problem", entry.title, entry.link))
    for note in notes:
        when = note.date or git_last_modified(note.path)
        recent_items.append((when, "Note", note.title, note.link))

    recent_items.sort(key=lambda item: (item[0] is not None, item[0]), reverse=True)
    recent_items = recent_items[:8]

    total_platform_known = sum(count for platform, count in platform_counts.items() if platform != "Unspecified")
    platform_progress = progress_bar(total_platform_known, total_problems)

    badges = "\n".join(
        [
            f"![Total Problems](https://img.shields.io/badge/Problems-{total_problems}-2ea44f)",
            f"![Tracked Activity Days](https://img.shields.io/badge/Tracked_Activity_Days-{tracked_days}-1f6feb)",
            f"![Current Tracked Streak](https://img.shields.io/badge/Tracked_Streak-{streak}_days-8250df)",
            f"![Latest Update](https://img.shields.io/badge/Latest-{format_date(latest_update)}-0a7ea4)",
            f"![Categories](https://img.shields.io/badge/Categories-{total_categories}-d97706)",
            f"![Languages](https://img.shields.io/badge/Languages-{len(language_counts)}-6f42c1)",
        ]
    )

    stats_table = "\n".join(
        [
            "| Metric | Value |",
            "|---|---:|",
            f"| Total problem files | {total_problems} |",
            f"| Solution categories | {total_categories} |",
            f"| Notes files | {len(notes)} |",
            f"| Tracked activity days | {tracked_days} |",
            f"| Current tracked streak (days) | {streak} |",
            f"| Latest tracked update | {format_date(latest_update)} |",
            f"| Problems with identified platform | {total_platform_known}/{total_problems} {platform_progress} |",
        ]
    )

    category_lines = ["| Category/Folder | Problems |", "|---|---:|"]
    for category, count in sorted(category_counts.items()):
        category_lines.append(f"| `{category}` | {count} |")

    topic_lines = ["| Topic | Problems |", "|---|---:|"]
    for topic, count in sorted(topic_counts.items(), key=lambda item: (-item[1], item[0])):
        topic_lines.append(f"| {topic} | {count} |")

    platform_lines = ["| Platform/Source | Problems |", "|---|---:|"]
    for platform, count in sorted(platform_counts.items(), key=lambda item: (-item[1], item[0])):
        platform_lines.append(f"| {platform} | {count} |")

    language_lines = ["| Inferred language (from file extension) | Files |", "|---|---:|"]
    for language, count in sorted(language_counts.items(), key=lambda item: (-item[1], item[0])):
        language_lines.append(f"| {language} | {count} |")

    problems_by_category_lines = []
    grouped: dict[str, list[ProblemEntry]] = defaultdict(list)
    for entry in problem_entries:
        grouped[entry.category].append(entry)

    for category in sorted(grouped.keys()):
        problems_by_category_lines.append(f"### {category}")
        problems_by_category_lines.append("| Problem | Topic | Platform | Date |")
        problems_by_category_lines.append("|---|---|---|---|")
        for entry in sorted(grouped[category], key=lambda e: (e.date or dt.date.min, e.title), reverse=True):
            problems_by_category_lines.append(
                f"| [{entry.title}]({entry.link}) | {entry.topic} | {entry.platform} | {format_date(entry.date)} |"
            )
        problems_by_category_lines.append("")

    notes_lines = ["- _No notes files found._"]
    if notes:
        notes_lines = []
        for note in sorted(notes, key=lambda n: (n.date or dt.date.min, n.title), reverse=True):
            notes_lines.append(f"- [{note.title}]({note.link}) — {format_date(note.date)}")

    recent_lines = ["| Date | Type | Item |", "|---|---|---|"]
    if recent_items:
        for when, kind, title, link in recent_items:
            recent_lines.append(f"| {format_date(when)} | {kind} | [{title}]({link}) |")
    else:
        recent_lines.append("| Unknown | - | No tracked activity yet |")

    mermaid_lines = [
        "```mermaid",
        "pie showData",
        '    title Problems by Category',
    ]
    for category, count in sorted(category_counts.items()):
        safe_category = category.replace('"', "'")
        mermaid_lines.append(f'    "{safe_category}" : {count}')
    mermaid_lines.append("```")

    newline = "\n"

    generated = f"""
> ⚙️ This section is auto-generated by `scripts/update_readme.py`.
> Changes inside this block are overwritten by automation.

## 📊 Dashboard

{badges}

{stats_table}

## 🧮 Progress Visual

{newline.join(mermaid_lines)}

## 🗂️ Problems by Category

{newline.join(category_lines)}

## 🧠 Topics Inferred

{newline.join(topic_lines)}

## 🌐 Platforms / Sources

{newline.join(platform_lines)}

## 💻 Languages Inferred

{newline.join(language_lines)}

## ✅ Problem Index

{newline.join(problems_by_category_lines).strip()}

## 📝 Notes

{newline.join(notes_lines)}

## 🕒 Recent Activity

{newline.join(recent_lines)}

## 🧱 Repository Structure

{render_tree(problem_entries, notes)}
""".strip()

    return generated


def update_readme(generated_block: str) -> None:
    if not README_PATH.exists():
        raise ReadmeUpdateError(f"README not found at {README_PATH}")

    readme_text = read_text(README_PATH)
    if AUTO_START not in readme_text or AUTO_END not in readme_text:
        raise ReadmeUpdateError(
            f"README must contain markers '{AUTO_START}' and '{AUTO_END}' so generated content can be replaced safely."
        )

    pattern = re.compile(rf"{re.escape(AUTO_START)}.*?{re.escape(AUTO_END)}", flags=re.DOTALL)
    replacement = f"{AUTO_START}\n{generated_block}\n{AUTO_END}"
    updated = pattern.sub(replacement, readme_text, count=1)
    README_PATH.write_text(updated.rstrip() + "\n", encoding="utf-8")


def main() -> None:
    problem_entries = collect_problem_entries()
    notes = collect_notes()
    generated = build_generated_section(problem_entries, notes)
    update_readme(generated)


if __name__ == "__main__":
    try:
        main()
    except ReadmeUpdateError as exc:
        raise SystemExit(f"README generation failed: {exc}")
