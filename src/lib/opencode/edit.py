from __future__ import annotations

import json
import re
from contextlib import nullcontext
from urllib.parse import urlparse

import lib.opencode.store as st
from lib.common.common_store import (
    atomic_write_bytes,
    defer_directory_sync,
    mark_directory_dirty,
)
from lib.common.constants import SECRET_FILE_MODE
from lib.common.errors import SwitchError
from lib.common.network import normalize_base_url
from lib.common.recent import (
    forget_recent_provider,
    record_recent_provider,
    rename_recent_provider,
)
from lib.opencode.admin import atomic_write_config
from lib.opencode.patch import (
    patch_add_provider,
    patch_default_model,
    patch_delete_provider,
    patch_rename_provider,
)


def derive_provider_name(base_url: str) -> str:
    hostname = urlparse(base_url).hostname
    if not hostname:
        raise SwitchError("unable to derive provider name from base_url")
    name = re.sub(r"[^A-Za-z0-9_-]+", "-", hostname.split(".")[0]).strip("-_")
    if not name:
        raise SwitchError("unable to derive provider name from base_url")
    return name.lower()


def add_provider(
    base_url: str,
    api_key: str,
    provider: str | None,
    display_name: str | None,
    wire_api: str,
    dry_run: bool,
) -> int:
    base_url = normalize_base_url(base_url)
    if not base_url.endswith("/v1"):
        base_url = f"{base_url}/v1"
    provider = provider or derive_provider_name(base_url)
    if not st.PROVIDER_PATTERN.fullmatch(provider):
        raise SwitchError(f"invalid provider ID: {provider}")

    options = {"baseURL": base_url}
    provider_config = {
        "name": display_name or provider,
        "npm": "@ai-sdk/openai",
        "options": options,
        "models": {},
    }
    auth_entry = {"type": "api", "key": api_key}

    lock = nullcontext() if dry_run else st.lock_mgr
    with lock:
        state = st.load_state()
        auth_file = st.auth_path()
        auth_text = (
            auth_file.read_text(encoding="utf-8") if auth_file.exists() else "{}"
        )
        try:
            auth_data = json.loads(auth_text)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SwitchError(f"invalid OpenCode auth JSON: {auth_file}") from exc
        if not isinstance(auth_data, dict):
            raise SwitchError(f"OpenCode auth file must contain an object: {auth_file}")

        auth_exists = provider in auth_data
        updated_config = patch_add_provider(state.text, provider, provider_config)
        auth_data[provider] = auth_entry
        updated_auth = json.dumps(auth_data, ensure_ascii=False, indent=2) + "\n"

        if not dry_run:
            with defer_directory_sync():
                atomic_write_config(state.path, state.text, updated_config)
                try:
                    st.data_dir().mkdir(parents=True, exist_ok=True)
                    atomic_write_bytes(
                        auth_file,
                        updated_auth.encode("utf-8"),
                        secret=True,
                        mode=SECRET_FILE_MODE,
                    )
                    mark_directory_dirty(auth_file.parent)
                except (OSError, SwitchError):
                    atomic_write_config(state.path, updated_config, state.text)
                    raise
                record_recent_provider(st.recent_path(), provider)

    action = "would add" if dry_run else "added"
    auth_action = "replaced auth entry" if auth_exists else "created auth entry"
    print(f"{action} provider: {provider}")
    print(f"base_url: {base_url}")
    print(f"auth file: {auth_file}")
    print(f"{auth_action}: {provider}")
    print(f"models: none; run 'opencode-provider models sync {provider}'")
    return 0


