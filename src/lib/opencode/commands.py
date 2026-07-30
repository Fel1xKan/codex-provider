from __future__ import annotations

import sys
from contextlib import nullcontext
from typing import Any

import json5

import lib.opencode.store as st
from lib.common.errors import SwitchError
from lib.common.recent import (
    ensure_recent_providers,
    record_recent_provider,
    sort_providers_by_recent,
)
from lib.opencode.admin import atomic_write_config
from lib.opencode.patch import patch_default_model


def print_list() -> int:
    state = st.load_state()
    auth_provider_ids = st.load_auth_provider_ids()
    for provider in sort_providers_by_recent(
        state.providers, ensure_recent_providers(st.recent_path())
    ):
        marker = "*" if provider == state.current_provider else " "
        models = st.provider_models(state, provider)
        auth = st.provider_has_auth(
            provider, state.providers[provider], auth_provider_ids
        )
        print(f"{marker} {provider} (models={len(models)}, auth={auth})")
    return 0


def print_status() -> int:
    state = st.load_state()
    print(f"global config: {state.path}")
    print(f"auth file: {st.auth_path()}")
    print(f"default provider: {state.current_provider or '(OpenCode fallback)'}")
    print(f"default model: {state.current_model or '(OpenCode fallback)'}")
    print(f"model source: {state.model_source}")
    print("")
    return print_list()


def select_model_interactive(
    provider: str, models: dict[str, dict[str, Any]]
) -> str | None:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise SwitchError(
            f"provider '{provider}' has multiple models; pass --model with one of: "
            + ", ".join(sorted(models))
        )
    names = sorted(models)
    print(f"Models for {provider}:")
    for index, model in enumerate(names, start=1):
        display_name = models[model].get("name")
        suffix = f" ({display_name})" if isinstance(display_name, str) else ""
        print(f"{index:>2}. {model}{suffix}")
    value = input("Model number (Enter to cancel): ").strip()
    if not value:
        return None
    try:
        idx = int(value)
    except ValueError as exc:
        raise SwitchError("model selection must be a number") from exc
    if idx < 1 or idx > len(names):
        raise SwitchError(f"model selection must be between 1 and {len(names)}")
    return names[idx - 1]


def resolve_model(
    state: st.ConfigState, provider: str, requested: str | None
) -> str | None:
    models = st.provider_models(state, provider)
    if not models:
        raise SwitchError(
            f"provider '{provider}' has no configured models; run "
            f"opencode-provider models sync {provider}"
        )
    if requested and "/" in requested:
        requested_provider, requested = requested.split("/", 1)
        if requested_provider != provider:
            raise SwitchError(
                f"model provider '{requested_provider}' does not match "
                f"target '{provider}'"
            )
    if requested:
        if requested not in models:
            raise SwitchError(
                f"unknown model '{provider}/{requested}', available: "
                + ", ".join(sorted(models))
            )
        return requested
    if len(models) == 1:
        return next(iter(models))
    return select_model_interactive(provider, models)


def switch_provider(provider: str, requested_model: str | None, dry_run: bool) -> int:
    lock = nullcontext() if dry_run else st.lock_mgr
    with lock:
        state = st.load_state()
        if provider not in state.providers:
            raise SwitchError(f"unknown provider '{provider}'")
        if not st.provider_is_enabled(state, provider, state.providers[provider]):
            raise SwitchError(
                f"provider '{provider}' is disabled or excluded by "
                f"enabled_providers or disabled_providers"
            )

        model = resolve_model(state, provider, requested_model)
        if model is None:
            print("switch cancelled")
            return 0

        target = f"{provider}/{model}"
        configured_model = state.data.get("model")
        if configured_model == target:
            if not dry_run:
                record_recent_provider(st.recent_path(), provider)
            print(f"already using default model: {target}")
            return 0
        updated = patch_default_model(state.text, target)
        try:
            updated_data = json5.loads(updated)
        except Exception:
            updated_data = {}
        if updated_data.get("model") != target:
            raise SwitchError("updated config did not contain the requested model")
        if not dry_run:
            atomic_write_config(state.path, state.text, updated)
            record_recent_provider(st.recent_path(), provider)

    action = "would switch" if dry_run else "switched"
    effective_model = (
        state.current_model
        if state.current_provider == provider and requested_model is None
        else model
    )
    print(f"{action} default model: {provider}/{effective_model}")
    return 0
