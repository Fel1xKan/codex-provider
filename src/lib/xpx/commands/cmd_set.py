"""`xpx set` and `xpx show`: the single surface for a provider's fields.

`rename`, `config set`, and `auth set` all edited the same `ProviderSpec`
object through three different commands with three different flag sets, and
each carried its own copy of the "re-apply to active targets" logic. They are
now one write command (`set`) and one read command (`show`), which removes both
the duplication and the question of where a given field is edited.
"""

from __future__ import annotations

import getpass
import sys
from typing import Any

from lib.common.errors import SwitchError
from lib.xpx.adapters.registry import get_adapter
from lib.xpx.commands._provider_sync import (
    mask_secret,
    reapply_active_targets,
    report_refresh,
)
from lib.xpx.commands.cmd_apply import _check_target_compatibility
from lib.xpx.store.provider_store import (
    ProviderStore,
    TargetOverrides,
    validate_provider_name,
)
from lib.xpx.store.state_store import StateStore

VALID_PROTOCOLS = ("openai", "anthropic")


def _get_key(args: Any, *, prompt: str) -> str | None:
    """Resolve an API key from --key, --key-stdin, or an interactive prompt."""
    key = getattr(args, "key", None)
    if getattr(args, "key_stdin", False):
        key = sys.stdin.readline().rstrip("\r\n")
    elif not key and sys.stdin.isatty():
        key = getpass.getpass(prompt)
    return key


def run_set(args: Any) -> int:
    """Create a provider, or update any of its fields in place.

    Two shapes, distinguished by an optional positional target:

        xpx set <provider> [<flags>]            update universal fields
        xpx set <provider> <target> [<flags>]   update that client's overrides

    The target is positional rather than a `--target` flag because it reads as
    "this provider, as seen by that client" and removes the need for mutual
    exclusion between universal and target-scoped flags.
    """
    raw_name = args.name
    store = ProviderStore()
    existing = store.get(raw_name)
    new_name = getattr(args, "rename_to", None)

    raw_target = getattr(args, "target", None)
    target = _resolve_target(raw_target) if raw_target else None

    if existing is None:
        if target:
            raise SwitchError(
                f"provider '{raw_name}' does not exist; "
                "create it first with 'xpx set <provider> --base-url <url> --key <key>'"
            )
        return _create(args, store)

    if target:
        incompatible = [
            flag
            for flag, value in (
                ("--base-url", getattr(args, "base_url", None)),
                ("--protocol", getattr(args, "protocol", None)),
                ("--name", new_name),
            )
            if value
        ]
        if incompatible:
            raise SwitchError(
                f"{', '.join(incompatible)} cannot be combined with a target "
                "name; they apply to the provider itself"
            )
        return _set_target_overrides(args, store, existing, target)

    return _update_universal(args, store, existing, new_name)


def _resolve_target(raw_target: str) -> str:
    """Validate a positional target name, rejecting anything else early.

    Without this a typo such as `xpx set deepseek gpt-4o --fast` would look like
    a target and fail with a confusing message.
    """
    from lib.xpx.adapters.registry import get_all_adapters

    name = raw_target.strip().lower()
    adapters = get_all_adapters()
    if name not in adapters:
        available = ", ".join(sorted(adapters))
        raise SwitchError(
            f"unknown target client: '{raw_target}'. Supported targets: {available}. "
            "To update the provider itself, omit the second argument."
        )
    return name


def _create(args: Any, store: ProviderStore) -> int:
    name = validate_provider_name(args.name)
    base_url = getattr(args, "base_url", None)
    if not base_url and sys.stdin.isatty():
        base_url = input(f"Enter base URL for provider '{name}': ").strip()
    if not base_url:
        raise SwitchError("base_url is required (pass --base-url)")

    protocol = (getattr(args, "protocol", None) or "openai").lower()
    if protocol not in VALID_PROTOCOLS:
        raise SwitchError(
            f"unsupported protocol '{protocol}'; "
            f"choose one of: {', '.join(VALID_PROTOCOLS)}"
        )

    api_key = _get_key(args, prompt="Enter API Key: ")
    if not api_key:
        if not sys.stdin.isatty():
            raise SwitchError("API key is required (pass --key or --key-stdin)")
        api_key = ""

    from lib.xpx.store.provider_store import ProviderSpec

    spec = ProviderSpec(
        name=name,
        base_url=base_url,
        api_key=api_key,
        protocol=protocol,
        default_model=getattr(args, "default_model", None),
    )

    headers = getattr(args, "header", None) or []
    for item in headers:
        if "=" in item:
            k, v = item.split("=", 1)
            if v.strip():
                spec.headers[k.strip()] = v.strip()

    store.save(spec)
    print(f"\u2714 Added provider '{name}' ({spec.protocol}, {spec.base_url})")
    return 0


