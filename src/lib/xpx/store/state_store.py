from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lib.common.common_store import atomic_write_bytes
from lib.common.errors import SwitchError
from lib.xpx.store import ensure_xpx_dirs, get_xpx_home, xpx_lock


@dataclass
class TargetState:
    """Current activation state for a specific target client."""

    active_type: str  # "provider" | "account" | "official" | "none"
    active_name: str  # Provider name, account name, or ""
    active_model: str | None = None  # Active model ID
    updated_at: str = ""  # ISO-8601 timestamp

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_type": self.active_type,
            "active_name": self.active_name,
            "active_model": self.active_model,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TargetState:
        if not isinstance(data, dict):
            return cls(active_type="none", active_name="")
        return cls(
            active_type=str(data.get("active_type", "none")),
            active_name=str(data.get("active_name", "")),
            active_model=data.get("active_model") or None,
            updated_at=str(data.get("updated_at", "")),
        )


@dataclass
class GlobalState:
    """Global activation state across all target clients."""

    version: int = 1
    targets: dict[str, TargetState] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "targets": {k: v.to_dict() for k, v in self.targets.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GlobalState:
        if not isinstance(data, dict):
            return cls()
        version = int(data.get("version", 1))
        raw_targets = data.get("targets") or {}
        targets = {
            k: TargetState.from_dict(v)
            for k, v in raw_targets.items()
            if isinstance(v, dict)
        }
        return cls(version=version, targets=targets)


class StateStore:
    """Manages reading and writing of ~/.xpx/state.json."""

    def __init__(self, home: Path | None = None) -> None:
        self._home = home or get_xpx_home()

    @property
    def state_path(self) -> Path:
        return self._home / "state.json"

    def load(self) -> GlobalState:
        if not self.state_path.is_file():
            return GlobalState()
        try:
            raw = self.state_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            return GlobalState.from_dict(data)
        except (OSError, json.JSONDecodeError) as exc:
            raise SwitchError(f"failed to load global state: {exc}") from exc

    def save(self, state: GlobalState) -> None:
        ensure_xpx_dirs()
        payload = (json.dumps(state.to_dict(), indent=2) + "\n").encode("utf-8")
        with xpx_lock():
            atomic_write_bytes(self.state_path, payload)

    def get_target_state(self, target: str) -> TargetState | None:
        return self.load().targets.get(target)

    def set_target_state(
        self,
        target: str,
        active_type: str,
        active_name: str,
        active_model: str | None = None,
    ) -> None:
        with xpx_lock():
            state = self.load()
            timestamp = datetime.now(UTC).isoformat()
            state.targets[target] = TargetState(
                active_type=active_type,
                active_name=active_name,
                active_model=active_model,
                updated_at=timestamp,
            )
            self.save(state)

    def remove_target_state(self, target: str) -> bool:
        with xpx_lock():
            state = self.load()
            if target in state.targets:
                del state.targets[target]
                self.save(state)
                return True
        return False
