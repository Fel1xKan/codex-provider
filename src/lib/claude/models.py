from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import lib.claude.store as st
from lib.common.common_store import atomic_write_bytes
from lib.common.errors import SwitchError
from lib.common.network import (
    WireProtocol,
    fetch_provider_models,
)


def models_dir(*, create: bool = True) -> Path:
    mod = sys.modules.get("cli.claude_provider") or sys.modules.get("claude_provider")
    if mod and hasattr(mod, "MODELS_DIR"):
        path = mod.MODELS_DIR
    else:
        path = st.tool_home() / "models"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def models_path(provider: str, *, create: bool = False) -> Path:
    return models_dir(create=create) / f"{provider}.json"


def load_provider_models(provider: str) -> list[str]:
    path = models_path(provider)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SwitchError(f"invalid models file: {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("models"), list):
        raise SwitchError(f"models file must contain a models list: {path}")
    return [str(m) for m in data["models"]]


def save_provider_models(provider: str, models: list[str]) -> Path:
    path = models_path(provider, create=True)
    payload = (
        json.dumps(
            {"provider": provider, "models": sorted(models)},
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")
    atomic_write_bytes(path, payload)
    return path


def _resolve_target(provider: str | None) -> str:
    state = st.ensure_provider_state(read_only=True)
    target = provider or state.active_provider
    if not target:
        raise SwitchError("no active provider; pass a provider name")
    if target not in state.providers:
        raise SwitchError(f"unknown provider '{target}'")
    return target


def _provider_endpoint(
    config: dict[str, Any],
) -> tuple[str, str]:
    base_url = config.get("base_url", "")
    models_url = config.get("models_url", "")
    if not base_url:
        raise SwitchError("provider has no base_url configured")
    return base_url, models_url


def _provider_api_key(provider: str) -> str:
    profile = st.auth_profile_path(provider, create=False)
    if not profile.exists():
        raise SwitchError(f"auth profile is missing for provider '{provider}'")
    payload = json.loads(profile.read_text(encoding="utf-8"))
    return payload.get("ANTHROPIC_AUTH_TOKEN") or payload.get("ANTHROPIC_API_KEY", "")


def sync_provider_models(provider: str | None, dry_run: bool = False) -> int:
    target = _resolve_target(provider)
    state = st.ensure_provider_state(read_only=True)
    config = state.providers[target]
    base_url, models_url = _provider_endpoint(config)
    api_key = _provider_api_key(target)
    models = fetch_provider_models(
        base_url,
        api_key,
        WireProtocol.ANTHROPIC,
        models_url_override=models_url or None,
    )
    if not dry_run:
        path = save_provider_models(target, models)
        action = "synced"
        print(f"{action} models for provider '{target}': {len(models)} models")
        print(f"models file: {path}")
    else:
        print(f"would sync models for provider '{target}': {len(models)} models")
    return 0


def sync_all_models(dry_run: bool = False) -> int:
    state = st.ensure_provider_state(read_only=True)
    if not state.providers:
        raise SwitchError("no providers configured")
    failures = 0
    for target in sorted(state.providers):
        try:
            sync_provider_models(target, dry_run)
        except SwitchError as exc:
            print(f"error: {exc}", file=sys.stderr)
            failures += 1
    return 0 if failures == 0 else 1


def list_provider_models(provider: str | None, remote: bool = False) -> int:
    target = _resolve_target(provider)
    state = st.ensure_provider_state(read_only=True)
    config = state.providers[target]
    if remote:
        base_url, models_url = _provider_endpoint(config)
        api_key = _provider_api_key(target)
        models = fetch_provider_models(
            base_url,
            api_key,
            WireProtocol.ANTHROPIC,
            models_url_override=models_url or None,
        )
    else:
        models = load_provider_models(target)
    print(f"provider: {target}")
    print(f"models ({len(models)}):")
    for model in models:
        print(f"- {model}")
    return 0


def set_provider_model(
    provider: str | None,
    model: str,
    dry_run: bool = False,
) -> int:
    if not model or not model.strip():
        raise SwitchError("model must not be empty")
    model = model.strip()
    target = _resolve_target(provider)
    state = st.ensure_provider_state(read_only=dry_run)
    known = load_provider_models(target)
    if known and model not in known:
        raise SwitchError(
            f"unknown model '{model}' for provider '{target}', available: "
            + ", ".join(known)
        )

    providers = dict(state.providers)
    config = dict(providers[target])
    provider_env = dict(config.get("env", {}))
    model_keys = (
        "ANTHROPIC_MODEL",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL",
        "ANTHROPIC_DEFAULT_OPUS_MODEL",
        "ANTHROPIC_DEFAULT_SONNET_MODEL",
        "ANTHROPIC_SUBAGENT_MODEL",
        "CLAUDE_CODE_SUBAGENT_MODEL",
    )
    for key in model_keys:
        provider_env[key] = model
    config["env"] = provider_env
    config["model"] = model
    providers[target] = config

    from lib.claude.edit import _render_tool_payload
    from lib.claude.switch import _render_settings_payload

    tool_payload = _render_tool_payload(
        state.settings_path, providers, state.active_provider
    )
    render_config = dict(config)
    render_config["auth_token"] = _provider_api_key(target)
    settings_payload = _render_settings_payload(state, target, render_config)
    if not dry_run:
        atomic_write_bytes(
            st.tool_config_path(),
            tool_payload,
            secret=True,
            mode=0o600,
        )
        atomic_write_bytes(
            st.settings_path(),
            settings_payload,
            secret=True,
        )

    action = "would set" if dry_run else "set"
    print(f"{action} model: {target}/{model}")
    return 0


def models_command(
    command: str,
    provider: str | None,
    model: str | None,
    dry_run: bool,
    all_providers: bool,
    remote: bool,
) -> int:
    if command == "sync" and all_providers:
        if provider is not None:
            raise SwitchError("--all cannot be combined with a provider")
        return sync_all_models(dry_run)
    if command == "list":
        return list_provider_models(provider, remote)
    if command == "sync":
        return sync_provider_models(provider, dry_run)
    if command == "set":
        if not model:
            raise SwitchError("models set requires a model ID")
        return set_provider_model(provider, model, dry_run)
    return 0