def _update_universal(
    args: Any, store: ProviderStore, spec: Any, new_name: str | None
) -> int:
    changes: list[str] = []

    base_url = getattr(args, "base_url", None)
    if base_url:
        spec.base_url = base_url.strip()
        changes.append("base_url")

    protocol = getattr(args, "protocol", None)
    if protocol:
        protocol = protocol.lower()
        if protocol not in VALID_PROTOCOLS:
            raise SwitchError(
                f"unsupported protocol '{protocol}'; "
                f"choose one of: {', '.join(VALID_PROTOCOLS)}"
            )
        if protocol != spec.protocol:
            spec.protocol = protocol
            changes.append("protocol")

    default_model = getattr(args, "default_model", None)
    if default_model:
        spec.default_model = default_model.strip()
        changes.append("default_model")

    # `--key` / `--key-stdin` replace the credential; an interactive prompt only
    # happens when the user explicitly asked to rotate it.
    if getattr(args, "key", None) or getattr(args, "key_stdin", False):
        key = _get_key(args, prompt=f"Enter new API Key for '{spec.name}': ")
        if not key:
            raise SwitchError("API key cannot be empty")
        spec.api_key = key
        changes.append("api_key")

    headers = getattr(args, "header", None) or []
    for item in headers:
        if "=" in item:
            k, v = item.split("=", 1)
            k = k.strip()
            if v.strip():
                spec.headers[k] = v.strip()
                changes.append(f"header {k}")
            else:
                spec.headers.pop(k, None)
                changes.append(f"header {k} (removed)")
        else:
            spec.headers.pop(item.strip(), None)
            changes.append(f"header {item.strip()} (removed)")

    options = getattr(args, "option", None) or []
    if options:
        raise SwitchError(
            "--option applies to a single client; "
            "pass a target name: 'xpx set <provider> <target> --option k=v'"
        )

    if not changes and not new_name:
        raise SwitchError(
            "nothing to update; pass at least one of --base-url, --protocol, "
            "--default-model, --key, --key-stdin, --header, or --name"
        )

    store.save(spec)

    if new_name and new_name != spec.name:
        store.rename(spec.name, new_name)
        # Renaming also moves the catalog and the active-target pointers.
        refreshed = reapply_active_targets(store.require(new_name))
        if changes:
            action = (
                f"Renamed provider '{spec.name}' to '{new_name}' "
                f"(updated {', '.join(changes)})"
            )
        else:
            action = f"Renamed provider '{spec.name}' to '{new_name}'"
        report_refresh(action, new_name, refreshed)
        return 0

    refreshed = reapply_active_targets(spec)
    report_refresh(
        f"Updated {', '.join(changes)} on '{spec.name}'", spec.name, refreshed
    )
    return 0


