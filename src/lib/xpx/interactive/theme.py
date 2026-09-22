from __future__ import annotations

import os
import re
import sys

_ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def strip_ansi(s: str) -> str:
    """Strip ANSI escape sequences from string."""
    return _ANSI_ESCAPE_RE.sub("", s)


def supports_color() -> bool:
    """Check if the current terminal supports color output."""
    if "NO_COLOR" in os.environ:
        return False
    if os.environ.get("TERM") == "dumb":
        return False
    if not hasattr(sys.stdout, "isatty") or not sys.stdout.isatty():
        # Check if running under CI or forced colors
        return "FORCE_COLOR" in os.environ
    return True


def supports_truecolor() -> bool:
    """Check if the terminal supports 24-bit TrueColor."""
    if not supports_color():
        return False
    if os.environ.get("COLORTERM") in ("truecolor", "24bit"):
        return True
    if "WT_SESSION" in os.environ:  # Windows Terminal
        return True
    term_prog = os.environ.get("TERM_PROGRAM", "").lower()
    if term_prog in ("iterm.app", "wezterm", "vscode", "ghostty", "warp"):
        return True
    term = os.environ.get("TERM", "").lower()
    return "direct" in term or "kitty" in term or "alacritty" in term


def supports_256color() -> bool:
    """Check if the terminal supports at least 256 colors."""
    if not supports_color():
        return False
    if supports_truecolor():
        return True
    term = os.environ.get("TERM", "").lower()
    return "256color" in term or "xterm" in term or "screen" in term or "tmux" in term


def clear_screen() -> None:
    """Clear terminal screen and reset cursor to top-left."""
    if hasattr(sys.stdout, "isatty") and sys.stdout.isatty():
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()


def hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    """Convert hex color string (#RRGGBB or #RGB) to (r, g, b) tuple."""
    h = hex_str.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return (255, 255, 255)
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except ValueError:
        return (255, 255, 255)


def rgb_to_256(r: int, g: int, b: int) -> int:
    """Convert RGB to closest xterm 256 color code."""
    if r == g == b:
        if r < 8:
            return 16
        if r > 248:
            return 231
        return round(((r - 8) / 247) * 23) + 232
    r_idx = int(round(r / 255.0 * 5))
    g_idx = int(round(g / 255.0 * 5))
    b_idx = int(round(b / 255.0 * 5))
    return 16 + (36 * r_idx) + (6 * g_idx) + b_idx


def rgb_to_16(r: int, g: int, b: int, fg: bool = True) -> str:
    """Map RGB to closest standard ANSI 16 color code."""
    # Basic brightness threshold
    bright = max(r, g, b) > 128
    if r > 180 and g < 100 and b < 100:
        code = 91 if bright else 31
    elif g > 180 and r < 100 and b < 100:
        code = 92 if bright else 32
    elif r > 180 and g > 180 and b < 100:
        code = 93 if bright else 33
    elif b > 180 and r < 100 and g < 100:
        code = 94 if bright else 34
    elif r > 180 and b > 180 and g < 100:
        code = 95 if bright else 35
    elif g > 150 and b > 150 and r < 100:
        code = 96 if bright else 36
    elif r > 200 and g > 200 and b > 200:
        code = 97 if bright else 37
    else:
        code = 90 if bright else 30
    if not fg:
        code += 10
    return f"\033[{code}m"


def fg(color: str) -> str:
    """Return ANSI foreground escape sequence for hex color (#RRGGBB)."""
    if not supports_color() or not color:
        return ""
    r, g, b = hex_to_rgb(color)
    if supports_truecolor():
        return f"\033[38;2;{r};{g};{b}m"
    if supports_256color():
        return f"\033[38;5;{rgb_to_256(r, g, b)}m"
    return rgb_to_16(r, g, b, fg=True)


def bg(color: str) -> str:
    """Return ANSI background escape sequence for hex color (#RRGGBB)."""
    if not supports_color() or not color:
        return ""
    r, g, b = hex_to_rgb(color)
    if supports_truecolor():
        return f"\033[48;2;{r};{g};{b}m"
    if supports_256color():
        return f"\033[48;5;{rgb_to_256(r, g, b)}m"
    return rgb_to_16(r, g, b, fg=False)


