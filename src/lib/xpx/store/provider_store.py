from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lib.common.common_store import (
    atomic_write_bytes,
    ensure_private_dir,
)
from lib.common.constants import SECRET_FILE_MODE
from lib.common.errors import SwitchError
from lib.common.network import normalize_base_url
from lib.xpx.store import ensure_xpx_dirs, get_xpx_home, xpx_lock

NAME_REGEX = re.compile(r"^[a-zA-Z0-9_-]+$")


def validate_provider_name(name: str) -> str:
    if not name or not NAME_REGEX.fullmatch(name):
        raise SwitchError(f"invalid provider name '{name}': must match [a-zA-Z0-9_-]+")
    return name


@dataclass
class TargetOverrides:
    """Target-specific overrides for a provider."""

    headers: dict[str, str] = field(default_factory=dict)
    fast: bool | None = None  # Codex: service_tier = "priority"
    wire_api: str | None = None  # Codex: "chat" | "responses"
    web_search: bool | None = None  # Codex: web_search = "live"
    options: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "headers": dict(self.headers),
            "fast": self.fast,
            "wire_api": self.wire_api,
            "web_search": self.web_search,
            "options": dict(self.options),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TargetOverrides:
        if not isinstance(data, dict):
            return cls()
        return cls(
            headers=dict(data.get("headers") or {}),
            fast=data.get("fast"),
            wire_api=data.get("wire_api"),
            web_search=data.get("web_search"),
            options=dict(data.get("options") or {}),
        )


@dataclass
class ProviderSpec:
    """Universal core provider specification."""

    name: str
    base_url: str
    api_key: str
    protocol: str = "openai"
    default_model: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    targets: dict[str, TargetOverrides] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "protocol": self.protocol,
            "base_url": self.base_url,
            "api_key": self.api_key,
            "default_model": self.default_model,
            "headers": dict(self.headers),
            "targets": {k: v.to_dict() for k, v in self.targets.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProviderSpec:
        if not isinstance(data, dict):
            raise SwitchError("invalid provider payload: expected dict")
        name = validate_provider_name(str(data.get("name", "")))
        base_url = str(data.get("base_url", "")).strip()
        if not base_url:
            raise SwitchError(f"base_url is required for provider '{name}'")
        raw_targets = data.get("targets") or {}
        targets = {
            k: TargetOverrides.from_dict(v)
            for k, v in raw_targets.items()
            if isinstance(v, dict)
        }
        return cls(
            name=name,
            base_url=base_url,
            api_key=str(data.get("api_key", "")),
            protocol=str(data.get("protocol", "openai")).lower(),
            default_model=data.get("default_model") or None,
            headers=dict(data.get("headers") or {}),
            targets=targets,
        )


class ProviderStore:
    """Manages provider asset persistence under ~/.xpx/providers/."""

    def __init__(self, home: Path | None = None) -> None:
        self._home = home or get_xpx_home()

    @property
    def providers_dir(self) -> Path:
        p = self._home / "providers"
        ensure_private_dir(p)
        return p

    def provider_path(self, name: str) -> Path:
        valid_name = validate_provider_name(name)
        return self.providers_dir / f"{valid_name}.json"

    def exists(self, name: str) -> bool:
        return self.provider_path(name).is_file()

    def get(self, name: str) -> ProviderSpec | None:
        path = self.provider_path(name)
        if not path.is_file():
            return None
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
            return ProviderSpec.from_dict(data)
        except (OSError, json.JSONDecodeError, SwitchError) as exc:
            raise SwitchError(f"failed to load provider '{name}': {exc}") from exc

    def require(self, name: str) -> ProviderSpec:
        spec = self.get(name)
        if spec is None:
            available = [p.name for p in self.list_all()]
            known = f", available: {', '.join(available)}" if available else ""
            raise SwitchError(f"unknown provider '{name}'{known}")
        return spec

    def list_all(self) -> list[ProviderSpec]:
        ensure_xpx_dirs()
        providers: list[ProviderSpec] = []
        for file in sorted(self.providers_dir.glob("*.json")):
            name = file.stem
            try:
                spec = self.get(name)
                if spec is not None:
                    providers.append(spec)
            except SwitchError:
                continue
        providers.sort(key=lambda s: s.name)
        return providers

    def save(self, spec: ProviderSpec) -> None:
        validate_provider_name(spec.name)
        if spec.base_url:
            spec.base_url = normalize_base_url(spec.base_url)
        path = self.provider_path(spec.name)
        payload = (json.dumps(spec.to_dict(), indent=2) + "\n").encode("utf-8")
        with xpx_lock():
            atomic_write_bytes(
                path,
                payload,
                secret=True,
                mode=SECRET_FILE_MODE,
            )

    def delete(self, name: str) -> bool:
        path = self.provider_path(name)
        with xpx_lock():
            if path.is_file():
                path.unlink()
                return True
        return False

    def rename(self, old_name: str, new_name: str) -> None:
        validate_provider_name(old_name)
        validate_provider_name(new_name)
        with xpx_lock():
            spec = self.require(old_name)
            if self.exists(new_name) and old_name != new_name:
                raise SwitchError(f"provider '{new_name}' already exists")
            spec.name = new_name
            self.save(spec)
            if old_name != new_name:
                self.delete(old_name)
