"""Collect providers from the legacy OpenCode config and the native auth store."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import json5

from lib.xpx.adapters.opencode import get_opencode_config_dir, get_opencode_data_dir
from lib.xpx.store.provider_store import ProviderSpec

from .common import (
    WELL_KNOWN_BASE_URLS,
    DiscoveredItem,
    StateMap,
    has_item,
    provider_item,
)

_LABEL = "OpenCode (opx)"
_CONFIG_NAMES = (
    "opencode.json",
    "opencode.jsonc",
    "opencode.json5",
    "opencode.config.json",
    "opencode.config.jsonc",
)


def collect(items: list[DiscoveredItem], states: StateMap, home: Path) -> None:
    """OpenCode (opx & native) configurations."""
    auth_keys = _auth_keys(get_opencode_data_dir() / "auth.json")
    cfg_file = _config_file(get_opencode_config_dir())
    if cfg_file is not None:
        _collect_config(items, states, cfg_file, auth_keys)
    _collect_well_known(items, auth_keys)


def _auth_keys(auth_path: Path) -> dict[str, str]:
    keys: dict[str, str] = {}
    if not auth_path.is_file():
        return keys
    try:
        data = json.loads(auth_path.read_text(encoding="utf-8"))
    except Exception:
        return keys
    if not isinstance(data, dict):
        return keys
    for name, entry in data.items():
        if isinstance(entry, dict):
            value = entry.get("key") or entry.get("apiKey")
            if isinstance(value, str) and value:
                keys[name] = value
    return keys


def _config_file(cfg_dir: Path) -> Path | None:
    for name in _CONFIG_NAMES:
        candidate = cfg_dir / name
        if candidate.is_file():
            return candidate
    return None


def _collect_config(
    items: list[DiscoveredItem],
    states: StateMap,
    cfg_file: Path,
    auth_keys: dict[str, str],
) -> None:
    try:
        data = json5.loads(cfg_file.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(data, dict):
        return
    _record_state(states, data)
    _collect_providers(items, data, auth_keys)


def _record_state(states: StateMap, data: dict[str, Any]) -> None:
    current_model = data.get("model")
    if isinstance(current_model, str) and "/" in current_model:
        provider_part, model_part = current_model.split("/", 1)
        states["opencode"] = ("provider", provider_part.strip(), model_part.strip())
    elif data.get("default_provider"):
        states["opencode"] = ("provider", str(data["default_provider"]).strip(), None)


def _collect_providers(
    items: list[DiscoveredItem], data: dict[str, Any], auth_keys: dict[str, str]
) -> None:
    providers = data.get("provider", {})
    if not isinstance(providers, dict):
        return
    for name, pcfg in providers.items():
        if not isinstance(pcfg, dict):
            continue
        raw_opts = pcfg.get("options")
        opts: dict[str, Any] = raw_opts if isinstance(raw_opts, dict) else {}
        base_url = opts.get("baseURL") or opts.get("base_url")
        if not base_url:
            continue
        spec = ProviderSpec(
            name=name,
            base_url=base_url,
            api_key=opts.get("apiKey") or auth_keys.get(name, ""),
            protocol="openai",
            default_model=_default_model(data, pcfg, name),
        )
        provider_item(items, _LABEL, name, spec)


def _default_model(data: dict[str, Any], pcfg: dict[str, Any], name: str) -> str | None:
    current_model = data.get("model")
    if isinstance(current_model, str) and "/" in current_model:
        provider_part, _, model_part = current_model.partition("/")
        return model_part if provider_part == name else None
    models = pcfg.get("models", {})
    if isinstance(models, dict) and models:
        return str(next(iter(models.keys())))
    return None


def _collect_well_known(items: list[DiscoveredItem], auth_keys: dict[str, str]) -> None:
    for name, key in auth_keys.items():
        if name in WELL_KNOWN_BASE_URLS and not has_item(items, name):
            spec = ProviderSpec(
                name=name,
                base_url=WELL_KNOWN_BASE_URLS[name],
                api_key=key,
                protocol="openai",
            )
            provider_item(items, _LABEL, name, spec)
