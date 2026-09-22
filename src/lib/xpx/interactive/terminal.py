from __future__ import annotations

import atexit
import contextlib
import os
import select
import sys
from typing import Any

# ANSI escape sequence constants
ESC = "\033"
CLEAR_LINE = f"{ESC}[2K"
CURSOR_HIDE = f"{ESC}[?25l"
CURSOR_SHOW = f"{ESC}[?25h"
MOUSE_ENABLE = f"{ESC}[?1000h{ESC}[?1006h"
MOUSE_DISABLE = f"{ESC}[?1000l{ESC}[?1006l"


class KeyCode:
    UP = "UP"
    DOWN = "DOWN"
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    ENTER = "ENTER"
    SPACE = "SPACE"
    BACKSPACE = "BACKSPACE"
    TAB = "TAB"
    ESC = "ESC"
    HOME = "HOME"
    END = "END"
    PAGE_UP = "PAGE_UP"
    PAGE_DOWN = "PAGE_DOWN"
    CHAR = "CHAR"
    MOUSE_WHEEL_UP = "MOUSE_WHEEL_UP"
    MOUSE_WHEEL_DOWN = "MOUSE_WHEEL_DOWN"
    MOUSE_CLICK = "MOUSE_CLICK"
    EOF = "EOF"
    UNKNOWN = "UNKNOWN"


class InputEvent:
    def __init__(
        self,
        code: str,
        char: str = "",
        mouse_x: int = 0,
        mouse_y: int = 0,
    ) -> None:
        self.code = code
        self.char = char
        self.mouse_x = mouse_x
        self.mouse_y = mouse_y

    def __repr__(self) -> str:
        return (
            f"InputEvent({self.code}, char={self.char!r}, "
            f"x={self.mouse_x}, y={self.mouse_y})"
        )


_active_session: TerminalSession | None = None


def _cleanup_terminal() -> None:
    global _active_session
    if _active_session is not None:
        _active_session.restore()
        _active_session = None


atexit.register(_cleanup_terminal)


