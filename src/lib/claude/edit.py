from __future__ import annotations

import json
from contextlib import nullcontext
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import lib.claude.store as st
from lib.common.common_store import atomic_write_bytes, defer_directory_sync
from lib.common.constants import SECRET_FILE_MODE
from lib.common.errors import SwitchError
from lib.common.recent import (
    forget_recent_provider,
    rename_recent_provider,
)
from lib.common.toml_config import validate_provider_name


def derive_provider_name(base_url: str) -> str:
    hostname = urlparse(base_url).hostname
    if not hostname:
        raise SwitchError("unable to derive provider name from base_url")
    name = hostname.split(".")[0]
    return validate_provider_name(name.lower())


def _normalize_claude_base_url(url: str) -> str:
    url = url.strip()
    if "://" in url and not url.startswith(("http://", "https://")):
        raise SwitchError(f"invalid scheme: {url}")
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise SwitchError(f"invalid base_url scheme/host: {url}")
    if parsed.username or parsed.password:
        raise SwitchError("base_url must not contain credentials")
    if parsed.query or parsed.fragment:
        raise SwitchError("base_url must not contain query parameters or fragments")
    return url.rstrip("/")


def _render_tool_payload(
    settings_path: Path,
    providers: dict[str, dict[str, Any]],
    active_provider: str,
) -> bytes:
    return (
        json.dumps(
            {
                "settings_path": str(settings_path),
                "active_provider": active_provider,
                "providers": providers,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")


def add_provider(
    provider: str | None,
    base_url: str,
    api_key: str,
    display_name: str | None,
    model: str | None,
    dry_run: bool,
    from_settings: bool = False,
    env_overrides: list[str] | None = None,
) -> int:
    if from_settings:
        settings_data = st.load_settings_data()
        settings_env = settings_data.get("env")
        if not isinstance(settings_env, dict):
            raise SwitchError(
                "current settings.json has no env object to snapshot; "
                "pass --from-settings only after configuring Claude"
            )
        base_url = settings_env.get("ANTHROPIC_BASE_URL")
        if not isinstance(base_url, str) or not base_url:
            raise SwitchError("current settings.json env is missing ANTHROPIC_BASE_URL")
        api_key = settings_env.get("ANTHROPIC_AUTH_TOKEN") or settings_env.get(
            "ANTHROPIC_API_KEY", ""
        )
        if not api_key:
            raise SwitchError(
                "current settings.json env has no ANTHROPIC_AUTH_TOKEN or "
                "ANTHROPIC_API_KEY"
            )
    elif not base_url:
        raise SwitchError("add requires <base-url> or --from-settings")

    base_url = _normalize_claude_base_url(base_url)
    provider = (
        validate_provider_name(provider) if provider else derive_provider_name(base_url)
    )
    if display_name is not None:
        display_name = display_name.strip()
        if not display_name:
            raise SwitchError("display name must not be empty")
    if model is not None:
        model = model.strip()
        if not model:
            raise SwitchError("model must not be empty")
    if not api_key:
        raise SwitchError("api_key must not be empty")

    parsed_env: dict[str, str] = {}
    if env_overrides:
        for item in env_overrides:
            if "=" not in item:
                raise SwitchError(f"invalid env override (expected KEY=VALUE): {item}")
            key, value = item.split("=", 1)
            key = key.strip()
            if not key:
                raise SwitchError("env override key must not be empty")
            parsed_env[key] = value
    if from_settings:
        parsed_env.setdefault("ANTHROPIC_BASE_URL", base_url)

    lock = nullcontext() if dry_run else st.state_lock()
    with lock:
        state = st.ensure_provider_state(read_only=dry_run)
        current = state.active_provider
        providers = state.providers
        if provider in providers:
            raise SwitchError(f"provider already exists: {provider}")

        providers = dict(providers)
        config: dict[str, Any] = {
            "base_url": base_url,
            "name": display_name if display_name is not None else provider,
        }
        if model:
            config["model"] = model
        if from_settings:
            config["model_overrides"] = settings_data.get("modelOverrides", {})
            if settings_env.get("ANTHROPIC_API_KEY"):
                config["credential_env"] = "ANTHROPIC_API_KEY"
            env_keys = (
                "ANTHROPIC_MODEL",
                "ANTHROPIC_DEFAULT_HAIKU_MODEL",
                "ANTHROPIC_DEFAULT_OPUS_MODEL",
                "ANTHROPIC_DEFAULT_SONNET_MODEL",
                "ANTHROPIC_SUBAGENT_MODEL",
                "CLAUDE_CODE_SUBAGENT_MODEL",
            )
            provider_env: dict[str, str] = {}
            for key in env_keys:
                value = settings_env.get(key)
                if isinstance(value, str) and value:
                    provider_env[key] = value
            parsed_env.update(provider_env)
        if parsed_env:
            config["env"] = parsed_env
        providers[provider] = config

        profile = st.auth_profile_path(provider, create=not dry_run)
        profile_existed = profile.exists()
        credential_key = "ANTHROPIC_AUTH_TOKEN"
        if from_settings and settings_env.get("ANTHROPIC_API_KEY"):
            credential_key = "ANTHROPIC_API_KEY"
        auth_payload = (json.dumps({credential_key: api_key}, indent=2) + "\n").encode(
            "utf-8"
        )
        tool_payload = _render_tool_payload(state.settings_path, providers, current)

        if not dry_run:
            with defer_directory_sync():
                try:
                    atomic_write_bytes(
                        profile,
                        auth_payload,
                        secret=True,
                        mode=SECRET_FILE_MODE,
                    )
                    atomic_write_bytes(
                        st.tool_config_path(),
                        tool_payload,
                        secret=True,
                        mode=SECRET_FILE_MODE,
                    )
                except SwitchError as exc:
                    if not profile_existed:
                        profile.unlink(missing_ok=True)
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


def set_provider_options(
    provider: str | None,
    display_name: str | None,
    model: str | None,
    dry_run: bool,
    models_url: str | None = None,
) -> int:
    if display_name is None and model is None and models_url is None:
        raise SwitchError("nothing to set; pass --name, --model, or --models-url")
    lock = nullcontext() if dry_run else st.state_lock()
    with lock:
        state = st.ensure_provider_state(read_only=dry_run)
        target = provider or state.active_provider
        if not target:
            raise SwitchError("no active provider set")
        target = validate_provider_name(target)
        if target not in state.providers:
            raise SwitchError(f"unknown provider '{target}'")

        providers = dict(state.providers)
        config = dict(providers[target])
        changes: list[str] = []
        if display_name is not None:
            display_name = display_name.strip()
            if not display_name:
                raise SwitchError("display name must not be empty")
            config["name"] = display_name
            changes.append(f"name = {display_name}")
        if model is not None:
            model = model.strip()
            if model:
                config["model"] = model
                changes.append(f"model = {model}")
            elif "model" in config:
                del config["model"]
                changes.append("remove model")
            else:
                changes.append("model remains unset")
        if models_url is not None:
            models_url = models_url.strip()
            if models_url:
                config["models_url"] = models_url
                changes.append(f"models_url = {models_url}")
            elif "models_url" in config:
                del config["models_url"]
                changes.append("remove models_url")
            else:
                changes.append("models_url remains unset")
        providers[target] = config
        tool_payload = _render_tool_payload(
            state.settings_path, providers, state.active_provider
        )
        if not dry_run:
            atomic_write_bytes(
                st.tool_config_path(),
                tool_payload,
                secret=True,
                mode=SECRET_FILE_MODE,
            )

    action = "would set" if dry_run else "set"
    print(f"{action} provider options: {target}")
    for change in changes:
        print(f"- {change}")
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
        tool_payload = _render_tool_payload(state.settings_path, providers, current)
        if not dry_run:
            with defer_directory_sync():
                atomic_write_bytes(
                    st.tool_config_path(),
                    tool_payload,
                    secret=True,
                    mode=SECRET_FILE_MODE,
                )
                if delete_auth:
                    profile.unlink(missing_ok=True)
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
        tool_payload = _render_tool_payload(
            state.settings_path, providers, active_provider
        )

        if not dry_run:
            with defer_directory_sync():
                if old_profile.exists():
                    atomic_write_bytes(
                        new_profile,
                        old_profile.read_bytes(),
                        secret=True,
                        mode=SECRET_FILE_MODE,
                    )
                    old_profile.unlink(missing_ok=True)
                atomic_write_bytes(
                    st.tool_config_path(),
                    tool_payload,
                    secret=True,
                    mode=SECRET_FILE_MODE,
                )
                rename_recent_provider(st.recent_path(), old_name, new_name)

    action = "would rename" if dry_run else "renamed"
    print(f"{action} provider: {old_name} -> {new_name}")
    return 0
