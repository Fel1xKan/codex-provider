"""Shared types and tables for legacy client discovery."""

from __future__ import annotations

from dataclasses import dataclass

from lib.xpx.store.account_store import AccountSpec
from lib.xpx.store.provider_store import ProviderSpec

StateMap = dict[str, tuple[str, str, str | None]]

WELL_KNOWN_BASE_URLS = {
    "deepseek": "https://api.deepseek.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "302ai": "https://api.302.ai/v1",
}


@dataclass
class DiscoveredItem:
    source_label: str  # e.g. "Codex (cpx)"
    item_type: str  # "provider" or "account"
    name: str
    summary: str
    payload: ProviderSpec | AccountSpec


def has_item(items: list[DiscoveredItem], name: str) -> bool:
    """True when an item of any type already carries this name."""
    return any(it.name == name for it in items)


def provider_item(
    items: list[DiscoveredItem], source_label: str, name: str, spec: ProviderSpec
) -> None:
    """Append a provider discovery with the standard ``url=/key=`` summary."""
    has_key = "yes" if spec.api_key else "no"
    items.append(
        DiscoveredItem(
            source_label=source_label,
            item_type="provider",
            name=name,
            summary=f"url={spec.base_url}, key={has_key}",
            payload=spec,
        )
    )