# Modern Soft Palette
PRIMARY = "#38BDF8"  # Sky 400 (Bright, inviting modern cyan-sky)
PRIMARY_DARK = "#0284C7"  # Sky 600
ACCENT = "#818CF8"  # Indigo 400 (Subtle purple-blue)
SUCCESS = "#34D399"  # Emerald 400 (Mint green)
WARNING = "#FBBF24"  # Amber 400 (Warm gold)
ERROR = "#F87171"  # Rose 400 (Soft red)
TEXT = "#F8FAFC"  # Slate 50 (Crisp white)
MUTED = "#94A3B8"  # Slate 400 (Subtle silver)
DIM_TEXT = "#64748B"  # Slate 500 (Muted gray)
BORDER = "#475569"  # Slate 600 (Soft box borders)
HIGHLIGHT_BG = "#1E293B"  # Slate 800 (Selection row highlight)
HIGHLIGHT_FG = "#FFFFFF"  # Pure White
KEYCAP_BG = "#334155"  # Slate 700
KEYCAP_FG = "#E2E8F0"  # Slate 200

# Target specific badge colors
TARGET_COLORS: dict[str, tuple[str, str]] = {
    "codex": ("#1E3A8A", "#93C5FD"),  # Deep blue bg, light blue text
    "claude": ("#451A03", "#FDBA74"),  # Dark amber bg, soft peach text
    "opencode": ("#134E4A", "#5EEAD4"),  # Dark teal bg, mint text
    "cursor": ("#083344", "#67E8F9"),  # Dark cyan bg, electric cyan text
    "agy": ("#3B0764", "#D8B4FE"),  # Dark purple bg, lavender text
    "pi": ("#701A75", "#F0ABFC"),  # Dark fuchsia bg, pink text
}


def styled(
    text: str,
    fg_color: str = "",
    bg_color: str = "",
    *,
    bold: bool = False,
    dim: bool = False,
) -> str:
    """Format string with optional foreground, background, bold, and dim styles."""
    if not supports_color():
        return text
    parts: list[str] = []
    if bold:
        parts.append("\033[1m")
    if dim:
        parts.append("\033[2m")
    if fg_color:
        parts.append(fg(fg_color))
    if bg_color:
        parts.append(bg(bg_color))
    parts.append(text)
    parts.append("\033[0m")
    return "".join(parts)


def pill(label: str, bg_color: str, fg_color: str) -> str:
    """Render a compact styled pill badge with rounded/padded style."""
    if not supports_color():
        return f"[{label}]"
    return f"{bg(bg_color)}{fg(fg_color)} {label} \033[0m"


def target_badge(target: str) -> str:
    """Render a stylish pill badge for a given target adapter."""
    bg_c, fg_c = TARGET_COLORS.get(target.lower(), ("#1E293B", "#94A3B8"))
    return pill(target, bg_c, fg_c)


def keycap(key: str, action: str = "") -> str:
    """Render a keyboard shortcut hint styled like a physical keycap."""
    if not supports_color():
        return f"[{key}] {action}".strip()
    cap = f"{bg(KEYCAP_BG)}{fg(KEYCAP_FG)} {key} \033[0m"
    if action:
        return f"{cap} {fg(MUTED)}{action}\033[0m"
    return cap


def breadcrumb(step: int, total: int, title: str, context: str = "") -> str:
    """Render a step breadcrumb header with clear visual progress."""
    badge = styled(f"步骤 {step}/{total}", fg_color=PRIMARY, bold=True)
    step_str = styled(title, bold=True)
    ctx_str = f"  {fg(BORDER)}│{RESET}  {fg(MUTED)}{context}{RESET}" if context else ""
    return f"{fg(ACCENT)}🎯{RESET} {badge} {fg(BORDER)}›{RESET} {step_str}{ctx_str}\n"


BOLD = "\033[1m" if supports_color() else ""
DIM = "\033[2m" if supports_color() else ""
RESET = "\033[0m" if supports_color() else ""
