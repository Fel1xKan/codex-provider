from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lib.common.common_store import (
    atomic_write_bytes,
    ensure_private_dir,
)
from lib.common.constants import SECRET_FILE_MODE
from lib.common.errors import SwitchError
from lib.xpx.store import ensure_xpx_dirs, get_xpx_home, xpx_lock
from lib.xpx.store.provider_store import validate_provider_name


@dataclass
class AccountSpec:
    """OAuth session / token account credentials."""

    target: str  # Target client: "agy", "codex", "cursor"
    name: str  # Account alias: "work", "personal"
    account_type: str  # "google-oauth", "chatgpt-session", "cursor-auth"
    token_data: dict[str, Any]  # access_token, refresh_token, etc.
    metadata: dict[str, Any] = field(default_factory=dict)  # email, project_id, etc.

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "name": self.name,
            "account_type": self.account_type,
            "token_data": dict(self.token_data),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AccountSpec:
        if not isinstance(data, dict):
            raise SwitchError("invalid account payload: expected dict")
        target = validate_provider_name(str(data.get("target", "")))
        name = validate_provider_name(str(data.get("name", "")))
        return cls(
            target=target,
            name=name,
            account_type=str(data.get("account_type", "unknown")),
            token_data=dict(data.get("token_data") or {}),
            metadata=dict(data.get("metadata") or {}),
        )


class AccountStore:
    """Manages account persistence under ~/.xpx/accounts/<target>/."""

    def __init__(self, home: Path | None = None) -> None:
        self._home = home or get_xpx_home()

    @property
    def accounts_dir(self) -> Path:
        p = self._home / "accounts"
        ensure_private_dir(p)
        return p

    def target_dir(self, target: str) -> Path:
        valid_target = validate_provider_name(target)
        p = self.accounts_dir / valid_target
        ensure_private_dir(p)
        return p

    def account_path(self, target: str, name: str) -> Path:
        valid_name = validate_provider_name(name)
        return self.target_dir(target) / f"{valid_name}.json"

    def exists(self, target: str, name: str) -> bool:
        return self.account_path(target, name).is_file()

    def get(self, target: str, name: str) -> AccountSpec | None:
        path = self.account_path(target, name)
        if not path.is_file():
            return None
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
            return AccountSpec.from_dict(data)
        except (OSError, json.JSONDecodeError, SwitchError) as exc:
            raise SwitchError(
                f"failed to load account '{name}' for target '{target}': {exc}"
            ) from exc

    def require(self, target: str, name: str) -> AccountSpec:
        spec = self.get(target, name)
        if spec is None:
            available = [a.name for a in self.list_by_target(target)]
            known = f", available: {', '.join(available)}" if available else ""
            raise SwitchError(f"unknown account '{name}' for target '{target}'{known}")
        return spec

    def list_by_target(self, target: str) -> list[AccountSpec]:
        target_path = self.target_dir(target)
        accounts: list[AccountSpec] = []
        for file in sorted(target_path.glob("*.json")):
            try:
                acc = self.get(target, file.stem)
                if acc is not None:
                    accounts.append(acc)
            except SwitchError:
                continue
        accounts.sort(key=lambda a: a.name)
        return accounts

    def list_all(self) -> list[AccountSpec]:
        ensure_xpx_dirs()
        accounts: list[AccountSpec] = []
        for target_dir in sorted(self.accounts_dir.iterdir()):
            if target_dir.is_dir():
                accounts.extend(self.list_by_target(target_dir.name))
        accounts.sort(key=lambda a: (a.target, a.name))
        return accounts

    def save(self, spec: AccountSpec) -> None:
        validate_provider_name(spec.target)
        validate_provider_name(spec.name)
        path = self.account_path(spec.target, spec.name)
        payload = (json.dumps(spec.to_dict(), indent=2) + "\n").encode("utf-8")
        with xpx_lock():
            atomic_write_bytes(
                path,
                payload,
                secret=True,
                mode=SECRET_FILE_MODE,
            )

    def delete(self, target: str, name: str) -> bool:
        path = self.account_path(target, name)
        with xpx_lock():
            if path.is_file():
                path.unlink()
                return True
        return False
