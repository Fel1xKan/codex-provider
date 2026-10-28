"""Shared helpers for keeping active targets in sync with a provider change.

Editing a provider's fields (base URL, API key, target overrides) must be
reflected in any client that currently uses it. `auth set`, `config set`, and
`apply` each used to carry their own copy of that re-apply loop, which is how
one of them could drift and silently stop re-applying.
"""

from __future__ import annotations

import sys

from lib.xpx.adapters.base import MergedProviderSpec
from lib.xpx.adapters.registry import get_adapter
from lib.xpx.store.provider_store import ProviderSpec
from lib.xpx.store.state_store import StateStore


def active_targets_for(provider_name: str) -> list[str]:
    """Return target names whose active provider is `provider_name`."""
    state = StateStore().load()
    active: list[str] = []
    for target_name, ts in sorted(state.targets.items()):
        if ts.active_type == "provider" and ts.active_name == provider_name:
            active.append(target_name)
    return active


def build_spec_for_target(
    spec: ProviderSpec,
    target_name: str,
    active_model: str | None = None,
) -> MergedProviderSpec:
    """Merge a provider's universal config with one target's overrides."""
    overrides = spec.targets.get(target_name)
    effort = (
        str(overrides.options["effort"])
        if overrides and overrides.options and "effort" in overrides.options
        else None
    )
    merged = MergedProviderSpec(
        name=spec.name,
        base_url=spec.base_url,
        api_key=spec.api_key,
        protocol=spec.protocol,
        model=active_model or spec.default_model,
        effort=effort,
        headers=dict(spec.headers),
        fast=overrides.fast if overrides else None,
        wire_api=overrides.wire_api if overrides else None,
        web_search=overrides.web_search if overrides else None,
        options=dict(overrides.options) if overrides else {},
    )
    if overrides and overrides.headers:
        merged.headers.update(overrides.headers)
    return merged


def reapply_active_targets(spec: ProviderSpec) -> list[str]:
    """Re-apply `spec` to every target currently using it.

    Returns the target names that were successfully refreshed. Failures are
    reported but never abort the update: the provider was already saved, and a
    client that cannot be refreshed should not block the others.
    """
    state = StateStore().load()
    reapplied: list[str] = []
    for target_name in active_targets_for(spec.name):
        try:
            adp = get_adapter(target_name)
            ts = state.targets.get(target_name)
            active_model = ts.active_model if ts else None
            adp.apply(build_spec_for_target(spec, target_name, active_model))
            reapplied.append(target_name)
        except Exception as exc:  # noqa: BLE001 - reported, never fatal
            print(
                f"warning: failed to re-apply to target '{target_name}': {exc}",
                file=sys.stderr,
            )
    return reapplied


def report_refresh(action: str, name: str, reapplied: list[str]) -> None:
    """Print a consistent summary line for a provider mutation."""
    msg = f"\u2714 {action}"
    if reapplied:
        msg += f". Re-applied '{name}' to active targets: {', '.join(reapplied)}"
    print(msg + ".")


def mask_secret(value: str) -> str:
    """Render an API key in a form safe to print."""
    if not value:
        return "(not set)"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def parse_kv_pairs(items: list[str]) -> dict[str, str | None]:
    """Parse repeated `key=value` flags into a mapping.

    A bare `key` (no `=`) maps to None, which callers interpret as "remove".
    """
    result: dict[str, str | None] = {}
    for item in items:
        if "=" in item:
            key, value = item.split("=", 1)
            result[key.strip()] = value.strip() or None
        else:
            result[item.strip()] = None
    return result
