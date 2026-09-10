from __future__ import annotations

import json
from contextlib import nullcontext, suppress
from pathlib import Path

import lib.claude.store as st
from lib.claude.switch import switch_provider
from lib.common.common_store import SECRET_FILE_MODE, atomic_write_bytes
from lib.common.errors import SwitchError
from lib.common.toml_config import validate_provider_name
from lib.common.transfer import (
    build_interoperable_export,
    read_import_data,
    validate_export,
    write_export,
)


def export_command(file_path: str | None, target_tool: str | None = None) -> int:
    state = st.ensure_provider_state(read_only=True)
    if not target_tool:
        export_data = {
            "version": 1,
            "settings_path": str(state.settings_path),
            "active_provider": state.active_provider,
            "providers": state.providers,
        }
        payload = json.dumps(export_data, indent=2, ensure_ascii=False) + "\n"
        if file_path in (None, "-"):
            print(payload, end="")
        else:
            Path(file_path).write_text(payload, encoding="utf-8")
        return 0

    normalized_providers = {}
    for provider, config in state.providers.items():
        auth = {}
        profile = st.auth_profile_path(provider, create=False)
        if profile.exists():
            with suppress(OSError, UnicodeDecodeError, json.JSONDecodeError):
                auth = json.loads(profile.read_text(encoding="utf-8"))
        token = auth.get("ANTHROPIC_AUTH_TOKEN") or auth.get("ANTHROPIC_API_KEY")
        normalized_providers[provider] = {
            "base_url": config.get("base_url"),
            "name": config.get("name"),
            "api_key": token if isinstance(token, str) else "",
            "model": config.get("model"),
        }

    export_data = build_interoperable_export(
        target_tool,
        state.active_provider,
        normalized_providers,
    )

    payload = json.dumps(export_data, indent=2, ensure_ascii=False) + "\n"
    write_export(payload, file_path, target_tool)
    return 0


def import_command(file_path: str | None, dry_run: bool) -> int:
    try:
        data = read_import_data(file_path)
    except KeyboardInterrupt:
        return 1

    if data.get("type") is None:
        return _import_legacy(data, dry_run)
    validate_export(data, "claude-provider")

    providers_to_import = data.get("providers")
    if not isinstance(providers_to_import, dict):
        raise SwitchError("providers must be a JSON object")

    lock = nullcontext() if dry_run else st.state_lock()
    with lock:
        state = st.ensure_provider_state(read_only=dry_run)
        providers = dict(state.providers)
        for provider, info in providers_to_import.items():
            provider = validate_provider_name(provider)
            if not isinstance(info, dict):
                raise SwitchError(f"invalid provider entry: {provider}")
            config = info.get("config")
            auth = info.get("auth")
            if not isinstance(config, dict) or not isinstance(auth, dict):
                raise SwitchError(
                    f"provider {provider} must have config and auth objects"
                )
            if not isinstance(config.get("base_url"), str) or not config["base_url"]:
                raise SwitchError(f"provider {provider} must have a base_url")

            action = "would add/update" if dry_run else "added/updated"
            print(f"{action} provider: {provider}")
            if not dry_run:
                providers[provider] = config
                auth_payload = json.dumps(auth, indent=2, ensure_ascii=False) + "\n"
                atomic_write_bytes(
                    st.auth_profile_path(provider, create=True),
                    auth_payload.encode("utf-8"),
                    secret=True,
                    mode=SECRET_FILE_MODE,
                )

        if not dry_run:
            payload = {
                "settings_path": str(state.settings_path),
                "active_provider": state.active_provider,
                "providers": providers,
            }
            atomic_write_bytes(
                st.tool_config_path(),
                (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode(
                    "utf-8"
                ),
                secret=True,
                mode=SECRET_FILE_MODE,
            )

        active_provider = data.get("active_provider")
        if active_provider and (
            active_provider in providers_to_import or active_provider in state.providers
        ):
            if dry_run:
                print(f"would switch default provider: {active_provider}")
            else:
                switch_provider(active_provider, dry_run=False)
    return 0


def _import_legacy(data: dict[str, object], dry_run: bool) -> int:
    providers = data.get("providers", {})
    if not isinstance(providers, dict):
        raise SwitchError("export providers must be an object")
    active_provider = data.get("active_provider", "")
    if not isinstance(active_provider, str):
        raise SwitchError("export active_provider must be a string")
    state = st.ensure_provider_state(read_only=dry_run)
    payload = {
        "settings_path": str(state.settings_path),
        "active_provider": active_provider,
        "providers": providers,
    }
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if not dry_run:
        st.ensure_tool_home()
        atomic_write_bytes(
            st.tool_config_path(),
            text.encode("utf-8"),
            secret=True,
            mode=SECRET_FILE_MODE,
        )
    action = "would import" if dry_run else "imported"
    print(f"{action} provider registry: {st.tool_config_path()}")
    return 0
