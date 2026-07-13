from __future__ import annotations

import ctypes
import os
import shlex
import subprocess
import sys
from pathlib import Path

from codex_provider_lib.errors import SwitchError

if os.name == "nt":
    from ctypes import wintypes
else:
    import select
    import termios
    import tty


def split_command(value: str) -> list[str]:
    if os.name != "nt":
        return shlex.split(value)

    argc = ctypes.c_int()
    ctypes.windll.shell32.CommandLineToArgvW.argtypes = [
        wintypes.LPCWSTR,
        ctypes.POINTER(ctypes.c_int),
    ]
    ctypes.windll.shell32.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
    ctypes.windll.kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    ctypes.windll.kernel32.LocalFree.restype = wintypes.HLOCAL
    argv = ctypes.windll.shell32.CommandLineToArgvW(value, ctypes.byref(argc))
    if not argv:
        raise SwitchError(f"could not parse command: {value}")
    try:
        return [argv[index] for index in range(argc.value)]
    finally:
        ctypes.windll.kernel32.LocalFree(argv)


def run_editor(path: Path) -> None:
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if not editor:
        raise SwitchError("set VISUAL or EDITOR to use edit")
    try:
        command = split_command(editor)
    except ValueError as exc:
        raise SwitchError(f"unable to parse editor command: {exc}") from exc
    if not command:
        raise SwitchError("VISUAL or EDITOR must not be empty")
    try:
        result = subprocess.run([*command, str(path)])
    except OSError as exc:
        raise SwitchError(f"unable to start editor {command[0]}: {exc}") from exc
    if result.returncode != 0:
        raise SwitchError(f"editor exited with status {result.returncode}")


def _read_key(fd: int) -> bytes:
    ch = os.read(fd, 1)
    if ch == b"\x1b":
        ready, _, _ = select.select([fd], [], [], 0.1)
        if ready:
            return ch + os.read(fd, 2)
    return ch


def select_provider_windows(current: str, names: list[str]) -> str | None:
    print("Providers:")
    for index, name in enumerate(names, start=1):
        marker = "*" if name == current else " "
        print(f"{index:>2}. {marker} {name}")
    print("Enter a number to select, or press Enter to cancel.")
    value = input("Provider: ").strip()
    if not value:
        return None
    try:
        index = int(value)
    except ValueError as exc:
        raise SwitchError("provider selection must be a number") from exc
    if index < 1 or index > len(names):
        raise SwitchError(f"provider selection must be between 1 and {len(names)}")
    return names[index - 1]


def _render_provider_menu(names: list[str], cursor: int, current: str) -> None:
    for index, name in enumerate(names):
        marker = "*" if name == current else " "
        pointer = ">" if index == cursor else " "
        line = f"{pointer}{marker} {name}"
        if index == cursor:
            line = f"\x1b[7m{line}\x1b[0m"
        sys.stdout.write("\r\x1b[K" + line + "\r\n")
    sys.stdout.flush()


def _redraw_provider_menu(names: list[str], cursor: int, current: str) -> None:
    sys.stdout.write(f"\x1b[{len(names)}A")
    _render_provider_menu(names, cursor, current)


def _clear_render(lines: int) -> None:
    sys.stdout.write(f"\x1b[{lines}A\r\x1b[J")
    sys.stdout.flush()


def select_provider_interactive(current: str, providers: list[str]) -> str | None:
    if not providers:
        raise SwitchError("no providers available; add one with 'add' first")
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise SwitchError(
            "no provider specified and stdin/stdout is not a TTY; pass a provider name"
        )

    names = sorted(providers)
    if os.name == "nt":
        return select_provider_windows(current, names)

    cursor = names.index(current) if current in names else 0
    count = len(names)
    hint_lines = 1

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    chosen: str | None = None
    try:
        tty.setraw(fd)
        sys.stdout.write("Up/Down move, Enter select, Esc cancel\r\n")
        _render_provider_menu(names, cursor, current)
        while True:
            key = _read_key(fd)
            if key in (b"\r", b"\n"):
                chosen = names[cursor]
                break
            if key == b"\x03":
                raise KeyboardInterrupt
            if key == b"\x1b[A":
                cursor = (cursor - 1) % count
                _redraw_provider_menu(names, cursor, current)
            elif key == b"\x1b[B":
                cursor = (cursor + 1) % count
                _redraw_provider_menu(names, cursor, current)
            elif key == b"\x1b":
                chosen = None
                break
    finally:
        _clear_render(count + hint_lines)
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    return chosen