def delete_provider(provider: str, delete_auth: bool, dry_run: bool) -> int:
    lock = nullcontext() if dry_run else st.lock_mgr
    with lock:
        state = st.load_state()

        if provider not in state.providers:
            auth_file = st.auth_path()
            if delete_auth and auth_file.exists():
                auth_text = auth_file.read_text(encoding="utf-8")
                try:
                    auth_data = json.loads(auth_text)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise SwitchError(
                        f"invalid OpenCode auth JSON: {auth_file}"
                    ) from exc
                if isinstance(auth_data, dict) and provider in auth_data:
                    del auth_data[provider]
                    updated_auth = (
                        json.dumps(auth_data, ensure_ascii=False, indent=2) + "\n"
                    )
                    if not dry_run:
                        atomic_write_config(auth_file, auth_text, updated_auth)
                    action = "would remove" if dry_run else "removed"
                    print(f"provider not found: {provider}")
                    print(f"{action} auth entry: {provider}")
                    return 0
            raise SwitchError(f"unknown provider '{provider}'")
        if state.current_provider == provider:
            raise SwitchError(f"cannot delete the current provider '{provider}'")

        updated_config = patch_delete_provider(state.text, provider)
        auth_changed = False
        auth_file = st.auth_path()
        auth_text = "{}"
        updated_auth = auth_text

        if delete_auth and auth_file.exists():
            auth_text = auth_file.read_text(encoding="utf-8")
            try:
                auth_data = json.loads(auth_text)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise SwitchError(f"invalid OpenCode auth JSON: {auth_file}") from exc
            if not isinstance(auth_data, dict):
                raise SwitchError(
                    f"OpenCode auth file must contain an object: {auth_file}"
                )
            if provider in auth_data:
                del auth_data[provider]
                auth_changed = True
                updated_auth = (
                    json.dumps(auth_data, ensure_ascii=False, indent=2) + "\n"
                )

        if not dry_run:
            with defer_directory_sync():
                atomic_write_config(state.path, state.text, updated_config)
                if auth_changed:
                    try:
                        atomic_write_config(auth_file, auth_text, updated_auth)
                    except SwitchError:
                        atomic_write_config(state.path, updated_config, state.text)
                        raise
                forget_recent_provider(st.recent_path(), provider)

    action = "would delete" if dry_run else "deleted"
    print(f"{action} provider: {provider}")
    return 0


def rename_provider(old: str, new: str, dry_run: bool) -> int:
    if not st.PROVIDER_PATTERN.fullmatch(new):
        raise SwitchError(f"invalid provider ID: {new}")
    lock = nullcontext() if dry_run else st.lock_mgr
    with lock:
        state = st.load_state()
        if old == new:
            raise SwitchError("old and new provider IDs must differ")
        updated = patch_rename_provider(state.text, old, new)
        if state.data.get("model", "").startswith(old + "/"):
            updated = patch_default_model(
                updated, new + "/" + state.data["model"].split("/", 1)[1]
            )
        st.read_jsonc(state.path)
        auth_file = st.auth_path()
        auth_text = (
            auth_file.read_text(encoding="utf-8") if auth_file.exists() else "{}"
        )
        try:
            auth_data = json.loads(auth_text)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SwitchError(f"invalid OpenCode auth JSON: {auth_file}") from exc
        if not isinstance(auth_data, dict):
            raise SwitchError(f"OpenCode auth file must contain an object: {auth_file}")
        auth_changed = old in auth_data
        if auth_changed:
            if new in auth_data:
                raise SwitchError(f"auth entry already exists: {new}")
            auth_data[new] = auth_data.pop(old)
        updated_auth = json.dumps(auth_data, ensure_ascii=False, indent=2) + "\n"
        if not dry_run:
            with defer_directory_sync():
                atomic_write_config(state.path, state.text, updated)
                if auth_changed:
                    try:
                        atomic_write_config(auth_file, auth_text, updated_auth)
                    except SwitchError:
                        atomic_write_config(state.path, updated, state.text)
                        raise
                rename_recent_provider(st.recent_path(), old, new)
    action = "would rename" if dry_run else "renamed"
    print(f"{action} provider: {old} -> {new}")
    return 0
