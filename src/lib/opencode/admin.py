from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import lib.opencode.store as st
from lib.common.common_store import atomic_write_bytes, inspect_file_lock
from lib.common.errors import SwitchError
from lib.common.network import run_models_test as default_run_models_test
from lib.common.platform import run_editor as platform_run_editor


def run_editor(path: Path) -> None:
    mod = (
        sys.modules.get("cli.opencode_provider")
        or sys.modules.get("opencode_provider")
        or sys.modules.get("cli.codex_provider")
        or sys.modules.get("codex_provider")
    )
    if mod and hasattr(mod, "run_editor") and mod.run_editor is not None:
        mod.run_editor(path)
        return
    platform_run_editor(path)


def run_models_test(*args: Any, **kwargs: Any) -> int:
    mod = (
        sys.modules.get("cli.opencode_provider")
        or sys.modules.get("opencode_provider")
        or sys.modules.get("cli.codex_provider")
        or sys.modules.get("codex_provider")
    )
    if mod and hasattr(mod, "run_models_test") and mod.run_models_test is not None:
        return mod.run_models_test(*args, **kwargs)
    return default_run_models_test(*args, **kwargs)


def atomic_write_config(path: Path, before: str, content: str) -> None:
    st.acquire_lock()
    try:
        atomic_write_bytes(path, content.encode("utf-8"))
        try:
            st.read_jsonc(path)
        except SwitchError:
            atomic_write_bytes(path, before.encode("utf-8"))
            raise
    finally:
        st.release_lock()


def show_auth(provider: str | None) -> int:
    auth_file = st.auth_path()
    if not auth_file.exists():
        raise SwitchError(f"auth file not found: {auth_file}")
    try:
        data = json.loads(auth_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SwitchError(f"invalid OpenCode auth JSON: {auth_file}") from exc
    if not isinstance(data, dict):
        raise SwitchError(f"OpenCode auth file must contain an object: {auth_file}")
    if provider is not None and provider not in data:
        raise SwitchError(f"auth entry not found: {provider}")
    print(f"auth file: {auth_file}")
    if provider is not None:
        print(f"provider: {provider}")
    print("fields:")
    entries = {provider: data[provider]} if provider else data
    for name, value in sorted(entries.items()):
        if not isinstance(value, dict):
            print(f"- {name}: invalid ({type(value).__name__})")
            continue
        print(f"- {name}: type={value.get('type', '(missing)')}")
        for key in sorted(value):
            if key != "type":
                print(f"  {key}: configured ({type(value[key]).__name__})")
    return 0


def edit_auth(provider: str | None) -> int:
    auth_file = st.auth_path()
    if provider is not None:
        st.load_auth_keys()
        if provider not in st.load_auth_provider_ids():
            raise SwitchError(f"auth entry not found: {provider}")
    if not auth_file.exists():
        raise SwitchError(f"auth file not found: {auth_file}")
    before = auth_file.read_text(encoding="utf-8")
    run_editor(auth_file)
    try:
        st.load_auth_keys()
    except SwitchError:
        atomic_write_config(auth_file, auth_file.read_text(encoding="utf-8"), before)
        raise
    print(f"edited auth file: {auth_file}")
    return 0


def redact_config(value: Any) -> Any:
    sensitive = {
        "apikey",
        "key",
        "authorization",
        "token",
        "accesstoken",
        "refreshtoken",
        "password",
        "secret",
        "clientsecret",
    }
    if isinstance(value, dict):
        return {
            name: (
                "[REDACTED]"
                if re.sub(r"[^a-z0-9]", "", name.lower()) in sensitive
                else redact_config(item)
            )
            for name, item in value.items()
        }
    if isinstance(value, list):
        return [redact_config(item) for item in value]
    return value


def show_config(provider: str | None) -> int:
    state = st.load_state()
    target = provider or state.current_provider
    if not target:
        raise SwitchError("no current provider; pass a provider name")
    if target not in state.providers:
        raise SwitchError(f"unknown provider '{target}'")
    print(f"global config: {state.path}")
    targets = {target: state.providers[target]}
    print(json.dumps(redact_config(targets), ensure_ascii=False, indent=2))
    return 0


def edit_config(provider: str | None) -> int:
    if provider is not None:
        state = st.load_state()
        if provider not in state.providers:
            raise SwitchError(f"unknown provider '{provider}'")
    state = st.load_state()
    before = state.text
    auth_target = provider or state.current_provider
    auth_command = (
        f"opencode-provider auth edit {auth_target}"
        if auth_target
        else "opencode-provider auth edit <provider>"
    )
    print(f"API key: use '{auth_command}'")
    run_editor(state.path)
    try:
        st.load_state()
    except SwitchError:
        atomic_write_config(state.path, state.path.read_text(encoding="utf-8"), before)
        raise
    print(f"edited global config: {state.path}")
    return 0


def doctor_command(fix: bool) -> int:
    issues = []
    lock = inspect_file_lock(st.lock_path())
    print(
        f"state lock: {lock.state}"
        + (f" (pid {lock.pid})" if lock.pid is not None else "")
    )
    try:
        state = st.load_state()
        print(f"global config: {state.path}")
        print(f"providers: {len(state.providers)}")
        for provider in sorted(state.providers):
            try:
                count = len(st.provider_models(state, provider))
            except SwitchError as exc:
                issues.append(str(exc))
                continue
            print(f"- {provider}: models={count}")
    except SwitchError as exc:
        issues.append(str(exc))
    try:
        st.load_auth_provider_ids()
    except SwitchError as exc:
        issues.append(str(exc))
    if issues:
        print("doctor result: issues found")
        for issue in issues:
            print(f"- {issue}")
        return 1
    if fix:
        print("doctor fix: no repairs needed")
    print("doctor result: ok")
    return 0


def test_provider(provider: str | None, timeout: float) -> int:
    state = st.load_state()
    target = provider or state.current_provider
    if not target:
        raise SwitchError("no current provider; pass a provider name")
    config = state.providers.get(target)
    if config is None:
        raise SwitchError(f"unknown provider '{target}'")
    options = config.get("options", {})
    base_url = options.get("baseURL") if isinstance(options, dict) else None
    if not isinstance(base_url, str):
        raise SwitchError(f"provider '{target}' has no options.baseURL configured")
    auth_keys = st.load_auth_keys().get(target, [])
    api_key = auth_keys[0] if auth_keys else ""
    anthropic = config.get("npm") == "@ai-sdk/anthropic"
    return run_models_test(
        target,
        base_url,
        api_key,
        timeout,
        state.current_provider,
        anthropic=anthropic,
    )


def test_direct(base_url: str, api_key: str, timeout: float) -> int:
    return run_models_test(
        base_url, base_url, api_key, timeout, st.load_state().current_provider
    )
