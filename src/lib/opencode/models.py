from __future__ import annotations

import json
from typing import Any

import lib.opencode.admin as adm
from lib.common.errors import SwitchError
from lib.common.network import get_request_module, normalize_base_url
from lib.opencode.patch import patch_provider_models
from lib.opencode.store import (
    load_auth_keys,
    load_state,
    provider_models,
)


def fetch_provider_models(base_url: str, api_key: str) -> list[str]:
    base_url = normalize_base_url(base_url)
    models_url = f"{base_url}/models"
    req_mod = get_request_module()
    req = req_mod.Request(
        models_url,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    try:
        with req_mod.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, dict) and isinstance(data.get("data"), list):
                models = [
                    m["id"]
                    for m in data["data"]
                    if isinstance(m, dict) and isinstance(m.get("id"), str)
                ]
                if models:
                    return sorted(models)
    except Exception:
        pass
    return ["gpt-4o", "gpt-4o-mini", "claude-3-5-sonnet-20241022"]


def add_models_parser(subparsers: Any) -> None:
    models_parser = subparsers.add_parser("models", help="Manage provider models")
    models_sub = models_parser.add_subparsers(dest="models_command", required=True)
    list_p = models_sub.add_parser("list", help="List models for a provider")
    list_p.add_argument("provider", nargs="?", help="Provider name")
    sync_p = models_sub.add_parser("sync", help="Sync models from provider API")
    sync_p.add_argument("provider", nargs="?", help="Provider name")
    sync_p.add_argument("--dry-run", action="store_true", help="Perform a dry run")


def models_command(command: str, provider: str | None, dry_run: bool = False) -> int:
    state = load_state()
    target = provider or state.current_provider
    if not target:
        raise SwitchError("no current provider; pass a provider name")
    if target not in state.providers:
        raise SwitchError(f"unknown provider '{target}'")

    if command == "list":
        options = state.providers[target].get("options", {})
        base_url = options.get("baseURL") if isinstance(options, dict) else None
        keys = load_auth_keys().get(target, [])
        api_key = keys[0] if keys else ""
        if isinstance(base_url, str) and base_url:
            try:
                models = fetch_provider_models(base_url, api_key)
            except Exception:
                models = list(provider_models(state, target).keys())
        else:
            models = list(provider_models(state, target).keys())
        print(f"provider: {target}")
        print(f"models ({len(models)}):")
        for m in models:
            print(f"- {m}")
        return 0

    if command == "sync":
        options = state.providers[target].get("options", {})
        base_url = options.get("baseURL") if isinstance(options, dict) else None
        if not isinstance(base_url, str):
            raise SwitchError(f"provider '{target}' has no options.baseURL configured")
        keys = load_auth_keys().get(target, [])
        api_key = keys[0] if keys else ""
        models_list = fetch_provider_models(base_url, api_key)
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

    return 0
