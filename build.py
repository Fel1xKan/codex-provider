#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from lib.common.constants import VERSION  # noqa: E402

DIST_DIR = ROOT_DIR / "dist"
BUILD_TARGETS = {
    "codex": (
        ROOT_DIR / "codex-provider-bin.spec",
        "codex-provider.exe" if os.name == "nt" else "codex-provider",
        "cpx.exe" if os.name == "nt" else "cpx",
    ),
    "opencode": (
        ROOT_DIR / "opencode-provider.spec",
        "opencode-provider.exe" if os.name == "nt" else "opencode-provider",
        "opx.exe" if os.name == "nt" else "opx",
    ),
    "agy": (
        ROOT_DIR / "agy-provider.spec",
        "agy-provider.exe" if os.name == "nt" else "agy-provider",
        "apx.exe" if os.name == "nt" else "apx",
    ),
    "cursor": (
        ROOT_DIR / "cursor-provider.spec",
        "cursor-provider.exe" if os.name == "nt" else "cursor-provider",
        "cupx.exe" if os.name == "nt" else "cupx",
    ),
    "claude": (
        ROOT_DIR / "claude-provider.spec",
        "claude-provider.exe" if os.name == "nt" else "claude-provider",
        "clpx.exe" if os.name == "nt" else "clpx",
    ),
}

SHORT_TO_LEGACY = {
    "cpx": "codex-provider",
    "opx": "opencode-provider",
    "apx": "agy-provider",
    "cupx": "cursor-provider",
    "clpx": "claude-provider",
}


class BuildError(Exception):
    pass


def format_command(command: list[str]) -> str:
    return (
        subprocess.list2cmdline(command)
        if os.name == "nt"
        else " ".join(shlex.quote(p) for p in command)
    )


def select_python(override: str | None) -> list[str]:
    if override:
        return [override] if Path(override).is_file() else shlex.split(override)
    env_py = os.environ.get("PYTHON")
    if env_py:
        return [env_py] if Path(env_py).is_file() else shlex.split(env_py)
    for cand in (
        ROOT_DIR / ".venv" / "Scripts" / "python.exe",
        ROOT_DIR / ".venv" / "bin" / "python",
    ):
        if cand.is_file():
            return [str(cand)]
    return [sys.executable]


def run(command: list[str], *, quiet: bool = False) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=ROOT_DIR,
            check=True,
            stdout=subprocess.DEVNULL if quiet else None,
            stderr=subprocess.DEVNULL if quiet else None,
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
        res = subprocess.run(
            [*python_cmd, "-m", "PyInstaller", "--version"],
            cwd=ROOT_DIR,
            check=True,
            capture_output=True,
            text=True,
        )
        return res.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def verify_binary_version(path: Path, program: str) -> None:
    try:
        res = subprocess.run(
            [str(path), "--version"],
            cwd=ROOT_DIR,
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception as exc:
        raise BuildError(f"binary version check failed: {exc}") from exc

    expected = f"{program} {VERSION}"
    got = res.stdout.strip()
    if got != expected:
        raise BuildError(f"binary version mismatch: expected {expected!r}, got {got!r}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_target(python_cmd: list[str], target: str, skip_smoke_test: bool) -> None:
    spec_file, bin_name, short_name = BUILD_TARGETS[target]
    if not spec_file.is_file():
        raise BuildError(f"missing {spec_file.relative_to(ROOT_DIR)}")
    run([*python_cmd, "-m", "PyInstaller", "--clean", "-y", spec_file.name])
    output_bin = DIST_DIR / bin_name
    if not output_bin.is_file():
        raise BuildError(f"expected build output was not created: {output_bin}")
    short_bin = DIST_DIR / short_name
    shutil.copy2(output_bin, short_bin)
    if not skip_smoke_test:
        run([str(short_bin), "--help"], quiet=True)
    verify_binary_version(short_bin, short_name.removesuffix(".exe"))
    legacy_prog = SHORT_TO_LEGACY[short_name]
    legacy_bin = DIST_DIR / legacy_prog
    res = subprocess.run(
        [str(legacy_bin), "--version"],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
    )
    if res.returncode == 0:
        raise BuildError(f"legacy binary {legacy_prog} should refuse execution")
    checksum_file = DIST_DIR / f"{bin_name}.sha256"
    checksum = sha256_file(output_bin)
    checksum_file.write_text(f"{checksum}  {output_bin.name}\n", encoding="ascii")
    short_checksum_file = DIST_DIR / f"{short_name}.sha256"
    short_checksum = sha256_file(short_bin)
    short_checksum_file.write_text(
        f"{short_checksum}  {short_bin.name}\n", encoding="ascii"
    )
    print(
        "Built "
        f"{output_bin.relative_to(ROOT_DIR)} and {short_bin.relative_to(ROOT_DIR)}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build provider binaries.")
    parser.add_argument("--python", help="Python command used to run PyInstaller")
    parser.add_argument("--skip-smoke-test", action="store_true")
    parser.add_argument(
        "--target",
        choices=["all", *BUILD_TARGETS],
        default="all",
    )
    args = parser.parse_args()
    python_cmd = select_python(args.python)
    version = pyinstaller_version(python_cmd)
    if not version:
        print("error: PyInstaller is not installed", file=sys.stderr)
        return 1
    targets = list(BUILD_TARGETS) if args.target == "all" else [args.target]
    for target in targets:
        build_target(python_cmd, target, args.skip_smoke_test)
    return 0


if __name__ == "__main__":
    sys.exit(main())
