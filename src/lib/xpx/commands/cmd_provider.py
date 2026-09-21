from __future__ import annotations

import getpass
import json
import sys
from typing import Any

from lib.common.errors import SwitchError
from lib.xpx.adapters.registry import get_adapter
from lib.xpx.store.provider_store import (
    ProviderSpec,
    ProviderStore,
    validate_provider_name,
)
from lib.xpx.store.state_store import StateStore


def mask_key(key: str) -> str:
    if not key:
        return "(none)"
    if len(key) <= 8:
        return "****"
    return f"{key[:4]}...{key[-4:]} ({len(key)} chars)"


def run_add(args: Any) -> int:
    name = validate_provider_name(args.name)
    base_url = args.base_url
    if not base_url:
        if sys.stdin.isatty():
            base_url = input(f"Enter base URL for provider '{name}': ").strip()
        else:
            raise SwitchError("base_url is required")
    if not base_url:
        raise SwitchError("base_url cannot be empty")

    api_key = args.key
    if args.key_stdin:
        line = sys.stdin.readline()
        api_key = line.rstrip("\r\n")
    elif not api_key:
        if sys.stdin.isatty():
            api_key = getpass.getpass("Enter API Key: ")
        else:
            raise SwitchError("API key is required (pass --key or --key-stdin)")

    protocol = getattr(args, "protocol", "openai") or "openai"
    protocol = protocol.lower()
    if protocol not in ("openai", "anthropic"):
        raise SwitchError(
            f"unsupported protocol '{protocol}'; choose 'openai' or 'anthropic'"
        )

    store = ProviderStore()
    if store.exists(name):
        raise SwitchError(
            f"provider '{name}' already exists. "
            "Use 'config set' or 'auth set' to modify."
        )

    spec = ProviderSpec(
        name=name,
        base_url=base_url,
        api_key=api_key or "",
        protocol=protocol,
        default_model=getattr(args, "default_model", None),
    )
    store.save(spec)
    print(f"✔ Added provider '{name}' ({spec.protocol}, {spec.base_url})")
    return 0


def run_list(args: Any) -> int:
    store = ProviderStore()
    providers = store.list_all()
    state = StateStore().load()

    # Calculate active targets per provider
    active_map: dict[str, list[str]] = {}
    for target_name, tstate in state.targets.items():
        if tstate.active_type == "provider" and tstate.active_name:
            active_map.setdefault(tstate.active_name, []).append(target_name)

    if getattr(args, "json", False):
        data = []
        for p in providers:
            item = p.to_dict()
            item["active_in_targets"] = sorted(active_map.get(p.name, []))
            data.append(item)
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0

    if not providers:
        print("No providers configured. Run 'xpx add <name> <base_url>' to add one.")
        return 0

    header = (
        f"{'PROVIDER':<15} {'PROTOCOL':<10} "
        f"{'DEFAULT MODEL':<20} {'ACTIVE IN TARGETS':<20}"
    )
    print(header)
    print("-" * len(header))
    for p in providers:
        active_str = ", ".join(sorted(active_map.get(p.name, []))) or "-"
        def_model = p.default_model or "-"
        print(f"{p.name:<15} {p.protocol:<10} {def_model:<20} {active_str:<20}")
    return 0


def run_show(args: Any) -> int:
    store = ProviderStore()
    spec = store.require(args.name)
    state = StateStore().load()

    active_targets = [
        target
        for target, ts in state.targets.items()
        if ts.active_type == "provider" and ts.active_name == spec.name
    ]

    print(f"Provider:      {spec.name}")
    print(f"Protocol:      {spec.protocol}")
    print(f"Base URL:      {spec.base_url}")
    print(f"API Key:       {mask_key(spec.api_key)}")
    print(f"Default Model: {spec.default_model or '(none)'}")
    print(f"Active in:     {', '.join(sorted(active_targets)) or '(none)'}")

    if spec.headers:
        print("Global Headers:")
        for k, v in sorted(spec.headers.items()):
            print(f"  {k}: {v}")

    if spec.targets:
        print("Target Overrides:")
        for target, override in sorted(spec.targets.items()):
            details: list[str] = []
            if override.fast is not None:
                details.append(f"fast={override.fast}")
            if override.wire_api:
                details.append(f"wire_api={override.wire_api}")
            if override.web_search is not None:
                details.append(f"web_search={override.web_search}")
            if override.headers:
                details.append(f"headers={list(override.headers.keys())}")
            if override.options:
                details.append(f"options={list(override.options.keys())}")
            summary = ", ".join(details) if details else "(none)"
            print(f"  {target}: {summary}")
    return 0


def run_delete(args: Any) -> int:
    name = args.name
    store = ProviderStore()
    if not store.exists(name):
        raise SwitchError(f"provider '{name}' not found")

    is_dry_run = getattr(args, "dry_run", False)
    is_full = getattr(args, "full", False)

    state_store = StateStore()
    state = state_store.load()
    active_targets = [
        target
        for target, ts in state.targets.items()
        if ts.active_type == "provider" and ts.active_name == name
    ]

    if is_dry_run:
        print(f"would delete provider '{name}'")
        if is_full and active_targets:
            print(f"would clear active state from targets: {', '.join(active_targets)}")
        return 0

    if is_full and active_targets:
        for target in active_targets:
            try:
                adp = get_adapter(target)
                adp.clear()
                state_store.remove_target_state(target)
            except Exception as exc:
                print(
                    f"warning: failed to clear target '{target}': {exc}",
                    file=sys.stderr,
                )

    store.delete(name)
    print(f"✔ Deleted provider '{name}'")
    return 0


def run_rename(args: Any) -> int:
    old_name = args.old
    new_name = args.new
    store = ProviderStore()
    store.rename(old_name, new_name)

    # Update StateStore if active
    state_store = StateStore()
    state = state_store.load()
    updated = False
    for ts in state.targets.values():
        if ts.active_type == "provider" and ts.active_name == old_name:
            ts.active_name = new_name
            updated = True
    if updated:
        state_store.save(state)

    print(f"✔ Renamed provider '{old_name}' to '{new_name}'")
    return 0
