from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from lib.common.common_store import atomic_write_bytes
from lib.common.errors import SwitchError

DEFAULT_REPOSITORY = "Fel1xKan/codex-provider"
GITHUB_API_RELEASES = "https://api.github.com/repos/{repo}/releases"
RELEASE_TAG_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
DOWNLOAD_CHUNK_SIZE = 1024 * 1024
PROGRESS_UPDATE_INTERVAL = 0.1


@dataclass(frozen=True)
class UpgradePlan:
    current_version: str
    latest_version: str
    release_url: str
    asset_name: str
    asset_url: str
    sha256_url: str | None
    update_available: bool


def _format_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    units = ("KiB", "MiB", "GiB")
    value = float(size)
    for unit in units:
        value /= 1024
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}"
    return f"{value:.1f} GiB"


class UpgradeProgress:
    """Report concise upgrade stages and TTY-safe download progress."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self.stream = stream or sys.stderr
        self.interactive = bool(getattr(self.stream, "isatty", lambda: False)())
        self._dynamic_line = False
        self._last_update = 0.0

    def _finish_dynamic_line(self) -> None:
        if self._dynamic_line:
            print(file=self.stream, flush=True)
            self._dynamic_line = False

    def status(self, message: str) -> None:
        self._finish_dynamic_line()
        print(message, file=self.stream, flush=True)

    def download_started(self, asset_name: str, total: int | None) -> None:
        if self.interactive:
            self.download_progress(asset_name, 0, total, force=True)
            return
        detail = f" ({_format_size(total)})" if total is not None else ""
        self.status(f"downloading {asset_name}{detail}...")

    def download_progress(
        self,
        asset_name: str,
        downloaded: int,
        total: int | None,
        *,
        force: bool = False,
    ) -> None:
        if not self.interactive:
            return
        now = time.monotonic()
        if not force and now - self._last_update < PROGRESS_UPDATE_INTERVAL:
            return
        self._last_update = now
        if total is not None and total > 0:
            percent = min(100, downloaded * 100 // total)
            detail = f"{_format_size(downloaded)} / {_format_size(total)} ({percent}%)"
        else:
            detail = _format_size(downloaded)
        print(
            f"\rdownloading {asset_name}: {detail}",
            end="",
            file=self.stream,
            flush=True,
        )
        self._dynamic_line = True

    def download_finished(
        self, asset_name: str, downloaded: int, total: int | None
    ) -> None:
        if self.interactive:
            self.download_progress(asset_name, downloaded, total, force=True)
            self._finish_dynamic_line()

    def finish(self) -> None:
        self._finish_dynamic_line()


def _platform_key() -> str:
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64", "x64"):
        arch = "x86_64"
    elif machine in ("aarch64", "arm64"):
        arch = "arm64"
    else:
        raise SwitchError(f"unsupported architecture: {machine}")
    if sys.platform.startswith("linux"):
        return f"linux-{arch}"
    if sys.platform == "darwin":
        return f"macos-{arch}"
    if sys.platform.startswith("win"):
        return "windows-x86_64"
    raise SwitchError(f"unsupported platform: {sys.platform}")


def parse_version(value: str) -> tuple[int, int, int]:
    match = RELEASE_TAG_RE.match(value.strip())
    if not match:
        raise SwitchError(f"invalid version: {value!r}")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def fetch_latest_release(repository: str = DEFAULT_REPOSITORY) -> dict[str, Any]:
    url = GITHUB_API_RELEASES.format(repo=repository) + "/latest"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "codex-provider",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        OSError,
        json.JSONDecodeError,
    ) as exc:
        raise SwitchError(f"failed to fetch latest release: {exc}") from exc
    if not isinstance(payload, dict):
        raise SwitchError("unexpected GitHub API response")
    return payload


def build_upgrade_plan(
    repository: str,
    program: str,
    current_version: str,
    payload: dict[str, Any],
    legacy_name: str | None = None,
) -> UpgradePlan:
    tag = str(payload.get("tag_name", ""))
    latest = tag.lstrip("v") if tag.startswith("v") else tag
    latest_tuple = parse_version(latest)
    current_tuple = parse_version(current_version)
    update_available = latest_tuple > current_tuple

    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise SwitchError("release payload missing assets")
    platform_key = _platform_key()
    suffix = ".exe" if os.name == "nt" else ""
    names = [f"{program}-{latest}-{platform_key}{suffix}"]
    if legacy_name and legacy_name != program:
        names.append(f"{legacy_name}-{latest}-{platform_key}{suffix}")
    asset = None
    for expected in names:
        asset = next(
            (
                item
                for item in assets
                if isinstance(item, dict)
                and item.get("name") == expected
                and item.get("browser_download_url")
            ),
            None,
        )
        if asset is not None:
            break
    if asset is None:
        raise SwitchError(f"release {tag} has no asset for this platform: {names[0]}")
    expected = str(asset["name"])
    return UpgradePlan(
        current_version=current_version,
        latest_version=latest,
        release_url=str(payload.get("html_url", "")),
        asset_name=expected,
        asset_url=str(asset["browser_download_url"]),
        sha256_url=f"{asset['browser_download_url']}.sha256",
        update_available=update_available,
    )


def _download(
    url: str,
    dest: Path,
    progress: UpgradeProgress | None = None,
    display_name: str | None = None,
) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "codex-provider"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            name = display_name or dest.name
            raw_total = response.headers.get("Content-Length")
            try:
                total = int(raw_total) if raw_total else None
            except ValueError:
                total = None
            if total is not None and total < 0:
                total = None

            if progress is not None:
                progress.download_started(name, total)

            chunks = []
            downloaded = 0
            while chunk := response.read(DOWNLOAD_CHUNK_SIZE):
                chunks.append(chunk)
                downloaded += len(chunk)
                if progress is not None:
                    progress.download_progress(name, downloaded, total)

            if progress is not None:
                progress.download_finished(name, downloaded, total)
            atomic_write_bytes(dest, b"".join(chunks), secret=False)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
        if progress is not None:
            progress.finish()
        raise SwitchError(f"failed to download {url}: {exc}") from exc


def _sha256_hex(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_sha256(path: Path, expected: str) -> None:
    expected = expected.strip().split()[0].lower()
    actual = _sha256_hex(path)
    if actual != expected:
        raise SwitchError(f"checksum mismatch: expected {expected}, got {actual}")


def _sha256_expected_from_release(asset_url: str) -> str:
    request = urllib.request.Request(
        f"{asset_url}.sha256", headers={"User-Agent": "codex-provider"}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8").strip()
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
        raise SwitchError(f"failed to fetch checksum: {exc}") from exc


def current_executable() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    return Path(sys.argv[0]).resolve()


def _replace_binary(dest: Path, temp: Path) -> None:
    if os.name == "nt":
        shutil.copy2(temp, dest)
        temp.unlink(missing_ok=True)
    else:
        temp.chmod(dest.stat().st_mode if dest.exists() else 0o755)
        os.replace(temp, dest)


def perform_upgrade(
    plan: UpgradePlan,
    target: Path,
    progress: UpgradeProgress | None = None,
) -> int:
    if not plan.update_available:
        print(f"up to date: {plan.current_version}")
        return 0

    reporter = progress or UpgradeProgress()
    temp = target.with_name(f".{target.name}.upgrade")
    try:
        _download(plan.asset_url, temp, reporter, plan.asset_name)
        reporter.status("fetching SHA-256 checksum...")
        expected = _sha256_expected_from_release(plan.asset_url)
        reporter.status("verifying SHA-256 checksum...")
        verify_sha256(temp, expected)
        reporter.status("installing update...")
        _replace_binary(target, temp)
    except Exception:
        reporter.finish()
        temp.unlink(missing_ok=True)
        raise

    print(f"upgraded {target.name}: {plan.current_version} -> {plan.latest_version}")
    return 0
