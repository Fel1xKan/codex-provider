from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterable
from contextlib import suppress
from pathlib import Path

from lib.common.constants import PRIVATE_DIR_MODE, SECRET_FILE_MODE


def load_recent_providers(path: Path) -> list[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict):
        return []
    recent = data.get("recent")
    if not isinstance(recent, list):
        return []
    names: list[str] = []
    seen: set[str] = set()
    for item in recent:
        if not isinstance(item, str) or not item or item in seen:
            continue
        seen.add(item)
        names.append(item)
    return names


def ensure_recent_providers(path: Path) -> list[str]:
    if not path.exists():
        save_recent_providers(path, [])
    return load_recent_providers(path)


def save_recent_providers(path: Path, recent: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=PRIVATE_DIR_MODE)
    if path.parent.exists():
        with suppress(OSError):
            path.parent.chmod(PRIVATE_DIR_MODE)
    payload = json.dumps({"recent": recent}, ensure_ascii=False, indent=2) + "\n"
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temp:
            temp_path = Path(temp.name)
            temp.write(payload.encode("utf-8"))
            temp.flush()
            os.fsync(temp.fileno())
        with suppress(OSError):
            temp_path.chmod(SECRET_FILE_MODE)
        os.replace(temp_path, path)
        temp_path = None
    finally:
        if temp_path is not None:
            with suppress(OSError):
                temp_path.unlink(missing_ok=True)


def record_recent_provider(path: Path, provider: str) -> list[str]:
    recent = [provider]
    for name in load_recent_providers(path):
        if name != provider:
            recent.append(name)
    save_recent_providers(path, recent)
    return recent


def forget_recent_provider(path: Path, provider: str) -> list[str]:
    recent = [name for name in load_recent_providers(path) if name != provider]
    if path.exists() or recent:
        save_recent_providers(path, recent)
    return recent


def rename_recent_provider(path: Path, old: str, new: str) -> list[str]:
    recent: list[str] = []
    seen: set[str] = set()
    for name in load_recent_providers(path):
        updated = new if name == old else name
        if updated in seen:
            continue
        seen.add(updated)
        recent.append(updated)
    if path.exists() or recent:
        save_recent_providers(path, recent)
    return recent


def sort_providers_by_recent(
    providers: Iterable[str],
    recent: list[str],
) -> list[str]:
    names = list(providers)
    remaining = set(names)
    ordered: list[str] = []
    for name in recent:
        if name in remaining:
            ordered.append(name)
            remaining.remove(name)
    ordered.extend(sorted(remaining))
    return ordered
