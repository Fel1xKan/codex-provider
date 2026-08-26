from __future__ import annotations

from contextlib import nullcontext
from urllib.parse import urlparse

import lib.codex.store as st
from lib.common.common_store import (
    atomic_write_bytes,
    fsync_directory,
)
from lib.common.constants import RUNTIME_PROVIDER_ID, SECRET_FILE_MODE
from lib.common.errors import SwitchError
from lib.common.network import normalize_base_url
from lib.common.recent import (
    forget_recent_provider,
    rename_recent_provider,
)
from lib.common.toml_config import (
    MODEL_CATALOG_FIELD,
    render_runtime_config,
    render_tool_config,
    validate_provider_name,
)


def derive_provider_name(base_url: str) -> str:
    hostname = urlparse(base_url).hostname
    if not hostname:
        raise SwitchError("unable to derive provider name from base_url")
    name = hostname.split(".")[0]
    return validate_provider_name(name.lower())


def add_provider(
    provider: str | None,
    base_url: str,
    api_key: str,
    display_name: str | None,
    wire_api: str,
    supports_websockets: bool | None,
    dry_run: bool,
    model_catalog_json: str | None = None,
) -> int:
    base_url = normalize_base_url(base_url)
    provider = (
        validate_provider_name(provider) if provider else derive_provider_name(base_url)
    )
    if display_name is not None:
        display_name = display_name.strip()
        if not display_name:
            raise SwitchError("display name must not be empty")
    if not api_key:
        raise SwitchError("api_key must not be empty")

    lock = nullcontext() if dry_run else st.state_lock()
    with lock:
        state = st.ensure_provider_state(read_only=dry_run)
        current = state.active_provider
        providers = state.providers
        if provider in providers:
            raise SwitchError(f"provider already exists: {provider}")

        providers = dict(providers)
        providers[provider] = {
            "base_url": base_url,
            "name": display_name if display_name is not None else provider,
            "requires_openai_auth": True,
            "wire_api": wire_api,
        }
        if supports_websockets is not None:
            providers[provider]["supports_websockets"] = supports_websockets
        if model_catalog_json is not None and model_catalog_json.strip():
            providers[provider][MODEL_CATALOG_FIELD] = model_catalog_json

        profile = st.auth_profile_path(provider, create=not dry_run)
        profile_existed = profile.exists()
        auth_payload = f'{{"OPENAI_API_KEY": "{api_key}"}}\n'.encode()

        base_text = (
            st.tool_config_path().read_text(encoding="utf-8")
            if st.tool_config_path().exists()
            else None
        )
        updated = render_tool_config(
            state.codex_dir,
            providers,
            base_text=base_text,
            active_provider=current,
        )

        if not dry_run:
            try:
                atomic_write_bytes(
                    profile,
                    auth_payload,
                    secret=True,
                    mode=SECRET_FILE_MODE,
                )
                atomic_write_bytes(
                    st.tool_config_path(),
                    updated.encode("utf-8"),
                    secret=True,
                    mode=SECRET_FILE_MODE,
                )
            except SwitchError as exc:
                if not profile_existed:
                    profile.unlink(missing_ok=True)
                    if profile.parent.exists():
                        fsync_directory(profile.parent)
                raise SwitchError(f"unable to commit state changes: {exc}") from exc

    action = "would add" if dry_run else "added"
    auth_action = "replaced auth profile" if profile_existed else "created auth profile"
    print(f"{action} provider: {provider}")
    print(f"display name: {providers[provider]['name']}")
    print(f"{auth_action}: {profile}")
    if current:
        print(f"current provider remains: {current}")
    else:
        print("current provider remains: (none)")
    return 0


