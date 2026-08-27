from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import lib.codex.store as st
from lib.common.common_store import SECRET_FILE_MODE, atomic_write_bytes
from lib.common.constants import MODE_OFFICIAL
from lib.common.errors import SwitchError

BACKUP_KEEP_COUNT = 10
BACKUP_METADATA_FIELD = "codex_provider_backup"


def backup_dir() -> Path:
    return st.tool_home() / "backups"


def _load_auth_payload(profile: Path) -> dict[str, Any]:
    from lib.codex.doctor import load_auth_json

    return load_auth_json(profile)


def create_snapshot(
    action: str,
    provider: str | None = None,
    *,
    state: st.ProviderState | None = None,
) -> str:
    if state is None:
        state = st.ensure_provider_state(read_only=True)
    now = datetime.now(UTC)
    token = f"{now.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    providers: dict[str, dict[str, Any]] = {}
    for name, config in state.providers.items():
        profile = st.auth_profile_path(name, create=False)
        auth = _load_auth_payload(profile) if profile.exists() else {}
        providers[name] = {"config": dict(config), "auth": auth}

    payload = {
        "type": "codex-provider",
        "version": 1,
        "active_provider": state.active_provider,
        "providers": providers,
        BACKUP_METADATA_FIELD: {
            "token": token,
            "created_at": now.isoformat(),
            "action": action,
            "provider": provider,
        },
    }
    target = backup_dir() / f"{token}.json"
    atomic_write_bytes(
        target,
        (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
        secret=True,
        mode=SECRET_FILE_MODE,
    )
    _prune_snapshots()
    return token


def _prune_snapshots() -> None:
    snapshots = sorted(
        item
        for item in backup_dir().glob("*.json")
        if item.name.endswith(".json") and len(item.stem.split("-")[-1]) == 8
    )
    for item in snapshots[:-BACKUP_KEEP_COUNT]:
        try:
            item.unlink()
        except OSError as exc:
            raise SwitchError(f"unable to prune snapshot {item}: {exc}") from exc


def list_snapshots() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for path in sorted(backup_dir().glob("*.json"), reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        metadata = payload.get(BACKUP_METADATA_FIELD)
        if not isinstance(metadata, dict):
            continue
        results.append(
            {
                "token": metadata.get("token", path.stem),
                "created_at": metadata.get("created_at", ""),
                "action": metadata.get("action", ""),
                "provider": metadata.get("provider"),
                "active_provider": payload.get("active_provider", ""),
                "official": _snapshot_has_official(payload),
                "path": str(path),
            }
        )
    return results


def _snapshot_has_official(payload: dict[str, Any]) -> bool:
    providers = payload.get("providers")
    if not isinstance(providers, dict):
        return False
    return any(
        isinstance(info, dict)
        and isinstance(info.get("config"), dict)
        and info["config"].get("mode") == MODE_OFFICIAL
        for info in providers.values()
    )
