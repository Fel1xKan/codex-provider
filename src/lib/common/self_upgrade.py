from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lib.common.common_store import atomic_write_bytes
from lib.common.errors import SwitchError

DEFAULT_REPOSITORY = "Fel1xKan/codex-provider"
GITHUB_API_RELEASES = "https://api.github.com/repos/{repo}/releases"
RELEASE_TAG_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


@dataclass(frozen=True)
class UpgradePlan:
    current_version: str
    latest_version: str
    release_url: str
    asset_name: str
    asset_url: str
    sha256_url: str | None
    update_available: bool


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
    prefix = f"{program}-{latest}-{platform_key}"
    suffix = ".exe" if os.name == "nt" else ""
    expected = f"{prefix}{suffix}"
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
    if asset is None:
        raise SwitchError(
            f"release {tag} has no asset for this platform: {expected}"
        )
    return UpgradePlan(
        current_version=current_version,
        latest_version=latest,
        release_url=str(payload.get("html_url", "")),
        asset_name=expected,
        asset_url=str(asset["browser_download_url"]),
        sha256_url=f"{asset['browser_download_url']}.sha256",
        update_available=update_available,
    )


def _download(url: str, dest: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "codex-provider"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            atomic_write_bytes(dest, response.read(), secret=False)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
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
        raise SwitchError(
            f"checksum mismatch: expected {expected}, got {actual}"
        )


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


def perform_upgrade(plan: UpgradePlan, target: Path) -> int:
    if not plan.update_available:
        print(f"up to date: {plan.current_version}")
        return 0

    temp = target.with_name(f".{target.name}.upgrade")
    try:
        _download(plan.asset_url, temp)
        expected = _sha256_expected_from_release(plan.asset_url)
        verify_sha256(temp, expected)
        _replace_binary(target, temp)
    except Exception:
        temp.unlink(missing_ok=True)
        raise

    print(f"upgraded {target.name}: {plan.current_version} -> {plan.latest_version}")
    return 0