class TerminalSession:
    """Context manager setting cbreak mode, mouse reporting, and cursor state."""

    def __init__(self, enable_mouse: bool = True, hide_cursor: bool = True) -> None:
        self.enable_mouse = enable_mouse
        self.hide_cursor = hide_cursor
        self.fd = sys.stdin.fileno() if sys.stdin.isatty() else None
        self.old_settings: Any = None
        self._is_cbreak = False

    def __enter__(self) -> TerminalSession:
        global _active_session
        _active_session = self
        self.setup()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        global _active_session
        self.restore()
        _active_session = None

    def setup(self) -> None:
        if self.fd is None:
            return

        if os.name != "nt":
            import termios
            import tty

            with contextlib.suppress(Exception):
                self.old_settings = termios.tcgetattr(self.fd)
                # Use setcbreak rather than setraw to keep OPOST
                # (output postprocessing) enabled, ensuring \n properly
                # translates to \r\n and prevents stair-stepping.
                tty.setcbreak(self.fd)
                self._is_cbreak = True
        else:
            self._setup_windows()

        if self.hide_cursor:
            sys.stdout.write(CURSOR_HIDE)
        if self.enable_mouse:
            sys.stdout.write(MOUSE_ENABLE)
        sys.stdout.flush()

    def _setup_windows(self) -> None:
        """Enable Virtual Terminal Processing and UTF-8 console mode on Windows."""
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        h_out = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        h_in = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE

        out_mode = wintypes.DWORD()
        in_mode = wintypes.DWORD()
        self._old_out_mode: int | None = None
        self._old_in_mode: int | None = None
        self._old_cp: int | None = None
        self._old_output_cp: int | None = None

        with contextlib.suppress(Exception):
            if kernel32.GetConsoleMode(h_out, ctypes.byref(out_mode)):
                self._old_out_mode = out_mode.value
                # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
                kernel32.SetConsoleMode(h_out, out_mode.value | 0x0004)

            if kernel32.GetConsoleMode(h_in, ctypes.byref(in_mode)):
                self._old_in_mode = in_mode.value
                # ENABLE_VIRTUAL_TERMINAL_INPUT = 0x0200
                new_in = in_mode.value | 0x0200
                if self.enable_mouse:
                    # ENABLE_MOUSE_INPUT = 0x0010, ENABLE_EXTENDED_FLAGS = 0x0080
                    new_in |= 0x0010 | 0x0080
                kernel32.SetConsoleMode(h_in, new_in)

            self._old_cp = kernel32.GetConsoleCP()
            self._old_output_cp = kernel32.GetConsoleOutputCP()
            kernel32.SetConsoleCP(65001)
            kernel32.SetConsoleOutputCP(65001)
            if hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(encoding="utf-8")

    def restore(self) -> None:
        if self.enable_mouse:
            sys.stdout.write(MOUSE_DISABLE)
        if self.hide_cursor:
            sys.stdout.write(CURSOR_SHOW)
        sys.stdout.flush()

        if self.fd is not None and self._is_cbreak and os.name != "nt":
            import termios

            with contextlib.suppress(Exception):
                termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old_settings)
            self._is_cbreak = False
        elif os.name == "nt":
            self._restore_windows()

    def _restore_windows(self) -> None:
        """Restore previous console modes on Windows."""
        import ctypes

        kernel32 = ctypes.windll.kernel32
        with contextlib.suppress(Exception):
            if getattr(self, "_old_out_mode", None) is not None:
                h_out = kernel32.GetStdHandle(-11)
                kernel32.SetConsoleMode(h_out, self._old_out_mode)
            if getattr(self, "_old_in_mode", None) is not None:
                h_in = kernel32.GetStdHandle(-10)
                kernel32.SetConsoleMode(h_in, self._old_in_mode)
            if getattr(self, "_old_cp", None) is not None:
                kernel32.SetConsoleCP(self._old_cp)
            if getattr(self, "_old_output_cp", None) is not None:
                kernel32.SetConsoleOutputCP(self._old_output_cp)

    def _has_bytes(self, timeout: float = 0.04) -> bool:
        if self.fd is None:
            return False
        r, _, _ = select.select([self.fd], [], [], timeout)
        return bool(r)

    def _read_byte(self, timeout: float | None = None) -> int | None:
        """Read a single byte without Python TextIO buffering."""
        if timeout is not None and not self._has_bytes(timeout):
            return None
        if self.fd is not None:
            try:
                data = os.read(self.fd, 1)
                return data[0] if data else None
            except Exception:
                pass
        try:
            ch = sys.stdin.read(1)
            return ord(ch) if ch else None
        except Exception:
            return None

    def read_event(self) -> InputEvent:
        if self.fd is None and not sys.stdin.isatty():
            line = sys.stdin.readline()
            if not line:
                return InputEvent(KeyCode.EOF)
            clean = line.strip()
            if clean:
                return InputEvent(KeyCode.CHAR, char=clean)
            return InputEvent(KeyCode.ENTER)

        if os.name == "nt":
            return self._read_event_windows()

        b = self._read_byte()
        if b is None:
            return InputEvent(KeyCode.EOF)

        if b == 0x03:
            raise KeyboardInterrupt()

        if b in (0x0D, 0x0A):
            return InputEvent(KeyCode.ENTER)

        if b == 0x20:
            return InputEvent(KeyCode.SPACE, char=" ")

        if b in (0x7F, 0x08):
            return InputEvent(KeyCode.BACKSPACE)

        if b == 0x09:
            return InputEvent(KeyCode.TAB)

        if b == 0x1B:
            return self._parse_escape_sequence()

        # Handle UTF-8 multibyte characters
        char_bytes = bytes([b])
        extra_len = 0
        if (b & 0xE0) == 0xC0:
            extra_len = 1
        elif (b & 0xF0) == 0xE0:
            extra_len = 2
        elif (b & 0xF8) == 0xF0:
            extra_len = 3

        while extra_len > 0 and self._has_bytes(0.05):
            nxt = self._read_byte(0.05)
            if nxt is None:
                break
            char_bytes += bytes([nxt])
            extra_len -= 1

        try:
            ch = char_bytes.decode("utf-8")
            if ch.isprintable():
                return InputEvent(KeyCode.CHAR, char=ch)
        except Exception:
            pass

        return InputEvent(KeyCode.UNKNOWN)

    def _parse_escape_sequence(self) -> InputEvent:
        """Parses escape sequences according to ECMA-48.

        Only a standalone lone ESC with no following bytes returns KeyCode.ESC.
        Any unrecognized sequence returns KeyCode.UNKNOWN so it never cancels out.
        """
        # If no bytes follow within 40ms, the user hit the physical Esc key!
        if not self._has_bytes(0.04):
            return InputEvent(KeyCode.ESC)

        b1 = self._read_byte(0.05)
        if b1 is None:
            return InputEvent(KeyCode.ESC)

        c1 = chr(b1)
        if c1 == "[":
            # CSI sequence: read parameter bytes until terminating
            # character (0x40 - 0x7E)
            params = ""
            final = ""
            while self._has_bytes(0.05):
                nb = self._read_byte(0.05)
                if nb is None:
                    break
                if 0x40 <= nb <= 0x7E:
                    final = chr(nb)
                    break
                params += chr(nb)

            if not final:
                return InputEvent(KeyCode.UNKNOWN)

            if final == "A":
                return InputEvent(KeyCode.UP)
            if final == "B":
                return InputEvent(KeyCode.DOWN)
            if final == "C":
                return InputEvent(KeyCode.RIGHT)
            if final == "D":
                return InputEvent(KeyCode.LEFT)
            if final == "H":
                return InputEvent(KeyCode.HOME)
            if final == "F":
                return InputEvent(KeyCode.END)
            if final == "~":
                if params == "5":
                    return InputEvent(KeyCode.PAGE_UP)
                if params == "6":
                    return InputEvent(KeyCode.PAGE_DOWN)
                if params in ("1", "7"):
                    return InputEvent(KeyCode.HOME)
                if params in ("4", "8"):
                    return InputEvent(KeyCode.END)
                return InputEvent(KeyCode.UNKNOWN)
            if final in ("M", "m") and params.startswith("<"):
                # SGR mouse event format: <btn;col;rowM (press) or m (release)
                try:
                    parts = params[1:].split(";")
                    if len(parts) == 3:
                        btn = int(parts[0])
                        col = int(parts[1])
                        row = int(parts[2])
                        if btn == 64:
                            return InputEvent(
                                KeyCode.MOUSE_WHEEL_UP, mouse_x=col, mouse_y=row
                            )
                        if btn == 65:
                            return InputEvent(
                                KeyCode.MOUSE_WHEEL_DOWN, mouse_x=col, mouse_y=row
                            )
                        if btn == 0 and final == "M":
                            return InputEvent(
                                KeyCode.MOUSE_CLICK, mouse_x=col, mouse_y=row
                            )
                except (ValueError, IndexError):
                    pass
                return InputEvent(KeyCode.UNKNOWN)

            # Any unhandled CSI sequence (e.g. CPR reports, focus, etc.) is ignored
            return InputEvent(KeyCode.UNKNOWN)

        elif c1 == "O":
            # SS3 sequence (e.g. \x1bOA, \x1bOB for up/down)
            b2 = self._read_byte(0.05)
            if b2 is not None:
                c2 = chr(b2)
                if c2 == "H":
                    return InputEvent(KeyCode.HOME)
                if c2 == "F":
                    return InputEvent(KeyCode.END)
                if c2 == "A":
                    return InputEvent(KeyCode.UP)
                if c2 == "B":
                    return InputEvent(KeyCode.DOWN)
            return InputEvent(KeyCode.UNKNOWN)

        return InputEvent(KeyCode.UNKNOWN)

    def _read_event_windows(self) -> InputEvent:
        """Read input event on Windows console using msvcrt without select.select()."""
        import msvcrt
        import time

        while True:
            if not msvcrt.kbhit():
                time.sleep(0.01)
                continue

            ch = msvcrt.getwch()
            if ch == "\x03":  # Ctrl+C
                raise KeyboardInterrupt()

            if ch in ("\r", "\n"):
                return InputEvent(KeyCode.ENTER)

            if ch == " ":
                return InputEvent(KeyCode.SPACE, char=" ")

            if ch in ("\x08", "\x7f"):
                return InputEvent(KeyCode.BACKSPACE)

            if ch == "\t":
                return InputEvent(KeyCode.TAB)

            if ch == "\x1b":
                # Check if ANSI sequence follows within 40ms
                start = time.time()
                has_more = False
                while time.time() - start < 0.04:
                    if msvcrt.kbhit():
                        has_more = True
                        break
                    time.sleep(0.005)
                if not has_more:
                    return InputEvent(KeyCode.ESC)
                return self._parse_escape_sequence_windows()

            if ch in ("\x00", "\xe0"):
                # Windows scan codes (arrows, page up/down, home/end)
                if msvcrt.kbhit():
                    sc = msvcrt.getwch()
                    key_map = {
                        "H": KeyCode.UP,
                        "P": KeyCode.DOWN,
                        "K": KeyCode.LEFT,
                        "M": KeyCode.RIGHT,
                        "G": KeyCode.HOME,
                        "O": KeyCode.END,
                        "I": KeyCode.PAGE_UP,
                        "Q": KeyCode.PAGE_DOWN,
                    }
                    if sc in key_map:
                        return InputEvent(key_map[sc])
                return InputEvent(KeyCode.UNKNOWN)

            if ch.isprintable():
                return InputEvent(KeyCode.CHAR, char=ch)

            return InputEvent(KeyCode.UNKNOWN)

    def _parse_escape_sequence_windows(self) -> InputEvent:
        """Parse ANSI sequences (e.g. from Windows Terminal) on Windows."""
        import msvcrt
        import time

        def _get_ch(timeout: float = 0.05) -> str | None:
            start = time.time()
            while time.time() - start < timeout:
                if msvcrt.kbhit():
                    return msvcrt.getwch()
                time.sleep(0.005)
            return None

        c1 = _get_ch(0.05)
        if c1 is None:
            return InputEvent(KeyCode.ESC)

        if c1 == "[":
            params = ""
            final = ""
            while True:
                nb = _get_ch(0.05)
                if nb is None:
                    break
                if 0x40 <= ord(nb) <= 0x7E:
                    final = nb
                    break
                params += nb

            if not final:
                return InputEvent(KeyCode.UNKNOWN)

            if final == "A":
                return InputEvent(KeyCode.UP)
            if final == "B":
                return InputEvent(KeyCode.DOWN)
            if final == "C":
                return InputEvent(KeyCode.RIGHT)
            if final == "D":
                return InputEvent(KeyCode.LEFT)
            if final == "H":
                return InputEvent(KeyCode.HOME)
            if final == "F":
                return InputEvent(KeyCode.END)
            if final == "~":
                if params == "5":
                    return InputEvent(KeyCode.PAGE_UP)
                if params == "6":
                    return InputEvent(KeyCode.PAGE_DOWN)
                if params in ("1", "7"):
                    return InputEvent(KeyCode.HOME)
                if params in ("4", "8"):
                    return InputEvent(KeyCode.END)
                return InputEvent(KeyCode.UNKNOWN)
            if final in ("M", "m") and params.startswith("<"):
                try:
                    parts = params[1:].split(";")
                    if len(parts) == 3:
                        btn = int(parts[0])
                        col = int(parts[1])
                        row = int(parts[2])
                        if btn == 64:
                            return InputEvent(
                                KeyCode.MOUSE_WHEEL_UP, mouse_x=col, mouse_y=row
                            )
                        if btn == 65:
                            return InputEvent(
                                KeyCode.MOUSE_WHEEL_DOWN, mouse_x=col, mouse_y=row
                            )
                        if btn == 0 and final == "M":
                            return InputEvent(
                                KeyCode.MOUSE_CLICK, mouse_x=col, mouse_y=row
                            )
                except (ValueError, IndexError):
                    pass
                return InputEvent(KeyCode.UNKNOWN)
            return InputEvent(KeyCode.UNKNOWN)
        elif c1 == "O":
            c2 = _get_ch(0.05)
            if c2 == "H":
                return InputEvent(KeyCode.HOME)
            if c2 == "F":
                return InputEvent(KeyCode.END)
            if c2 == "A":
                return InputEvent(KeyCode.UP)
            if c2 == "B":
                return InputEvent(KeyCode.DOWN)
        return InputEvent(KeyCode.UNKNOWN)
