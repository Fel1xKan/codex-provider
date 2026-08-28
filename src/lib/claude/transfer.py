from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import lib.claude.store as st
from lib.common.common_store import atomic_write_bytes
from lib.common.constants import SECRET_FILE_MODE
from lib.common.errors import SwitchError


def _read_export(file_path: str | None) -> dict[str, Any]:
    if file_path in (None, "-"):
        import sys

        text = sys.stdin.read()
    else:
        text = Path(file_path).read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SwitchError(f"invalid export JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise SwitchError("export JSON must contain an object")
    return data


def export_command(file_path: str | None) -> int:
    state = st.ensure_provider_state(read_only=True)
    payload = {
        "version": 1,
        "settings_path": str(state.settings_path),
        "active_provider": state.active_provider,
        "providers": state.providers,
    }
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if file_path in (None, "-"):
        print(text, end="")
    else:
        Path(file_path).write_text(text, encoding="utf-8")
    return 0


def import_command(file_path: str | None, dry_run: bool) -> int:
    data = _read_export(file_path)
    providers = data.get("providers", {})
    if not isinstance(providers, dict):
        raise SwitchError("export providers must be an object")
    settings_path = data.get("settings_path")
    if not isinstance(settings_path, str) or not settings_path:
        raise SwitchError("export settings_path must be a non-empty string")
    active_provider = data.get("active_provider", "")
    if not isinstance(active_provider, str):
        raise SwitchError("export active_provider must be a string")
    payload = {
        "settings_path": settings_path,
        "active_provider": active_provider,
        "providers": providers,
    }
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if not dry_run:
        st.ensure_tool_home()
        atomic_write_bytes(
            st.tool_config_path(),
            text.encode("utf-8"),
            secret=True,
            mode=SECRET_FILE_MODE,
        )
    action = "would import" if dry_run else "imported"
    print(f"{action} provider registry: {st.tool_config_path()}")
    return 0
