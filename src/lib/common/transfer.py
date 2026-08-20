from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from lib.common.common_store import SECRET_FILE_MODE, atomic_write_bytes
from lib.common.errors import SwitchError


def read_import_data(file_path: str | None) -> dict[str, Any]:
    if not file_path or file_path == "-":
        raw_data = sys.stdin.read()
    else:
        path = Path(file_path).expanduser()
        if not path.exists():
            raise SwitchError(f"import file not found: {path}")
        raw_data = path.read_text(encoding="utf-8")

    try:
        data = json.loads(raw_data)
    except Exception as exc:
        raise SwitchError(f"invalid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise SwitchError("imported data must be a JSON object")
    return data


def validate_export(data: dict[str, Any], expected_type: str) -> None:
    if data.get("type") != expected_type:
        found = data.get("type")
        raise SwitchError(
            f"invalid export file type: expected {expected_type}, found {found}"
        )
    version = data.get("version")
    if version != 1:
        raise SwitchError(f"unsupported version: {version}")


def write_export(payload: str, file_path: str | None, label: str) -> None:
    if not file_path or file_path == "-":
        sys.stdout.write(payload)
        return
    path = Path(file_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(
        path,
        payload.encode("utf-8"),
        secret=True,
        mode=SECRET_FILE_MODE,
    )
    print(f"exported {label} configuration and auth to {path}")
