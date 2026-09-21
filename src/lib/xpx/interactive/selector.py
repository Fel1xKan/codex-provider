from __future__ import annotations

import re
import shutil
import sys
import unicodedata
from collections.abc import Sequence
from typing import Any

from lib.xpx.i18n import t
from lib.xpx.interactive.terminal import (
    KeyCode,
    TerminalSession,
)

# Colors & styles
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"
RED = "\033[31m"

_ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def strip_ansi(s: str) -> str:
    """Strip ANSI escape sequences from string."""
    return _ANSI_ESCAPE_RE.sub("", s)


def str_display_width(s: str) -> int:
    """Calculate terminal visual display width accounting for full-width CJK chars.

    Ignores ANSI styling codes.
    """
    clean_s = strip_ansi(s)
    w = 0
    for ch in clean_s:
        eaw = unicodedata.east_asian_width(ch)
        if eaw in ("W", "F"):
            w += 2
        else:
            w += 1
    return w


def render_card(title: str, lines: Sequence[str]) -> str:
    """Render a perfectly aligned terminal card/box with unicode box borders."""
    clean_title = strip_ansi(title)
    title_w = str_display_width(clean_title)
    content_w = max((str_display_width(line) for line in lines), default=0)
    # Ensure minimum width of 56, and accommodate the longest line + padding
    inner_w = max(content_w + 4, title_w + 8, 56)

    # Top border: ┌── {title} ──────┐
    # "┌── " has width 4, " " has width 1, "┐" has width 1
    dashes_count = max(inner_w - 5 - title_w, 2)
    inner_w = 5 + title_w + dashes_count
    top_border = f"┌── {title} {'─' * dashes_count}┐"

    rendered_lines = [f"{BOLD}{top_border}{RESET}"]
    for line in lines:
        lw = str_display_width(line)
        pad = max(inner_w - 3 - lw, 1)
        rendered_lines.append(f"│  {line}{' ' * pad}│")

    bottom_border = f"└{'─' * (inner_w - 1)}┘"
    rendered_lines.append(f"{BOLD}{bottom_border}{RESET}")

    return "\n".join(rendered_lines) + "\n"


class Choice:
    def __init__(
        self,
        title: str,
        value: Any,
        description: str = "",
        checked: bool = False,
        disabled: bool = False,
    ) -> None:
        self.title = title
        self.value = value
        self.description = description
        self.checked = checked
        self.disabled = disabled


def render_frame(lines: Sequence[str], last_rendered_lines: int) -> int:
    """Renders an inline frame with zero screen tearing/flickering.

    Uses synchronized terminal updates (DEC Mode 2026) and atomic line overwriting
    instead of clearing the display with \\033[J.
    """
    buf: list[str] = ["\033[?2026h"]

    # 1. Reposition cursor back to top of previously rendered area
    if last_rendered_lines > 0:
        buf.append(f"\033[{last_rendered_lines}A\r")

    # 2. Overwrite each line in place: \r + \033[2K + line + \n
    for line in lines:
        buf.append(f"\r\033[2K{line}\n")

    # 3. If previous frame had more lines, clear leftover trailing lines
    if last_rendered_lines > len(lines):
        excess = last_rendered_lines - len(lines)
        for _ in range(excess):
            buf.append("\r\033[2K\n")
        # Move cursor back up to end of new lines
        buf.append(f"\033[{excess}A\r")

    # 4. End atomic synchronized update
    buf.append("\033[?2026l")

    sys.stdout.write("".join(buf))
    sys.stdout.flush()
    return len(lines)


def clear_frame(last_rendered_lines: int) -> None:
    """Clear previously rendered frame completely upon exit/confirm."""
    if last_rendered_lines > 0:
        sys.stdout.write(f"\033[?2026h\033[{last_rendered_lines}A\r\033[J\033[?2026l")
        sys.stdout.flush()


