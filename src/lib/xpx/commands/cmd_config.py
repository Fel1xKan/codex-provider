from __future__ import annotations

import sys
from typing import Any

from lib.common.errors import SwitchError
from lib.xpx.adapters.base import MergedProviderSpec
from lib.xpx.adapters.registry import get_adapter
from lib.xpx.store.provider_store import ProviderStore, TargetOverrides
from lib.xpx.store.state_store import StateStore


def run_config_show(args: Any) -> int:
    store = ProviderStore()
    name = getattr(args, "name", None)
    target = getattr(args, "target", None)

    if not name:
        providers = store.list_all()
        if not providers:
            print("No providers configured.")
            return 0
        for p in providers:
            print(f"Provider: {p.name}")
            print(f"  Base URL:      {p.base_url}")
            print(f"  Default Model: {p.default_model or '(none)'}")
            if p.targets:
                print(f"  Configured Targets: {', '.join(sorted(p.targets.keys()))}")
        return 0

    spec = store.require(name)
    if not target:
        print(f"Provider:      {spec.name}")
        print(f"Base URL:      {spec.base_url}")
        print(f"Default Model: {spec.default_model or '(none)'}")
        if spec.headers:
            print("Global Headers:")
            for k, v in sorted(spec.headers.items()):
                print(f"  {k}: {v}")
        if spec.targets:
            print("Configured Targets:")
            for t_name, overrides in sorted(spec.targets.items()):
                print(f"  [{t_name}]")
                if overrides.fast is not None:
                    print(f"    fast:       {overrides.fast}")
                if overrides.wire_api:
                    print(f"    wire_api:   {overrides.wire_api}")
                if overrides.web_search is not None:
                    print(f"    web_search: {overrides.web_search}")
                if overrides.headers:
                    print(f"    headers:    {overrides.headers}")
                if overrides.options:
                    print(f"    options:    {overrides.options}")
        return 0

    overrides = spec.targets.get(target)
    print(f"Effective Configuration for Provider '{spec.name}' in Target '{target}':")
    print(f"  Base URL:      {spec.base_url}")
    print(f"  Protocol:      {spec.protocol}")
    print(f"  Default Model: {spec.default_model or '(none)'}")
    if overrides:
        if overrides.fast is not None:
            print(f"  Fast Mode:     {overrides.fast}")
        if overrides.wire_api:
            print(f"  Wire API:      {overrides.wire_api}")
        if overrides.web_search is not None:
            print(f"  Web Search:    {overrides.web_search}")
        merged_headers = dict(spec.headers)
        merged_headers.update(overrides.headers)
        if merged_headers:
            print(f"  Headers:       {merged_headers}")
        if overrides.options:
            print(f"  Options:       {overrides.options}")
    return 0


def run_config_set(args: Any) -> int:
    name = args.name
    target = getattr(args, "target", None)
    store = ProviderStore()
    spec = store.require(name)

    state_store = StateStore()
    state = state_store.load()

    if not target:
        changed_base_url = False
        base_url = getattr(args, "base_url", None)
        if base_url:
            spec.base_url = base_url
            changed_base_url = True

        default_model = getattr(args, "default_model", None)
        if default_model:
            spec.default_model = default_model

        store.save(spec)

        reapplied: list[str] = []
        if changed_base_url:
            for t_name, ts in sorted(state.targets.items()):
                if ts.active_type == "provider" and ts.active_name == name:
                    try:
                        adp = get_adapter(t_name)
                        overrides = spec.targets.get(t_name)
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
                        reapplied.append(t_name)
                    except Exception as exc:
                        print(
                            f"warning: failed to re-apply to target '{t_name}': {exc}",
                            file=sys.stderr,
                        )

        msg = f"✔ Updated config for '{name}'."
        if reapplied:
            msg += f" Re-applied to active targets: {', '.join(reapplied)}."
        print(msg)
        return 0

    # Target-specific configuration
    get_adapter(target)  # validate target client name
    if target not in spec.targets:
        spec.targets[target] = TargetOverrides()
    overrides = spec.targets[target]

    if getattr(args, "fast", None) is not None:
        overrides.fast = bool(args.fast)

    wire_api = getattr(args, "wire_api", None)
    if wire_api is not None:
        if wire_api not in ("chat", "responses"):
            raise SwitchError(
                f"invalid wire-api '{wire_api}'; must be 'chat' or 'responses'"
            )
        overrides.wire_api = wire_api

    web_search = getattr(args, "web_search", None)
    if web_search is not None:
        if isinstance(web_search, str):
            overrides.web_search = web_search.lower() in ("true", "1", "yes")
        else:
            overrides.web_search = bool(web_search)

    header_items = getattr(args, "header", None) or []
    for item in header_items:
        if "=" in item:
            k, v = item.split("=", 1)
            k = k.strip()
            if not v.strip():
                overrides.headers.pop(k, None)
            else:
                overrides.headers[k] = v.strip()
        else:
            overrides.headers.pop(item.strip(), None)

    option_items = getattr(args, "option", None) or []
    for item in option_items:
        if "=" in item:
            k, v = item.split("=", 1)
            k = k.strip()
            if not v.strip():
                overrides.options.pop(k, None)
            else:
                overrides.options[k] = v.strip()
        else:
            overrides.options.pop(item.strip(), None)

    store.save(spec)

    # Linkage: if active on this target, re-apply
    ts = state.targets.get(target)
    if ts and ts.active_type == "provider" and ts.active_name == name:
        try:
            adp = get_adapter(target)
            merged = MergedProviderSpec(
                name=spec.name,
                base_url=spec.base_url,
                api_key=spec.api_key,
                protocol=spec.protocol,
                model=ts.active_model or spec.default_model,
                headers=dict(spec.headers),
                fast=overrides.fast,
                wire_api=overrides.wire_api,
                web_search=overrides.web_search,
                options=dict(overrides.options),
            )
            merged.headers.update(overrides.headers)
            adp.apply(merged)
            print(
                f"✔ Updated '{target}' overrides for '{name}'. "
                f"Re-applied to active target '{target}'."
            )
            return 0
        except Exception as exc:
            print(
                f"warning: failed to re-apply to target '{target}': {exc}",
                file=sys.stderr,
            )

    print(f"✔ Updated '{target}' overrides for '{name}'.")
    return 0
