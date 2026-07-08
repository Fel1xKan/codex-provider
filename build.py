#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
SPEC_FILE = ROOT_DIR / "codex-provider-bin.spec"
DIST_DIR = ROOT_DIR / "dist"
BIN_NAME = "codex-provider-bin.exe" if os.name == "nt" else "codex-provider-bin"
OUTPUT_BIN = DIST_DIR / BIN_NAME


class BuildError(Exception):
    pass


def format_command(command: list[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(command)
    return " ".join(shlex.quote(part) for part in command)


def split_command(value: str) -> list[str]:
    if os.name != "nt":
        return shlex.split(value)

    import ctypes
    from ctypes import wintypes

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
        raise BuildError(f"could not parse command: {value}")

    try:
        return [argv[index] for index in range(argc.value)]
    finally:
        ctypes.windll.kernel32.LocalFree(argv)


def parse_python_command(value: str) -> list[str]:
    if Path(value).is_file():
        return [value]
    return split_command(value)


def existing_venv_python() -> Path | None:
    candidates = [
        ROOT_DIR / ".venv" / "Scripts" / "python.exe",
        ROOT_DIR / ".venv" / "bin" / "python",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def select_python(override: str | None) -> list[str]:
    if override:
        return parse_python_command(override)

    env_python = os.environ.get("PYTHON")
    if env_python:
        return parse_python_command(env_python)

    venv_python = existing_venv_python()
    if venv_python is not None:
        return [str(venv_python)]

    return [sys.executable]


def run(command: list[str], *, quiet: bool = False) -> subprocess.CompletedProcess[str]:
    stdout = subprocess.DEVNULL if quiet else None
    stderr = subprocess.DEVNULL if quiet else None
    try:
        return subprocess.run(
            command,
            cwd=ROOT_DIR,
            check=True,
            stdout=stdout,
            stderr=stderr,
            text=True,
        )
    except OSError as exc:
        raise BuildError(f"could not run {format_command(command)}: {exc}") from exc
    except subprocess.CalledProcessError as exc:
        raise BuildError(
            f"command failed with exit code {exc.returncode}: {format_command(command)}"
        ) from exc


def pyinstaller_version(python_cmd: list[str]) -> str | None:
    try:
        result = subprocess.run(
            [*python_cmd, "-m", "PyInstaller", "--version"],
            cwd=ROOT_DIR,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None

    return result.stdout.strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the standalone codex-provider binary with PyInstaller.",
    )
    parser.add_argument(
        "--python",
        help="Python command used to run PyInstaller. Defaults to PYTHON, .venv, then this interpreter.",
    )
    parser.add_argument(
        "--skip-smoke-test",
        action="store_true",
        help="Skip the post-build '--help' check for the generated binary.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        python_cmd = select_python(args.python)
    except (BuildError, ValueError) as exc:
        print(f"error: invalid Python command: {exc}", file=sys.stderr)
        return 1

    if not SPEC_FILE.is_file():
        print(f"error: missing {SPEC_FILE.relative_to(ROOT_DIR)}", file=sys.stderr)
        return 1

    version = pyinstaller_version(python_cmd)
    if version is None:
        python_display = format_command(python_cmd)
        print(f"error: PyInstaller is not installed for {python_display}", file=sys.stderr)
        print(f"install it with: {python_display} -m pip install -r requirements.txt", file=sys.stderr)
        return 1

    print(f"Using Python: {format_command(python_cmd)}", flush=True)
    print(f"Using PyInstaller: {version}", flush=True)

    try:
        run([*python_cmd, "-m", "PyInstaller", "--clean", "-y", str(SPEC_FILE.name)])

        if not OUTPUT_BIN.is_file():
            print(f"error: expected build output was not created: {OUTPUT_BIN}", file=sys.stderr)
            return 1

        if not args.skip_smoke_test:
            run([str(OUTPUT_BIN), "--help"], quiet=True)
    except BuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Built {OUTPUT_BIN.relative_to(ROOT_DIR)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