def delete_provider(provider: str, delete_auth: bool, dry_run: bool) -> int:
    provider = validate_provider_name(provider)
    lock = nullcontext() if dry_run else st.state_lock()
    with lock:
        state = st.ensure_provider_state(read_only=dry_run)
        current = state.active_provider
        providers = state.providers
        profile = st.auth_profile_path(provider, create=False)

        if provider not in providers:
            if delete_auth and profile.exists():
                if not dry_run:
                    profile.unlink(missing_ok=True)
                    if profile.parent.exists():
                        fsync_directory(profile.parent)
                action = "would remove" if dry_run else "removed"
                print(f"provider not found in registry: {provider}")
                print(f"{action} auth profile: {profile}")
                return 0
            raise SwitchError(f"unknown provider '{provider}'")

        if current == provider:
            raise SwitchError(
                f"cannot delete active provider '{provider}', switch to another first"
            )

        providers = dict(providers)
        del providers[provider]
        base_text = (
            st.tool_config_path().read_text(encoding="utf-8")
            if st.tool_config_path().exists()
            else None
        )
        updated = render_tool_config(
            state.codex_dir,
            providers,
            base_text=base_text,
            active_provider=current,
        )

        if not dry_run:
            atomic_write_bytes(
                st.tool_config_path(),
                updated.encode("utf-8"),
                secret=True,
                mode=SECRET_FILE_MODE,
            )
            if delete_auth:
                profile.unlink(missing_ok=True)
                if profile.parent.exists():
                    fsync_directory(profile.parent)
            forget_recent_provider(st.recent_path(), provider)

    action = "would delete" if dry_run else "deleted"
    print(f"{action} provider: {provider}")
    if delete_auth:
        auth_action = "would remove" if dry_run else "removed"
        print(f"{auth_action} auth profile: {profile}")
    return 0


def rename_provider(old_name: str, new_name: str, dry_run: bool) -> int:
    old_name = validate_provider_name(old_name)
    new_name = validate_provider_name(new_name)
    if old_name == new_name:
        raise SwitchError("old and new provider names must differ")

    lock = nullcontext() if dry_run else st.state_lock()
    with lock:
        state = st.ensure_provider_state(read_only=dry_run)
        current = state.active_provider
        providers = state.providers

        if old_name not in providers:
            raise SwitchError(f"unknown provider '{old_name}'")
        if new_name in providers:
            raise SwitchError(f"provider already exists: {new_name}")

        old_profile = st.auth_profile_path(old_name, create=False)
        new_profile = st.auth_profile_path(new_name, create=not dry_run)

        providers = dict(providers)
        providers[new_name] = providers.pop(old_name)
        active_provider = new_name if current == old_name else current

        base_text = (
            st.tool_config_path().read_text(encoding="utf-8")
            if st.tool_config_path().exists()
            else None
        )
        updated = render_tool_config(
            state.codex_dir,
            providers,
            base_text=base_text,
            active_provider=active_provider,
        )

        if not dry_run:
            if old_profile.exists():
                atomic_write_bytes(
                    new_profile,
                    old_profile.read_bytes(),
                    secret=True,
                    mode=SECRET_FILE_MODE,
                )
                old_profile.unlink(missing_ok=True)
                if old_profile.parent.exists():
                    fsync_directory(old_profile.parent)

            atomic_write_bytes(
                st.tool_config_path(),
                updated.encode("utf-8"),
                secret=True,
                mode=SECRET_FILE_MODE,
            )

            if current == old_name:
                r_config = st.runtime_config_path(state.codex_dir)
                r_auth = st.runtime_auth_path(state.codex_dir)
                base_runtime_text = (
                    r_config.read_text(encoding="utf-8")
                    if r_config.exists()
                    else f'model_provider = "{RUNTIME_PROVIDER_ID}"\n'
                )
                runtime_payload = render_runtime_config(
                    base_runtime_text, providers[new_name]
                ).encode("utf-8")

                if new_profile.exists():
                    atomic_write_bytes(
                        r_auth,
                        new_profile.read_bytes(),
                        secret=True,
                        mode=SECRET_FILE_MODE,
                    )
                atomic_write_bytes(r_config, runtime_payload)

            rename_recent_provider(st.recent_path(), old_name, new_name)

    action = "would rename" if dry_run else "renamed"
    print(f"{action} provider: {old_name} -> {new_name}")
    return 0
