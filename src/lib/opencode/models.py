from __future__ import annotations

import sys
from typing import Any

import lib.opencode.admin as adm
from lib.common.errors import SwitchError
from lib.common.network import WireProtocol
from lib.common.network import fetch_provider_models as fetch_models
from lib.opencode.patch import patch_provider_models
from lib.opencode.store import (
    ConfigState,
    load_auth_keys,
    load_state,
    provider_models,
)


def fetch_provider_models(
    base_url: str, api_key: str, anthropic: bool = False
) -> list[str]:
    protocol = WireProtocol.ANTHROPIC if anthropic else WireProtocol.OPENAI
    return fetch_models(base_url, api_key, protocol)


def add_models_parser(subparsers: Any) -> None:
    models_parser = subparsers.add_parser("models", help="Manage provider models")
    models_sub = models_parser.add_subparsers(dest="models_command", required=True)
    list_p = models_sub.add_parser("list", help="List models for a provider")
    list_p.add_argument("provider", nargs="?", help="Provider name")
    sync_p = models_sub.add_parser("sync", help="Sync models from provider API")
    sync_p.add_argument("provider", nargs="?", help="Provider name")
    sync_p.add_argument("--dry-run", action="store_true", help="Perform a dry run")
    sync_p.add_argument(
        "--all",
        action="store_true",
        help="Sync models for every configured provider",
    )


def sync_provider_models(state: ConfigState, target: str, dry_run: bool) -> int:
    config = state.providers[target]
    options = config.get("options", {})
    base_url = options.get("baseURL") if isinstance(options, dict) else None
    if not isinstance(base_url, str):
        raise SwitchError(f"provider '{target}' has no options.baseURL configured")
    keys = load_auth_keys().get(target, [])
    api_key = keys[0] if keys else ""
    anthropic = config.get("npm") == "@ai-sdk/anthropic"
    models_list = fetch_provider_models(base_url, api_key, anthropic)
    existing_models = provider_models(state, target)
    model_objs: dict[str, dict[str, Any]] = {}
    for m in models_list:
        if m in existing_models and isinstance(existing_models[m], dict):
            model_objs[m] = existing_models[m]
        else:
            model_objs[m] = {}
    updated = patch_provider_models(state.text, target, model_objs)

    if not dry_run:
        adm.atomic_write_config(state.path, state.text, updated)

    action = "would sync" if dry_run else "synced"
    print(f"{action} models for provider '{target}': {len(models_list)} models")
    return 0


def sync_all_models(state: ConfigState, dry_run: bool) -> int:
    failures = 0
    for target in sorted(state.providers):
        try:
            sync_provider_models(load_state(), target, dry_run)
        except SwitchError as exc:
            print(f"error: {exc}", file=sys.stderr)
            failures += 1
    return 0 if failures == 0 else 1


def models_command(
    command: str,
    provider: str | None,
    dry_run: bool = False,
    all_providers: bool = False,
) -> int:
    state = load_state()
    if command == "sync" and all_providers:
        if provider is not None:
            raise SwitchError("--all cannot be combined with a provider")
        return sync_all_models(state, dry_run)
    target = provider or state.current_provider
    if not target:
        raise SwitchError("no current provider; pass a provider name")
    if target not in state.providers:
        raise SwitchError(f"unknown provider '{target}'")
    config = state.providers[target]
    anthropic = config.get("npm") == "@ai-sdk/anthropic"

    if command == "list":
        options = config.get("options", {})
        base_url = options.get("baseURL") if isinstance(options, dict) else None
        if isinstance(base_url, str) and base_url:
            keys = load_auth_keys().get(target, [])
            api_key = keys[0] if keys else ""
            models = fetch_provider_models(base_url, api_key, anthropic)
        else:
            models = list(provider_models(state, target).keys())
        print(f"provider: {target}")
        print(f"models ({len(models)}):")
        for m in models:
            print(f"- {m}")
        return 0

    if command == "sync":
        return sync_provider_models(state, target, dry_run)

    return 0
