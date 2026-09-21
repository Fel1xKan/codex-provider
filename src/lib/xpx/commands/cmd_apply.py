from __future__ import annotations

from typing import Any

from lib.common.errors import SwitchError
from lib.xpx.adapters.base import MergedProviderSpec
from lib.xpx.adapters.registry import detect_installed_adapters, get_adapter
from lib.xpx.store.account_store import AccountStore
from lib.xpx.store.provider_store import (
    ProviderSpec,
    ProviderStore,
    TargetOverrides,
)
from lib.xpx.store.state_store import StateStore


def parse_provider_and_model(
    provider_spec: str | None,
    explicit_model: str | None,
    target: str,
    state_store: StateStore,
    pv_store: ProviderStore,
) -> tuple[ProviderSpec, str | None]:
    if not provider_spec:
        # Check if target already has an active provider
        ts = state_store.get_target_state(target)
        if ts and ts.active_type == "provider" and ts.active_name:
            pv = pv_store.require(ts.active_name)
            model = explicit_model or ts.active_model or pv.default_model
            return pv, model
        raise SwitchError(f"provider specification required for target '{target}'")

    clean_spec = provider_spec.strip()
    if clean_spec.startswith(":"):
        # Model-only switch: :model-name
        model_name = clean_spec[1:].strip()
        ts = state_store.get_target_state(target)
        if not ts or ts.active_type != "provider" or not ts.active_name:
            raise SwitchError(
                f"cannot switch model only: target '{target}' has no active provider"
            )
        pv = pv_store.require(ts.active_name)
        return pv, explicit_model or model_name

    if "/" in clean_spec:
        pv_name, model_name = clean_spec.split("/", 1)
        pv = pv_store.require(pv_name.strip())
        return pv, explicit_model or model_name.strip()

    # Just provider name
    pv = pv_store.require(clean_spec)
    return pv, explicit_model or pv.default_model


def build_merged_spec(
    pv: ProviderSpec,
    target: str,
    model: str | None,
    args: Any,
) -> tuple[MergedProviderSpec, bool]:
    """Merge universal base + target overrides + CLI ad-hoc.

    Returns (MergedProviderSpec, has_adhoc_overrides).
    """
    adp = get_adapter(target)
    fast_supported = getattr(adp, "supports_fast", False)
    wire_api_supported = getattr(adp, "supports_wire_api", False)
    web_search_supported = getattr(adp, "supports_web_search", False)

    overrides = pv.targets.get(target)
    fast = (overrides.fast if overrides else None) if fast_supported else None
    wire_api = (
        (overrides.wire_api if overrides else None) if wire_api_supported else None
    )
    web_search = (
        (overrides.web_search if overrides else None) if web_search_supported else None
    )
    options = dict(overrides.options) if (overrides and overrides.options) else {}

    headers = dict(pv.headers)
    if overrides and overrides.headers:
        headers.update(overrides.headers)

    has_adhoc = False

    # Layer 3: Ad-hoc CLI flags
    cli_fast = getattr(args, "fast", None)
    if cli_fast is not None and fast_supported:
        fast = bool(cli_fast)
        has_adhoc = True

    cli_wire_api = getattr(args, "wire_api", None)
    if cli_wire_api is not None and wire_api_supported:
        if cli_wire_api not in ("chat", "responses"):
            raise SwitchError(
                f"invalid wire-api '{cli_wire_api}'; must be 'chat' or 'responses'"
            )
        wire_api = cli_wire_api
        has_adhoc = True

    cli_web_search = getattr(args, "web_search", None)
    if cli_web_search is not None and web_search_supported:
        if isinstance(cli_web_search, str):
            web_search = cli_web_search.lower() in ("true", "1", "yes")
        else:
            web_search = bool(cli_web_search)
        has_adhoc = True

    cli_headers = getattr(args, "header", None) or []
    if cli_headers:
        has_adhoc = True
        for h in cli_headers:
            if "=" in h:
                k, v = h.split("=", 1)
                headers[k.strip()] = v.strip()
            else:
                headers.pop(h.strip(), None)

    spec = MergedProviderSpec(
        name=pv.name,
        base_url=pv.base_url,
        api_key=pv.api_key,
        protocol=pv.protocol,
        model=model,
        headers=headers,
        fast=fast,
        wire_api=wire_api,
        web_search=web_search,
        options=options,
    )
    return spec, has_adhoc


