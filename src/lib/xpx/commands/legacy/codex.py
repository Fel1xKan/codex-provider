"""Collect providers from the legacy ~/.codex-provider tree and native Codex config."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import tomlkit

from lib.xpx.adapters.codex import get_codex_home
from lib.xpx.store.provider_store import ProviderSpec, TargetOverrides

from .common import DiscoveredItem, StateMap, has_item, provider_item

_LABEL = "Codex (cpx)"


def collect(items: list[DiscoveredItem], states: StateMap, home: Path) -> None:
    """Codex (cpx & native) configurations."""
    _collect_legacy(items, home / ".codex-provider")
    _collect_native(items, states, get_codex_home())


def _read_key(auth_path: Path, *names: str) -> str:
    if not auth_path.is_file():
        return ""
    try:
        data = json.loads(auth_path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    if not isinstance(data, dict):
        return ""
    for name in names:
        value = data.get(name)
        if value:
            return str(value)
    return ""


def _spec(name: str, cfg: dict[str, Any], api_key: str) -> ProviderSpec:
    return ProviderSpec(
        name=name,
        base_url=cfg["base_url"],
        api_key=api_key,
        protocol="openai",
        targets={
            "codex": TargetOverrides(
                wire_api=cfg.get("wire_api"),
                headers=dict(cfg.get("http_headers") or {}),
            )
        },
    )


def _collect_legacy(items: list[DiscoveredItem], codex_dir: Path) -> None:
    cfg_path = codex_dir / "config.toml"
    if not cfg_path.is_file():
        return
    try:
        doc = tomlkit.parse(cfg_path.read_text(encoding="utf-8"))
        providers = doc.get("model_providers", {})
        if not isinstance(providers, dict):
            return
        for name, cfg in providers.items():
            if isinstance(cfg, dict) and "base_url" in cfg:
                key = _read_key(codex_dir / "auth" / f"{name}.json", "OPENAI_API_KEY")
                provider_item(items, _LABEL, name, _spec(name, cfg, key))
    except Exception:
        return


def _collect_native(
    items: list[DiscoveredItem], states: StateMap, codex_home: Path
) -> None:
    cfg_path = codex_home / "config.toml"
    if not cfg_path.is_file():
        return
    auth_path = codex_home / "auth.json"
    try:
        doc = tomlkit.parse(cfg_path.read_text(encoding="utf-8"))
        _record_state(states, doc)
        providers = doc.get("model_providers", {})
        if not isinstance(providers, dict):
            return
        for name, cfg in providers.items():
            if (
                not isinstance(cfg, dict)
                or "base_url" not in cfg
                or name == "openai"
                or has_item(items, name)
            ):
                continue
            key = _read_key(auth_path, "OPENAI_API_KEY", f"{name}_api_key")
            provider_item(items, _LABEL, name, _spec(name, cfg, key))
    except Exception:
        return


def _record_state(states: StateMap, doc: Any) -> None:
    active_provider = str(doc.get("model_provider") or "")
    active_model = doc.get("model")
    if not active_provider:
        return
    kind = "official" if active_provider == "openai" else "provider"
    states["codex"] = (
        kind,
        active_provider,
        str(active_model) if active_model else None,
    )
