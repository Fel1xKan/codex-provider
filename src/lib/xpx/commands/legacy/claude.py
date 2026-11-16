"""Collect the provider described by the native Claude settings file."""

from __future__ import annotations

import json
from pathlib import Path

from lib.xpx.adapters.claude import get_claude_settings_path
from lib.xpx.store.provider_store import ProviderSpec

from .common import DiscoveredItem, StateMap, has_item, provider_item

_LABEL = "Claude (clpx)"
_DEFAULT_BASE_URL = "https://api.anthropic.com"


def collect(items: list[DiscoveredItem], states: StateMap, home: Path) -> None:
    """Claude (clpx & native) configurations."""
    _collect_legacy(items, home / ".claude-provider")
    _collect_native(items, states, get_claude_settings_path())


def _legacy_key(auth_path: Path) -> str:
    if not auth_path.is_file():
        return ""
    try:
        data = json.loads(auth_path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    if not isinstance(data, dict):
        return ""
    return str(
        data.get("ANTHROPIC_AUTH_TOKEN") or data.get("ANTHROPIC_API_KEY", "") or ""
    )


def _collect_legacy(items: list[DiscoveredItem], claude_dir: Path) -> None:
    cfg_path = claude_dir / "config.json"
    if not cfg_path.is_file():
        return
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        return
    providers = data.get("providers", {}) if isinstance(data, dict) else {}
    if not isinstance(providers, dict):
        return
    for name, cfg in providers.items():
        if not isinstance(cfg, dict):
            continue
        spec = ProviderSpec(
            name=name,
            base_url=cfg.get("base_url", _DEFAULT_BASE_URL),
            api_key=_legacy_key(claude_dir / "auth" / f"{name}.json"),
            protocol="anthropic",
            default_model=cfg.get("model"),
        )
        provider_item(items, _LABEL, name, spec)


def _collect_native(
    items: list[DiscoveredItem], states: StateMap, settings_path: Path
) -> None:
    if not settings_path.is_file():
        return
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except Exception:
        return
    env = data.get("env", {}) if isinstance(data, dict) else {}
    base_url = env.get("ANTHROPIC_BASE_URL")
    model = env.get("ANTHROPIC_MODEL")
    if not base_url:
        if "claude" not in states:
            states["claude"] = ("official", "anthropic", model)
        return
    token = env.get("ANTHROPIC_AUTH_TOKEN") or env.get("ANTHROPIC_API_KEY", "")
    name = _match_provider(items, str(base_url))
    if not has_item(items, name):
        spec = ProviderSpec(
            name=name,
            base_url=base_url,
            api_key=token,
            protocol="anthropic",
            default_model=model,
        )
        items.append(
            DiscoveredItem(
                source_label=_LABEL,
                item_type="provider",
                name=name,
                summary=f"url={base_url}",
                payload=spec,
            )
        )
    states["claude"] = ("provider", name, model)


def _match_provider(items: list[DiscoveredItem], base_url: str) -> str:
    right = base_url.rstrip("/")
    for it in items:
        if it.item_type != "provider" or not isinstance(it.payload, ProviderSpec):
            continue
        left = it.payload.base_url.rstrip("/")
        if left == right or left.startswith(right) or right.startswith(left):
            return it.name
    return "claude-custom"
