from __future__ import annotations

import json
from contextlib import nullcontext

import lib.cursor.store as st
from lib.common.errors import SwitchError
from lib.common.transfer import (
    build_interoperable_export,
    read_import_data,
    validate_export,
    write_export,
)


def export_command(file_path: str | None, target_tool: str | None = None) -> int:
    store = st.load_store()
    export_data = {
        "type": "cursor-provider",
        "version": 1,
        "current": store.current,
        "accounts": st.accounts_data_dict(store),
    }
    if target_tool:
        normalized_providers = {
            name: {
                "base_url": provider.base_url,
                "name": name,
                "api_key": provider.api_key,
                "models": provider.models,
            }
            for name, provider in store.providers.items()
        }
        export_data = build_interoperable_export(
            target_tool,
            store.current_provider,
            normalized_providers,
        )

    payload = json.dumps(export_data, indent=2, ensure_ascii=False) + "\n"
    write_export(payload, file_path, target_tool or "cursor")
    return 0


def import_command(file_path: str | None, dry_run: bool) -> int:
    try:
        data = read_import_data(file_path)
    except KeyboardInterrupt:
        return 1
    validate_export(data, "cursor-provider")

    accounts_to_import = data.get("accounts", {})
    if not isinstance(accounts_to_import, dict):
        raise SwitchError("accounts must be a JSON object")
    providers_to_import = data.get("providers", {})
    if not isinstance(providers_to_import, dict):
        raise SwitchError("providers must be a JSON object")

    lock = nullcontext() if dry_run else st.lock_mgr
    with lock:
        store = st.load_store()
        accounts_data = st.accounts_data_dict(store)
        providers_data = st.providers_data_dict(store)

        for name, acc_info in accounts_to_import.items():
            if not st.ACCOUNT_PATTERN.fullmatch(name):
                raise SwitchError(f"invalid account name: {name}")
            if not isinstance(acc_info, dict):
                raise SwitchError(f"invalid account entry: {name}")
            auth_data = acc_info.get("auth_data")
            if not isinstance(auth_data, dict):
                raise SwitchError(f"account {name} must have an auth_data object")

            email, display_name, auth_method = st.extract_account_info(auth_data)
            action = "would add/update" if dry_run else "added/updated"
            print(f"{action} account: {name}")

            if not dry_run:
                accounts_data[name] = {
                    "email": acc_info.get("email") or email,
                    "display_name": acc_info.get("display_name") or display_name,
                    "auth_method": acc_info.get("auth_method") or auth_method,
                    "auth_data": auth_data,
                }

        for name, provider_info in providers_to_import.items():
            if not st.PROVIDER_PATTERN.fullmatch(name):
                raise SwitchError(f"invalid provider name: {name}")
            if not isinstance(provider_info, dict):
                raise SwitchError(f"invalid provider entry: {name}")
            base_url = provider_info.get("base_url")
            api_key = provider_info.get("api_key", "")
            api_key_cipher = provider_info.get("api_key_cipher", "")
            models = provider_info.get("models", [])
            if not isinstance(base_url, str) or not base_url:
                raise SwitchError(f"provider {name} must have a base_url")
            if not isinstance(api_key, str) or not isinstance(api_key_cipher, str):
                raise SwitchError(f"provider {name} has invalid authentication data")
            if not isinstance(models, list) or not all(
                isinstance(model, str) for model in models
            ):
                raise SwitchError(f"provider {name} must have a models array")

            action = "would add/update" if dry_run else "added/updated"
            print(f"{action} provider: {name}")
            if not dry_run:
                providers_data[name] = {
                    "base_url": base_url,
                    "api_key": api_key,
                    "api_key_cipher": api_key_cipher,
                    "models": models,
                }

        current = data.get("current")
        current_provider = data.get("current_provider")
        if current_provider is not None and not isinstance(current_provider, str):
            raise SwitchError("current_provider must be a string")

        if not dry_run:
            from lib.cursor.commands import _save_state_file

            st.state_dir().mkdir(parents=True, exist_ok=True)
            _save_state_file(
                store.current or current or "",
                accounts_data,
                current_provider=current_provider or store.current_provider,
                providers=providers_data,
            )

        if current and (current in accounts_to_import or current in store.accounts):
            if dry_run:
                print(f"would switch account: {current}")
            else:
                from lib.cursor.commands import switch_account

                switch_account(current, dry_run=False)
        elif current_provider and (
            current_provider in providers_to_import
            or current_provider in store.providers
        ):
            print(f"imported active provider: {current_provider}")

    return 0
