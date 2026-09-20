from __future__ import annotations

import re
import sys
from typing import Any, TextIO

from lib.common.errors import SwitchError

# Version headings in CHANGELOG.md, e.g. `## [1.5.4] - 2026-09-11`.
_VERSION_HEADING_RE = re.compile(
    r"^##\s+\[?(?P<version>\d+\.\d+\.\d+)\]?", re.MULTILINE
)
# A section ends at the next version heading or at the trailing link block.
_SECTION_END_RE = re.compile(r"^(##\s+|\[[^\]]+\]:\s*)", re.MULTILINE)
# `## [1.5.4] - 2026-09-11` carries a release date after the version.
_TRAILING_DATE_RE = re.compile(r"^\s*-\s*\d{4}-\d{2}-\d{2}\s*$")
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_CODE_RE = re.compile(r"`([^`]+)`")
# Asterisk emphasis is unambiguous. Underscores are not: in
# `supported_reasoning_levels` they are part of the identifier, so they only
# count as emphasis when they are not surrounded by word characters.
_ASTERISK_EMPHASIS_RE = re.compile(r"(\*\*\*|\*\*|\*)(?=\S)(.+?)(?<=\S)\1")
_UNDERSCORE_EMPHASIS_RE = re.compile(
    r"(?<![0-9A-Za-z_])(__|_)(?=\S)(.+?)(?<=\S)\1(?![0-9A-Za-z_])"
)
# Code spans are parked here so emphasis rules cannot reach inside them.
_CODE_PLACEHOLDER = "\x00code{}\x00"
# GitHub's "generate release notes" adds this line; our footer already links
# the full notes, so it is dropped when reading old or generated bodies.
_AUTO_TRAILER_RE = re.compile(r"^\*{0,2}Full Changelog\*{0,2}:\s*\S*\s*$", re.I)

# Terminal output is bounded so an upgrade never scrolls a long release body
# past the user's prompt.
DEFAULT_NOTE_LINES = 40


def changelog_section(version: str, text: str) -> str | None:
    """Return the CHANGELOG section body for `version`, if present."""

    match = None
    for candidate in _VERSION_HEADING_RE.finditer(text):
        if candidate.group("version") == version:
            match = candidate
    if match is None:
        return None

    heading_tail = text[match.end() :].split("\n", 1)[0]
    body = text[match.end() + len(heading_tail) :]
    following = _SECTION_END_RE.search(body)
    if following is not None:
        body = body[: following.start()]

    lines = [heading_tail.strip()] if heading_tail.strip() else []
    lines.extend(body.split("\n"))
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and _TRAILING_DATE_RE.match(lines[0]):
        lines.pop(0)
    section = "\n".join(lines).strip()
    return section or None


def require_changelog_section(version: str, text: str) -> str:
    """Return the CHANGELOG section for `version` or fail loudly."""

    section = changelog_section(version, text)
    if section is None:
        raise SwitchError(
            f"CHANGELOG.md has no section for version {version}; "
            "add one before releasing"
        )
    return section


def _flatten_markdown(line: str) -> str:
    """Reduce one Markdown line to the text a terminal should show."""

    stripped = line.lstrip()
    if stripped.startswith("#"):
        line = stripped.lstrip("#").strip()
    elif stripped.startswith(("* ", "+ ")):
        indent = line[: len(line) - len(stripped)]
        line = f"{indent}- {stripped[2:].strip()}"
    elif stripped in ("---", "***", "___"):
        line = ""

    parked: list[str] = []

    def park(match: re.Match[str]) -> str:
        parked.append(match.group(1))
        return _CODE_PLACEHOLDER.format(len(parked) - 1)

    line = _CODE_RE.sub(park, line)
    line = _LINK_RE.sub(r"\1", line)
    line = _UNDERSCORE_EMPHASIS_RE.sub(r"\2", line)
    line = _ASTERISK_EMPHASIS_RE.sub(r"\2", line)
    for index, code in enumerate(parked):
        line = line.replace(_CODE_PLACEHOLDER.format(index), code)
    return line


def render_notes(body: str | None, *, max_lines: int = DEFAULT_NOTE_LINES) -> list[str]:
    """Turn a release body into terminal-ready lines.

    Release notes are authored as Markdown, so emphasis, links, and code spans
    are reduced to their readable text. Output is capped at `max_lines`;
    callers report the remainder with the release URL.
    """

    if not body:
        return []
    text = _HTML_COMMENT_RE.sub("", body)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    for raw_line in text.split("\n"):
        if _AUTO_TRAILER_RE.match(raw_line.strip()):
            continue
        line = _flatten_markdown(raw_line.rstrip())
        lines.append(line.strip() if not line.strip() else line)

    # Collapse runs of blank lines so sections stay visually separated.
    collapsed: list[str] = []
    for line in lines:
        if not line.strip():
            if not collapsed or not collapsed[-1].strip():
                continue
            collapsed.append("")
            continue
        collapsed.append(line)
    while collapsed and not collapsed[-1].strip():
        collapsed.pop()

    if max_lines > 0 and len(collapsed) > max_lines:
        hidden = len(collapsed) - max_lines
        return collapsed[:max_lines] + [f"... and {hidden} more lines"]
    return collapsed


def print_notes(
    plan: Any,
    *,
    stream: TextIO | None = None,
    max_lines: int = DEFAULT_NOTE_LINES,
) -> None:
    """Print a release's notes, plus how to read the full list."""

    out = stream or sys.stdout
    body = getattr(plan, "notes", None)
    version = getattr(plan, "latest_version", "")
    url = getattr(plan, "release_url", "")
    lines = render_notes(body, max_lines=max_lines)
    if not lines:
        if url:
            print(f"no release notes published; see {url}", file=out)
        return
    print(f"what's new in {version}:", file=out)
    for line in lines:
        print(f"  {line}" if line else "", file=out)
    if url:
        print(f"  full notes: {url}", file=out)
