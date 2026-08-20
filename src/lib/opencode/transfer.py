from __future__ import annotations

import json
from contextlib import nullcontext, suppress

import lib.opencode.store as st
from lib.common.common_store import SECRET_FILE_MODE, atomic_write_bytes
from lib.common.errors import SwitchError
from lib.common.transfer import (
    read_import_data,
    validate_export,
    write_export,
)
from lib.opencode.admin import atomic_write_config
from lib.opencode.patch import (
    patch_add_provider,
    patch_default_model,
    patch_delete_provider,
)


def export_command(file_path: str | None) -> int:
    state = st.load_state()
    auth_keys = {}
    apath = st.auth_path()
    if apath.exists():
        with suppress(Exception):
            auth_keys = json.loads(apath.read_text(encoding="utf-8"))

    export_data = {
        "type": "opencode-provider",
        "version": 1,
        "current_provider": state.current_provider,
        "current_model": state.current_model,
        "providers": {},
    }

    for provider, pconfig in state.providers.items():
        p_auth = auth_keys.get(provider, {})
        export_data["providers"][provider] = {"config": pconfig, "auth": p_auth}

    payload = json.dumps(export_data, indent=2, ensure_ascii=False) + "\n"
    write_export(payload, file_path, "OpenCode")
    return 0


def import_command(file_path: str | None, dry_run: bool) -> int:
    try:
        data = read_import_data(file_path)
    except KeyboardInterrupt:
        return 1
    validate_export(data, "opencode-provider")

    providers_to_import = data.get("providers")
    if not isinstance(providers_to_import, dict):
        raise SwitchError("providers must be a JSON object")

    lock = nullcontext() if dry_run else st.lock_mgr
    with lock:
        state = st.load_state()
        text = state.text
        providers_in_config = set(state.providers.keys())

        # Load auth
        auth_file = st.auth_path()
        auth_text = (
            auth_file.read_text(encoding="utf-8") if auth_file.exists() else "{}"
        )
        try:
            auth_data = json.loads(auth_text)
        except Exception:
            auth_data = {}
        if not isinstance(auth_data, dict):
            auth_data = {}

        for provider, info in providers_to_import.items():
            if not st.PROVIDER_PATTERN.fullmatch(provider):
                raise SwitchError(f"invalid provider ID: {provider}")
            if not isinstance(info, dict):
                raise SwitchError(f"invalid provider entry: {provider}")
            config = info.get("config")
            auth = info.get("auth")
            if not isinstance(config, dict) or not isinstance(auth, dict):
                raise SwitchError(
                    f"provider {provider} must have config and auth objects"
                )

            action = "would add/update" if dry_run else "added/updated"
            print(f"{action} provider: {provider}")

            if not dry_run:
                if provider in providers_in_config:
                    with suppress(Exception):
                        text = patch_delete_provider(text, provider)
                text = patch_add_provider(text, provider, config)
                auth_data[provider] = auth

        # Handle switching/setting default model
        current_provider = data.get("current_provider")
        current_model = data.get("current_model")

        if current_provider and current_model:
            target = f"{current_provider}/{current_model}"
            if (
                current_provider in providers_to_import
                or current_provider in state.providers
            ):
                if dry_run:
                    print(f"would switch default model: {target}")
                else:
                    text = patch_default_model(text, target)
                    print(f"switched default model: {target}")

        if not dry_run:
            # Write config
            atomic_write_config(state.path, state.text, text)
            # Write auth
            st.data_dir().mkdir(parents=True, exist_ok=True)
            updated_auth = json.dumps(auth_data, ensure_ascii=False, indent=2) + "\n"
            atomic_write_bytes(
                auth_file,
                updated_auth.encode("utf-8"),
                secret=True,
                mode=SECRET_FILE_MODE,
            )

    return 0