def _set_target_overrides(
    args: Any, store: ProviderStore, spec: Any, target: str
) -> int:
    adp = get_adapter(target)  # validates the target name
    _check_target_compatibility(adp, target, args)

    if target not in spec.targets:
        spec.targets[target] = TargetOverrides()
    overrides = spec.targets[target]

    changes: list[str] = []

    if getattr(args, "fast", None) is not None:
        overrides.fast = bool(args.fast)
        changes.append(f"fast={overrides.fast}")

    wire_api = getattr(args, "wire_api", None)
    if wire_api is not None:
        if wire_api not in ("chat", "responses"):
            raise SwitchError(
                f"invalid wire-api '{wire_api}'; must be 'chat' or 'responses'"
            )
        overrides.wire_api = wire_api
        changes.append(f"wire_api={wire_api}")

    web_search = getattr(args, "web_search", None)
    if web_search is not None:
        if isinstance(web_search, str):
            overrides.web_search = web_search.lower() in ("true", "1", "yes")
        else:
            overrides.web_search = bool(web_search)
        changes.append(f"web_search={overrides.web_search}")

    for item in getattr(args, "header", None) or []:
        if "=" in item:
            k, v = item.split("=", 1)
            k = k.strip()
            if v.strip():
                overrides.headers[k] = v.strip()
                changes.append(f"header {k}")
            else:
                overrides.headers.pop(k, None)
                changes.append(f"header {k} (removed)")
        else:
            overrides.headers.pop(item.strip(), None)
            changes.append(f"header {item.strip()} (removed)")

    for item in getattr(args, "option", None) or []:
        if "=" in item:
            k, v = item.split("=", 1)
            k = k.strip()
            if v.strip():
                overrides.options[k] = v.strip()
                changes.append(f"option {k}")
            else:
                overrides.options.pop(k, None)
                changes.append(f"option {k} (removed)")
        else:
            overrides.options.pop(item.strip(), None)
            changes.append(f"option {item.strip()} (removed)")

    if not changes:
        raise SwitchError(
            "nothing to update; pass at least one of --fast, --wire-api, "
            "--web-search, --header, or --option"
        )

    store.save(spec)
    refreshed = reapply_active_targets(spec)
    report_refresh(
        f"Updated {', '.join(changes)} for target '{target}' on '{spec.name}'",
        spec.name,
        refreshed,
    )
    return 0


def run_show(args: Any) -> int:
    """Show one provider's effective configuration, or summarize all of them."""
    store = ProviderStore()
    name = getattr(args, "name", None)
    target = getattr(args, "target", None)
    reveal = getattr(args, "reveal_key", False)

    if not name:
        return _show_all(store, reveal)

    spec = store.require(name)
    shown_key = spec.api_key if reveal else mask_secret(spec.api_key)

    print(f"Provider:      {spec.name}")
    print(f"Protocol:      {spec.protocol}")
    print(f"Base URL:      {spec.base_url}")
    print(f"Default Model: {spec.default_model or '(none)'}")
    print(f"API Key:       {shown_key}")

    if spec.headers:
        print("Headers:")
        for k, v in sorted(spec.headers.items()):
            print(f"  {k}: {v}")

    if target:
        overrides = spec.targets.get(target)
        if overrides is None:
            print(f"Target '{target}': no overrides configured")
            return 0
        print(f"Target '{target}' overrides:")
        _print_overrides(overrides, indent="  ")
        return 0

    if spec.targets:
        print("Target overrides:")
        for t_name in sorted(spec.targets):
            print(f"  [{t_name}]")
            _print_overrides(spec.targets[t_name], indent="    ")

    state = StateStore().load()
    active = [
        t
        for t, ts in sorted(state.targets.items())
        if ts.active_type == "provider" and ts.active_name == spec.name
    ]
    if active:
        print(f"Active in:     {', '.join(active)}")
    return 0


def _show_all(store: ProviderStore, reveal: bool) -> int:
    providers = store.list_all()
    if not providers:
        print("No providers configured.")
        return 0

    state = StateStore().load()
    header = (
        f"{'PROVIDER':<18} {'PROTOCOL':<11} {'KEY':<20} {'DEFAULT MODEL':<28} ACTIVE"
    )
    print(header)
    print("-" * len(header))
    for p in providers:
        key = p.api_key if reveal else mask_secret(p.api_key)
        active = [
            t
            for t, ts in sorted(state.targets.items())
            if ts.active_type == "provider" and ts.active_name == p.name
        ]
        print(
            f"{p.name:<18} {p.protocol:<11} {key:<20} "
            f"{(p.default_model or '-'):<28} {', '.join(active) or '-'}"
        )
    return 0


def _print_overrides(overrides: Any, indent: str = "  ") -> None:
    """Render one target's overrides, skipping unset fields."""
    if overrides.fast is not None:
        print(f"{indent}fast:       {overrides.fast}")
    if overrides.wire_api:
        print(f"{indent}wire_api:   {overrides.wire_api}")
    if overrides.web_search is not None:
        print(f"{indent}web_search: {overrides.web_search}")
    for k, v in sorted((overrides.headers or {}).items()):
        print(f"{indent}header {k}: {v}")
    for k, v in sorted((overrides.options or {}).items()):
        print(f"{indent}option {k}: {v}")
