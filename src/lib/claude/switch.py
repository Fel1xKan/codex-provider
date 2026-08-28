from __future__ import annotations

import json
from contextlib import nullcontext
from typing import Any

import lib.claude.store as st
from lib.common.common_store import FileChange, apply_changes
from lib.common.errors import SwitchError
from lib.common.recent import (
    load_recent_providers,
    serialize_recent_providers,
)
from lib.common.toml_config import validate_provider_name


def _render_settings_payload(
    state: st.ProviderState,
    provider: str,
    config: dict[str, Any],
) -> bytes:
    base_text, runtime = st.read_settings()
    provider_env = dict(config.get("env", {}))
    provider_env["ANTHROPIC_BASE_URL"] = config["base_url"]
    credential_env = config.get("credential_env", "ANTHROPIC_AUTH_TOKEN")
    provider_env[credential_env] = config.get("auth_token", "")
    runtime_env = runtime.setdefault("env", {})
    if not isinstance(runtime_env, dict):
        runtime_env = {}
        runtime["env"] = runtime_env
    managed_keys = (
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_MODEL",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL",
        "ANTHROPIC_DEFAULT_OPUS_MODEL",
        "ANTHROPIC_DEFAULT_SONNET_MODEL",
        "ANTHROPIC_SUBAGENT_MODEL",
        "CLAUDE_CODE_SUBAGENT_MODEL",
    )
    for key in managed_keys:
        if key not in provider_env:
            runtime_env.pop(key, None)
    for key, value in provider_env.items():
        if value:
            runtime_env[key] = value
        elif key in runtime_env:
            del runtime_env[key]
    if "model_overrides" in config:
        runtime["modelOverrides"] = config["model_overrides"]
    else:
        runtime.pop("modelOverrides", None)
    return st.render_settings_json(runtime, base_text=base_text).encode("utf-8")


def _render_tool_payload(
    state: st.ProviderState, providers: dict[str, dict[str, Any]], active: str
) -> bytes:
    return (
        json.dumps(
            {
                "settings_path": str(state.settings_path),
                "active_provider": active,
                "providers": providers,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")


def switch_provider(provider: str, dry_run: bool) -> int:
    provider = validate_provider_name(provider)
    lock = nullcontext() if dry_run else st.state_lock()
    with lock:
        state = st.ensure_provider_state(read_only=dry_run)
        providers = state.providers
        if provider not in providers:
            known = ", ".join(sorted(providers.keys()))
            raise SwitchError(f"unknown provider '{provider}', available: {known}")

        target_auth = st.auth_profile_path(provider, create=not dry_run)
        if not target_auth.exists():
            raise SwitchError(
                f"auth profile is missing for provider '{provider}': {target_auth}"
            )
        try:
            payload = json.loads(target_auth.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SwitchError(
                f"invalid auth JSON for provider '{provider}': {target_auth}: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise SwitchError(
                f"auth profile for '{provider}' must contain an object: {target_auth}"
            )
        token = payload.get("ANTHROPIC_AUTH_TOKEN") or payload.get("ANTHROPIC_API_KEY")
        if not isinstance(token, str) or not token:
            raise SwitchError(
                f"auth profile for '{provider}' has no credential "
                f"(ANTHROPIC_AUTH_TOKEN or ANTHROPIC_API_KEY): {target_auth}"
            )

        config = providers[provider]
        config = dict(config)
        config["auth_token"] = token
        config["api_key"] = token
        settings_payload = _render_settings_payload(state, provider, config)
        tool_payload = _render_tool_payload(state, providers, provider)

        recent_record = [provider] + [
            name for name in load_recent_providers(st.recent_path()) if name != provider
        ]
        changes = [
            FileChange(st.settings_path(), settings_payload, secret=True),
            FileChange(st.tool_config_path(), tool_payload, secret=True),
            FileChange(
                st.recent_path(),
                serialize_recent_providers(recent_record),
                secret=True,
            ),
        ]
        if not dry_run:
            apply_changes(changes)

    action = "would switch" if dry_run else "switched"
    print(f"{action} default provider: {provider}")
    print(f"settings file: {st.settings_path()}")
    return 0
