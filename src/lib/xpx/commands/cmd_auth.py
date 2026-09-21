from __future__ import annotations

import getpass
import sys
from typing import Any

from lib.common.errors import SwitchError
from lib.xpx.adapters.base import MergedProviderSpec
from lib.xpx.adapters.registry import get_adapter
from lib.xpx.commands.cmd_provider import mask_key
from lib.xpx.store.provider_store import ProviderStore
from lib.xpx.store.state_store import StateStore


def run_auth_show(args: Any) -> int:
    store = ProviderStore()
    name = getattr(args, "name", None)
    if name:
        spec = store.require(name)
        status = "configured" if spec.api_key else "missing"
        print(f"Provider: {spec.name}")
        print(f"API Key:  {mask_key(spec.api_key)}")
        print(f"Status:   {status}")
        return 0

    providers = store.list_all()
    if not providers:
        print("No providers configured.")
        return 0

    header = f"{'PROVIDER':<16} {'KEY SUMMARY':<30} {'STATUS':<12}"
    print(header)
    print("-" * len(header))
    for p in providers:
        status = "configured" if p.api_key else "missing"
        print(f"{p.name:<16} {mask_key(p.api_key):<30} {status:<12}")
    return 0


def run_auth_set(args: Any) -> int:
    name = args.name
    store = ProviderStore()
    spec = store.require(name)

    api_key = getattr(args, "key", None)
    if getattr(args, "key_stdin", False):
        line = sys.stdin.readline()
        api_key = line.rstrip("\r\n")
    elif not api_key:
        if sys.stdin.isatty():
            api_key = getpass.getpass(f"Enter new API Key for '{name}': ")
        else:
            raise SwitchError("API key is required (pass --key or --key-stdin)")

    if not api_key:
        raise SwitchError("API key cannot be empty")

    spec.api_key = api_key
    store.save(spec)

    # Linkage: detect active targets and re-apply
    state = StateStore().load()
    reapplied_targets: list[str] = []
    for target_name, ts in sorted(state.targets.items()):
        if ts.active_type == "provider" and ts.active_name == name:
            try:
                adp = get_adapter(target_name)
                # Build merged spec for this target
                overrides = spec.targets.get(target_name)
                merged = MergedProviderSpec(
                    name=spec.name,
                    base_url=spec.base_url,
                    api_key=spec.api_key,
                    protocol=spec.protocol,
                    model=ts.active_model or spec.default_model,
                    headers=dict(spec.headers),
                    fast=overrides.fast if overrides else None,
                    wire_api=overrides.wire_api if overrides else None,
                    web_search=overrides.web_search if overrides else None,
                    options=dict(overrides.options) if overrides else {},
                )
                if overrides and overrides.headers:
                    merged.headers.update(overrides.headers)
                adp.apply(merged)
                reapplied_targets.append(target_name)
            except Exception as exc:
                print(
                    f"warning: failed to re-apply to target '{target_name}': {exc}",
                    file=sys.stderr,
                )

    if reapplied_targets:
        targets_str = ", ".join(reapplied_targets)
        print(
            f"✔ Updated API Key for '{name}'. "
            f"Re-applied to active targets: {targets_str}."
        )
    else:
        print(f"✔ Updated API Key for '{name}'.")

    return 0
