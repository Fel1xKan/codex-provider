"""Collect the provider described by the native Pi config."""

from __future__ import annotations

from pathlib import Path

import yaml

from lib.xpx.adapters.pi import get_pi_config_file
from lib.xpx.store.provider_store import ProviderSpec

from .common import DiscoveredItem, StateMap


def collect(items: list[DiscoveredItem], states: StateMap, home: Path) -> None:
    """Pi (native) configuration."""
    pi_cfg_path = get_pi_config_file()
    if pi_cfg_path.is_file():
        try:
            p_data = yaml.safe_load(pi_cfg_path.read_text(encoding="utf-8")) or {}
            pv = p_data.get("model_provider", {}) if isinstance(p_data, dict) else {}
            p_name = pv.get("name")
            p_base = pv.get("api_base")
            p_key = pv.get("api_key", "")
            p_model = pv.get("model")
            if p_name and p_base:
                spec = ProviderSpec(
                    name=str(p_name),
                    base_url=str(p_base),
                    api_key=str(p_key or ""),
                    protocol="openai",
                    default_model=str(p_model) if p_model else None,
                )
                if not any(it.name == str(p_name) for it in items):
                    items.append(
                        DiscoveredItem(
                            source_label="Pi (native)",
                            item_type="provider",
                            name=str(p_name),
                            summary=f"url={p_base}",
                            payload=spec,
                        )
                    )
                states["pi"] = (
                    "provider",
                    str(p_name),
                    str(p_model) if p_model else None,
                )
        except Exception:
            pass