def select(
    prompt: str,
    choices: Sequence[Choice | str],
    *,
    default_index: int = 0,
    page_size: int = 8,
    allow_search: bool = True,
    allow_cancel: bool = True,
) -> Any | None:
    """Inline single-select menu with mouse wheel, clicking, filtering, and arrows."""
    norm_choices: list[Choice] = [
        c if isinstance(c, Choice) else Choice(c, c) for c in choices
    ]
    if not norm_choices:
        return None

    term_height = shutil.get_terminal_size((80, 24)).lines
    effective_page_size = min(page_size, max(3, term_height - 5))

    filter_text = ""
    highlight_index = max(0, min(default_index, len(norm_choices) - 1))
    scroll_offset = 0
    last_rendered_lines = 0

    with TerminalSession(enable_mouse=True, hide_cursor=True) as term:
        while True:
            if filter_text:
                ft = filter_text.lower()
                filtered = [
                    c
                    for c in norm_choices
                    if ft in c.title.lower() or ft in c.description.lower()
                ]
            else:
                filtered = list(norm_choices)

            if not filtered:
                highlight_index = 0
            else:
                highlight_index = max(0, min(highlight_index, len(filtered) - 1))

            # Adjust scroll window
            if highlight_index < scroll_offset:
                scroll_offset = highlight_index
            elif highlight_index >= scroll_offset + effective_page_size:
                scroll_offset = highlight_index - effective_page_size + 1

            visible_slice = filtered[
                scroll_offset : scroll_offset + effective_page_size
            ]

            lines: list[str] = []

            # 1. Prompt header
            if filter_text:
                lbl = t("ui.filter_label")
                header = (
                    f"{BOLD}?{RESET} {BOLD}{prompt}{RESET} "
                    f"{DIM}({lbl}: {CYAN}{filter_text}{RESET}{DIM}){RESET}"
                )
            else:
                header = f"{BOLD}?{RESET} {BOLD}{prompt}{RESET}"
            lines.append(header)

            # 2. Top overflow indicator
            if scroll_offset > 0:
                up_msg = f"  {DIM}{t('ui.overflow_up', count=scroll_offset)}{RESET}"
                lines.append(up_msg)

            # 3. Choices
            if not visible_slice:
                lines.append(f"  {DIM}{t('ui.no_matches')}{RESET}")
            else:
                for idx, c in enumerate(visible_slice):
                    actual_idx = scroll_offset + idx
                    desc_str = f" {DIM}{c.description}{RESET}" if c.description else ""
                    if actual_idx == highlight_index:
                        prefix = f"{CYAN}❯{RESET} {CYAN}{BOLD}"
                        suffix = f"{RESET}{desc_str}"
                    else:
                        prefix = "  "
                        suffix = f"{desc_str}"
                    lines.append(f"{prefix}{c.title}{suffix}")

            # 4. Bottom overflow indicator
            rem = len(filtered) - (scroll_offset + len(visible_slice))
            if rem > 0:
                dn_msg = f"  {DIM}{t('ui.overflow_down', count=rem)}{RESET}"
                lines.append(dn_msg)

            # 5. Hint footer
            hint = t("ui.hint_select")
            lines.append(f"{DIM}{hint}{RESET}")

            last_rendered_lines = render_frame(lines, last_rendered_lines)

            try:
                event = term.read_event()
            except KeyboardInterrupt:
                clear_frame(last_rendered_lines)
                raise

            if event.code == KeyCode.UP and filtered:
                highlight_index = (highlight_index - 1) % len(filtered)
            elif event.code == KeyCode.DOWN and filtered:
                highlight_index = (highlight_index + 1) % len(filtered)
            elif event.code == KeyCode.MOUSE_WHEEL_UP and filtered:
                highlight_index = max(0, highlight_index - 1)
            elif event.code == KeyCode.MOUSE_WHEEL_DOWN and filtered:
                highlight_index = min(len(filtered) - 1, highlight_index + 1)
            elif event.code == KeyCode.MOUSE_CLICK and filtered:
                event.code = KeyCode.ENTER
            elif event.code == KeyCode.PAGE_UP and filtered:
                highlight_index = max(0, highlight_index - effective_page_size)
            elif event.code == KeyCode.PAGE_DOWN and filtered:
                highlight_index = min(
                    len(filtered) - 1, highlight_index + effective_page_size
                )
            elif event.code == KeyCode.HOME and filtered:
                highlight_index = 0
            elif event.code == KeyCode.END and filtered:
                highlight_index = len(filtered) - 1
            elif event.code == KeyCode.BACKSPACE:
                if filter_text:
                    filter_text = filter_text[:-1]
                    highlight_index = 0
            elif event.code == KeyCode.ESC:
                if filter_text:
                    filter_text = ""
                    highlight_index = 0
                elif allow_cancel:
                    clear_frame(last_rendered_lines)
                    return None
            elif event.code == KeyCode.EOF:
                clear_frame(last_rendered_lines)
                return None
            elif event.code == KeyCode.CHAR and allow_search:
                filter_text += event.char
                highlight_index = 0

            if event.code == KeyCode.ENTER and filtered:
                chosen = filtered[highlight_index]
                clear_frame(last_rendered_lines)
                out_line = (
                    f"{GREEN}✔{RESET} {BOLD}{prompt}{RESET}: "
                    f"{CYAN}{chosen.title}{RESET}\n"
                )
                sys.stdout.write(out_line)
                sys.stdout.flush()
                return chosen.value


