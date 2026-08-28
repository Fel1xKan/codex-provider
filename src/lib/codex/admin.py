from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import lib.codex.store as st
from lib.codex.doctor import load_auth_json
from lib.codex.switch import switch_provider
from lib.common.common_store import (
    atomic_write_bytes,
)
from lib.common.constants import MODE_OFFICIAL, SECRET_FILE_MODE
from lib.common.errors import SwitchError
from lib.common.network import run_models_test as default_run_models_test
from lib.common.platform import (
    run_editor as default_run_editor,
)
from lib.common.platform import (
    select_provider_interactive,
)
from lib.common.recent import (
    ensure_recent_providers,
    sort_providers_by_recent,
)
from lib.common.toml_config import (
    format_toml_value,
    redact_sensitive_config,
    validate_provider_name,
)


def get_run_editor() -> Any:
    mod = sys.modules.get("cli.codex_provider") or sys.modules.get("codex_provider")
    if mod and hasattr(mod, "run_editor"):
        return mod.run_editor
    return default_run_editor


def get_run_models_test() -> Any:
    mod = sys.modules.get("cli.codex_provider") or sys.modules.get("codex_provider")
    if mod and hasattr(mod, "run_models_test"):
        return mod.run_models_test
    return default_run_models_test


@contextmanager
def temporary_provider(provider: str) -> Iterator[None]:
    state = st.ensure_provider_state(read_only=True)
    previous = state.active_provider
    switch_provider(provider, dry_run=False)
    try:
        yield
    finally:
        if previous:
            switch_provider(previous, dry_run=False)


def ensure_registry_ready() -> None:
    state = st.ensure_provider_state(read_only=True)
    if not state.providers:
        raise SwitchError("no model providers configured; add one first with `cpx add`")


def resolve_provider(provider: str | None) -> str:
    ensure_registry_ready()
    state = st.ensure_provider_state(read_only=True)
    providers = state.providers
    if provider:
        provider = validate_provider_name(provider)
        if provider not in providers:
            known = ", ".join(sorted(providers.keys()))
            raise SwitchError(f"unknown provider '{provider}', available: {known}")
        return provider

    selected = select_provider_interactive(
        providers, current_provider=state.active_provider
    )
    if not selected:
        raise SwitchError("no provider selected")
    return selected


def print_list() -> int:
    state = st.ensure_provider_state(read_only=True)
    providers = state.providers
    active = state.active_provider
    recent = ensure_recent_providers(st.recent_path())
    ordered = sort_providers_by_recent(providers, recent)

    for name in ordered:
        marker = "*" if name == active else " "
        profile = st.auth_profile_path(name, create=False)
        auth_status = "yes" if profile.exists() else "no"
        print(f"{marker} {name} (auth={auth_status})")
    return 0


def print_status() -> int:
    state = st.ensure_provider_state(read_only=True)
    active = state.active_provider or "(none)"
    print(f"tool home: {st.tool_home()}")
    print(f"tool config: {st.tool_config_path()}")
    print(f"auth store: {st.auth_store_dir(create=False)}")
    print(f"codex dir: {state.codex_dir}")
    print(f"active provider: {active}")
    print("")
    return print_list()


def show_provider_config(provider: str | None) -> int:
    state = st.ensure_provider_state(read_only=True)
    target = provider or state.active_provider
    if not target:
        raise SwitchError("no active provider set")
    target = validate_provider_name(target)
    if target not in state.providers:
        raise SwitchError(f"unknown provider '{target}'")
    config = state.providers[target]
    redacted = redact_sensitive_config(config)
    print(f"[{target}]")
    for key, value in redacted.items():
        print(f"{key} = {format_toml_value(value)}")
    return 0


def edit_provider_config(provider: str | None) -> int:
    state = st.ensure_provider_state(read_only=True)
    target = provider or state.active_provider
    if not target:
        raise SwitchError("no active provider set")
    target = validate_provider_name(target)
    if target not in state.providers:
        raise SwitchError(f"unknown provider '{target}'")
    res = get_run_editor()(st.tool_config_path())
    return 0 if res is None else res


def auth_target_path(provider: str | None) -> tuple[str | None, Any]:
    if provider is None:
        state = st.ensure_provider_state(read_only=True)
        return state.active_provider or None, st.runtime_auth_path(state.codex_dir)
    provider = validate_provider_name(provider)
    return provider, st.auth_profile_path(provider, create=False)


def show_auth(provider: str | None) -> int:
    target, path = auth_target_path(provider)
    if not path.exists():
        raise SwitchError(f"auth file not found: {path}")
    payload = load_auth_json(path)
    label = f"profile '{target}'" if target else "runtime auth.json"
    print(f"Auth file: {path} ({label})")
    for key in sorted(payload.keys()):
        val = payload[key]
        status = "configured" if isinstance(val, str) and val else "empty"
        print(f"  {key}: {status}")
    return 0


def edit_auth(provider: str | None) -> int:
    target, path = auth_target_path(provider)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(path, b"{}\n", secret=True, mode=SECRET_FILE_MODE)
    before_data = path.read_bytes() if path.exists() else b"{}\n"
    res = get_run_editor()(path)
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("JSON must be an object")
        except Exception as exc:
            path.write_bytes(before_data)
            raise SwitchError(f"invalid auth JSON: {exc}") from exc
    return 0 if res is None else res


def test_provider(provider: str | None, timeout: float) -> int:
    target = resolve_provider(provider)
    state = st.ensure_provider_state(read_only=True)
    config = state.providers[target]
    if config.get("mode") == MODE_OFFICIAL:
        raise SwitchError(
            f"provider '{target}' uses official Codex login; "
            f"use `cpx ping {target}` instead"
        )
    base_url = config.get("base_url", "")
    profile = st.auth_profile_path(target, create=False)
    if not profile.exists():
        raise SwitchError(f"auth profile is missing for provider '{target}': {profile}")
    auth_data = load_auth_json(profile)
    api_key = auth_data.get("OPENAI_API_KEY", "")
    return get_run_models_test()(
        target, base_url, api_key, timeout, state.active_provider
    )


def test_direct_base_url(base_url: str, api_key: str, timeout: float) -> int:
    state = st.ensure_provider_state(read_only=True)
    return get_run_models_test()(
        "direct",
        base_url,
        api_key,
        timeout,
        state.active_provider,
    )