def run_apply(args: Any) -> int:
    target_arg = getattr(args, "target", None)
    provider_spec = getattr(args, "provider_spec", None)
    all_targets = getattr(args, "all", False)

    if all_targets:
        if target_arg and not provider_spec:
            provider_spec = target_arg
            target_arg = None
        elif target_arg and provider_spec:
            if not getattr(args, "model", None):
                provider_spec = f"{target_arg}/{provider_spec}"
            else:
                provider_spec = target_arg
            target_arg = None

        installed = detect_installed_adapters()
        if not installed:
            raise SwitchError("no supported target clients detected on this machine")
        target_names = sorted(installed.keys())
    elif target_arg:
        target_names = [t.strip().lower() for t in target_arg.split(",") if t.strip()]
    else:
        import sys

        if sys.stdin.isatty() and sys.stdout.isatty():
            from lib.xpx.interactive.wizards import run_interactive_apply

            return run_interactive_apply()
        raise SwitchError(
            "target client required "
            "(e.g. 'xpx apply codex ...' or 'xpx apply --all ...')"
        )

    # Validate target names
    for t in target_names:
        get_adapter(t)

    # 1. Reset / Clear mode
    if getattr(args, "clear", False) or getattr(args, "reset", False):
        state_store = StateStore()
        for t in target_names:
            adp = get_adapter(t)
            if getattr(args, "dry_run", False):
                print(f"would reset '{t}' to official/default state")
            else:
                adp.clear()
                state_store.set_target_state(t, "official", "default")
                print(f"✔ Reset '{t}' to official/default state.")
        return 0

    # 2. Account mode
    account_name = getattr(args, "account", None)
    if account_name:
        acc_store = AccountStore()
        state_store = StateStore()
        for t in target_names:
            adp = get_adapter(t)
            if not hasattr(adp, "apply_account"):
                if all_targets:
                    print(f"• Skipping '{t}' (does not support OAuth accounts)")
                    continue
                raise SwitchError(f"target '{t}' does not support OAuth account apply")
            if all_targets:
                account = acc_store.get(t, account_name)
                if not account:
                    print(f"• Skipping '{t}' (account '{account_name}' not found)")
                    continue
            else:
                account = acc_store.require(t, account_name)
            if getattr(args, "dry_run", False):
                print(f"would apply account '{account_name}' to '{t}'")
            else:
                adp.apply_account(account)
                state_store.set_target_state(t, "account", account_name)
                print(f"✔ Applied account '{account_name}' to {t}.")
        return 0

    # 3. Global Sync mode: 'xpx apply --all' without a provider spec
    if all_targets and not provider_spec:
        state_store = StateStore()
        pv_store = ProviderStore()
        acc_store = AccountStore()
        is_dry_run = getattr(args, "dry_run", False)

        current_state = state_store.load()
        has_any_active = any(
            ts.active_type not in (None, "none")
            for ts in current_state.targets.values()
        )
        if not has_any_active:
            from lib.xpx.commands.cmd_import_export import scan_and_migrate_all

            scan_and_migrate_all(dry_run=False, quiet=True)
            current_state = state_store.load()
            has_any_active = any(
                ts.active_type not in (None, "none")
                for ts in current_state.targets.values()
            )

        if not has_any_active:
            print("No active configurations found in xpx.\n")
            print("Getting Started:")
            print("  1. Add an API provider:")
            print("     xpx add <name> <base_url> --key <api_key>")
            print("     xpx apply --all <name>")
            print("\n  2. Or log in to an OAuth account:")
            print("     xpx account login agy <name>")
            print("\n  3. Or inspect client status:")
            print("     xpx status")
            return 0

        for t in target_names:
            ts = state_store.get_target_state(t)
            adp = get_adapter(t)
            if not ts or ts.active_type in (None, "none"):
                print(f"• Skipping '{t}' (no active configuration recorded)")
                continue

            if ts.active_type == "account":
                if not hasattr(adp, "apply_account"):
                    print(f"• Skipping '{t}' (does not support OAuth accounts)")
                    continue
                account = acc_store.get(t, ts.active_name or "")
                if not account:
                    print(
                        f"• Skipping '{t}' "
                        f"(account '{ts.active_name}' not found in store)"
                    )
                    continue
                if is_dry_run:
                    print(f"would apply account '{ts.active_name}' to '{t}'")
                else:
                    adp.apply_account(account)
                    print(f"✔ Applied account '{ts.active_name}' to {t}.")

            elif ts.active_type == "provider":
                if adp.supported_protocols == ["google-oauth"]:
                    print(
                        f"• Skipping '{t}' "
                        "(uses Google OAuth accounts, not API providers)"
                    )
                    continue
                pv = pv_store.get(ts.active_name or "")
                if not pv:
                    print(
                        f"• Skipping '{t}' "
                        f"(provider '{ts.active_name}' not found in store)"
                    )
                    continue
                model = (
                    getattr(args, "model", None) or ts.active_model or pv.default_model
                )
                merged_spec, has_adhoc = build_merged_spec(pv, t, model, args)
                if is_dry_run:
                    fast_info = " (fast)" if merged_spec.fast else ""
                    print(
                        f"would apply provider '{pv.name}' "
                        f"(model: {merged_spec.model or 'default'}) to '{t}'{fast_info}"
                    )
                else:
                    adp.apply(merged_spec)
                    model_str = f"/{merged_spec.model}" if merged_spec.model else ""
                    fast_str = " (fast mode enabled)" if merged_spec.fast else ""
                    applied_msg = (
                        f"✔ Applied provider '{pv.name}{model_str}' to {t}{fast_str}."
                    )
                    print(applied_msg)

            elif ts.active_type == "official":
                if is_dry_run:
                    print(f"would reset '{t}' to official/default state")
                else:
                    adp.clear()
                    print(f"✔ Applied official state to {t}.")

        return 0

    # 4. Single-target account re-apply check
    if not all_targets and len(target_names) == 1 and not provider_spec:
        single_t = target_names[0]
        adp = get_adapter(single_t)
        state_store = StateStore()
        ts = state_store.get_target_state(single_t)
        if ts and ts.active_type == "account" and ts.active_name:
            acc_store = AccountStore()
            account = acc_store.get(single_t, ts.active_name)
            if account and hasattr(adp, "apply_account"):
                if getattr(args, "dry_run", False):
                    print(f"would apply account '{ts.active_name}' to '{single_t}'")
                else:
                    adp.apply_account(account)
                    print(f"✔ Applied account '{ts.active_name}' to {single_t}.")
                return 0

    # 5. Provider Apply mode
    explicit_model = getattr(args, "model", None)
    is_dry_run = getattr(args, "dry_run", False)
    no_save = getattr(args, "no_save", False)

    state_store = StateStore()
    pv_store = ProviderStore()

    for t in target_names:
        adp = get_adapter(t)
        if adp.supported_protocols == ["google-oauth"]:
            if all_targets:
                print(
                    f"• Skipping '{t}' (uses Google OAuth accounts, not API providers)"
                )
                continue
            raise SwitchError(
                "Antigravity uses Google OAuth accounts. "
                f"Use 'xpx apply {t} --account <name>' instead."
            )

        pv, model = parse_provider_and_model(
            provider_spec, explicit_model, t, state_store, pv_store
        )
        merged_spec, has_adhoc = build_merged_spec(pv, t, model, args)

        if is_dry_run:
            fast_info = " (fast)" if merged_spec.fast else ""
            print(
                f"would apply provider '{pv.name}' "
                f"(model: {merged_spec.model or 'default'}) to '{t}'{fast_info}"
            )
            continue

        # 端侧写入副作用
        adp.apply(merged_spec)

        # 记忆持久化 (unless --no-save)
        if has_adhoc and not no_save:
            if t not in pv.targets:
                pv.targets[t] = TargetOverrides()
            t_over = pv.targets[t]
            if getattr(adp, "supports_fast", False) and merged_spec.fast is not None:
                t_over.fast = merged_spec.fast
            if getattr(adp, "supports_wire_api", False) and merged_spec.wire_api:
                t_over.wire_api = merged_spec.wire_api
            if (
                getattr(adp, "supports_web_search", False)
                and merged_spec.web_search is not None
            ):
                t_over.web_search = merged_spec.web_search
            # persist custom target headers
            for k, v in merged_spec.headers.items():
                if k not in pv.headers or pv.headers[k] != v:
                    t_over.headers[k] = v
            pv_store.save(pv)

        # 记录全局激活状态
        state_store.set_target_state(
            t,
            active_type="provider",
            active_name=pv.name,
            active_model=merged_spec.model,
        )

        model_str = f"/{merged_spec.model}" if merged_spec.model else ""
        fast_str = " (fast mode enabled)" if merged_spec.fast else ""
        print(f"✔ Applied '{pv.name}{model_str}' to {t}{fast_str}.")

    return 0