def checkbox(
    prompt: str,
    choices: Sequence[Choice],
    *,
    page_size: int = 8,
    allow_empty: bool = False,
    allow_search: bool = True,
    allow_cancel: bool = True,
) -> list[Any] | None:
    """Inline multi-select menu with Space toggling, 'a' key all/none, and mouse."""
    norm_choices: list[Choice] = list(choices)
    if not norm_choices:
        return []

    term_height = shutil.get_terminal_size((80, 24)).lines
    effective_page_size = min(page_size, max(3, term_height - 5))

    filter_text = ""
    highlight_index = 0
    scroll_offset = 0
    last_rendered_lines = 0
    error_msg = ""

    with TerminalSession(enable_mouse=True, hide_cursor=True) as term:
        while True:
            if filter_text:
                ft = filter_text.lower()
                filtered = [
                    c
                    for c in norm_choices
                    if ft in c.title.lower() or ft in c.description.lower()
                ]
            else:
                filtered = list(norm_choices)

            if not filtered:
                highlight_index = 0
            else:
                highlight_index = max(0, min(highlight_index, len(filtered) - 1))

            if highlight_index < scroll_offset:
                scroll_offset = highlight_index
            elif highlight_index >= scroll_offset + effective_page_size:
                scroll_offset = highlight_index - effective_page_size + 1

            visible_slice = filtered[
                scroll_offset : scroll_offset + effective_page_size
            ]

            lines: list[str] = []

            # 1. Prompt header
            sel_count = sum(1 for c in norm_choices if c.checked)
            badge_text = t(
                "ui.selected_badge", selected=sel_count, total=len(norm_choices)
            )
            count_badge = f"{CYAN}{badge_text}{RESET}"
            if filter_text:
                lbl = t("ui.filter_label")
                header = (
                    f"{BOLD}?{RESET} {BOLD}{prompt}{RESET} {count_badge} "
                    f"{DIM}({lbl}: {CYAN}{filter_text}{RESET}{DIM}){RESET}"
                )
            else:
                header = f"{BOLD}?{RESET} {BOLD}{prompt}{RESET} {count_badge}"
            lines.append(header)

            # 2. Top overflow
            if scroll_offset > 0:
                up_msg = f"  {DIM}{t('ui.overflow_up', count=scroll_offset)}{RESET}"
                lines.append(up_msg)

            # 3. Choices
            if not visible_slice:
                lines.append(f"  {DIM}{t('ui.no_matches')}{RESET}")
            else:
                for idx, c in enumerate(visible_slice):
                    actual_idx = scroll_offset + idx
                    box = f"{GREEN}[✔]{RESET}" if c.checked else "[ ]"
                    desc_str = f" {DIM}{c.description}{RESET}" if c.description else ""
                    if actual_idx == highlight_index:
                        prefix = f"{CYAN}❯{RESET} {box} {CYAN}{BOLD}"
                        suffix = f"{RESET}{desc_str}"
                    else:
                        prefix = f"  {box} "
                        suffix = f"{desc_str}"
                    lines.append(f"{prefix}{c.title}{suffix}")

            # 4. Bottom overflow
            rem = len(filtered) - (scroll_offset + len(visible_slice))
            if rem > 0:
                dn_msg = f"  {DIM}{t('ui.overflow_down', count=rem)}{RESET}"
                lines.append(dn_msg)

            # 5. Error message or Hint footer
            if error_msg:
                lines.append(f"{RED}⚠ {error_msg}{RESET}")
                error_msg = ""
            else:
                hint = t("ui.hint_checkbox")
                lines.append(f"{DIM}{hint}{RESET}")

            last_rendered_lines = render_frame(lines, last_rendered_lines)

            try:
                event = term.read_event()
            except KeyboardInterrupt:
                clear_frame(last_rendered_lines)
                raise

            if event.code == KeyCode.UP and filtered:
                highlight_index = (highlight_index - 1) % len(filtered)
            elif event.code == KeyCode.DOWN and filtered:
                highlight_index = (highlight_index + 1) % len(filtered)
            elif event.code == KeyCode.MOUSE_WHEEL_UP and filtered:
                highlight_index = max(0, highlight_index - 1)
            elif event.code == KeyCode.MOUSE_WHEEL_DOWN and filtered:
                highlight_index = min(len(filtered) - 1, highlight_index + 1)
            elif (event.code in (KeyCode.SPACE, KeyCode.MOUSE_CLICK)) and filtered:
                curr = filtered[highlight_index]
                curr.checked = not curr.checked
            elif (
                event.code == KeyCode.CHAR
                and event.char.lower() == "a"
                and not filter_text
            ):
                any_unchecked = any(not c.checked for c in norm_choices)
                for c in norm_choices:
                    c.checked = any_unchecked
            elif event.code == KeyCode.PAGE_UP and filtered:
                highlight_index = max(0, highlight_index - effective_page_size)
            elif event.code == KeyCode.PAGE_DOWN and filtered:
                highlight_index = min(
                    len(filtered) - 1, highlight_index + effective_page_size
                )
            elif event.code == KeyCode.HOME and filtered:
                highlight_index = 0
            elif event.code == KeyCode.END and filtered:
                highlight_index = len(filtered) - 1
            elif event.code == KeyCode.BACKSPACE:
                if filter_text:
                    filter_text = filter_text[:-1]
                    highlight_index = 0
            elif event.code == KeyCode.ESC:
                if filter_text:
                    filter_text = ""
                    highlight_index = 0
                elif allow_cancel:
                    clear_frame(last_rendered_lines)
                    return None
            elif event.code == KeyCode.EOF:
                clear_frame(last_rendered_lines)
                return None
            elif event.code == KeyCode.CHAR and allow_search:
                filter_text += event.char
                highlight_index = 0
            elif event.code == KeyCode.ENTER:
                selected_items = [c for c in norm_choices if c.checked]
                if not selected_items and not allow_empty:
                    error_msg = t("ui.min_one_required")
                    continue

                clear_frame(last_rendered_lines)
                sel_titles = ", ".join(c.title for c in selected_items) or "(none)"
                out_line = (
                    f"{GREEN}✔{RESET} {BOLD}{prompt}{RESET}: "
                    f"{CYAN}{sel_titles}{RESET}\n"
                )
                sys.stdout.write(out_line)
                sys.stdout.flush()
                return [c.value for c in selected_items]


def prompt_text(
    prompt: str,
    *,
    default: str = "",
    password: bool = False,
    allow_empty: bool = True,
) -> str | None:
    """Inline text input with default placeholder and password masking."""
    buffer = list(default)
    cursor_pos = len(buffer)
    last_rendered_lines = 0

    with TerminalSession(enable_mouse=False, hide_cursor=False) as term:
        while True:
            display_val = "•" * len(buffer) if password else "".join(buffer)
            if default:
                hint_str = t("ui.hint_prompt_def", default=default)
            else:
                hint_str = t("ui.hint_prompt_nodef")
            def_hint = f" {DIM}{hint_str}{RESET}"
            line = f"{BOLD}?{RESET} {BOLD}{prompt}{RESET}{def_hint}: {display_val}"
            last_rendered_lines = render_frame([line], last_rendered_lines)

            try:
                event = term.read_event()
            except KeyboardInterrupt:
                clear_frame(last_rendered_lines)
                raise

            if event.code == KeyCode.ENTER:
                result = "".join(buffer).strip()
                if not result and default:
                    result = default
                if not result and not allow_empty:
                    continue
                clear_frame(last_rendered_lines)
                masked = "••••••••" if (password and result) else result
                out_line = (
                    f"{GREEN}✔{RESET} {BOLD}{prompt}{RESET}: {CYAN}{masked}{RESET}\n"
                )
                sys.stdout.write(out_line)
                sys.stdout.flush()
                return result
            elif event.code in (KeyCode.ESC, KeyCode.EOF):
                clear_frame(last_rendered_lines)
                return None
            elif event.code == KeyCode.BACKSPACE:
                if buffer and cursor_pos > 0:
                    buffer.pop(cursor_pos - 1)
                    cursor_pos -= 1
            elif event.code == KeyCode.LEFT:
                cursor_pos = max(0, cursor_pos - 1)
            elif event.code == KeyCode.RIGHT:
                cursor_pos = min(len(buffer), cursor_pos + 1)
            elif event.code == KeyCode.HOME:
                cursor_pos = 0
            elif event.code == KeyCode.END:
                cursor_pos = len(buffer)
            elif event.code in (KeyCode.CHAR, KeyCode.SPACE):
                buffer.insert(cursor_pos, event.char)
                cursor_pos += 1


def confirm(prompt: str, *, default: bool = True) -> bool:
    """Inline Yes/No confirmation prompt."""
    choices = [
        Choice(t("ui.yes"), True),
        Choice(t("ui.no"), False),
    ]
    default_idx = 0 if default else 1
    res = select(prompt, choices, default_index=default_idx, allow_search=False)
    return bool(res)
