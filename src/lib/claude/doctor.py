from __future__ import annotations

import json
import os
from typing import Any

import lib.claude.store as st
from lib.common.common_store import inspect_file_lock
from lib.common.constants import SECRET_FILE_MODE
from lib.common.errors import SwitchError
from lib.common.recent import (
    ensure_recent_providers,
    sort_providers_by_recent,
)


def load_auth_json(path: Any) -> dict[str, Any]:
    if not path.exists():
        raise SwitchError(f"auth file not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SwitchError(f"invalid auth JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SwitchError(f"auth JSON must contain an object: {path}")
    return payload


def doctor(fix: bool) -> int:
    issues: list[str] = []
    st.ensure_tool_home()

    print(f"tool home: {st.tool_home()}")
    print(f"tool config: {st.tool_config_path()}")
    print(f"auth store: {st.auth_store_dir()}")
    lock = inspect_file_lock(st.tool_home() / ".lock")
    print(
        f"state lock: {lock.state}"
        + (f" (pid {lock.pid})" if lock.pid is not None else "")
    )
    if not st.tool_config_path().exists():
        issues.append(f"missing tool config: {st.tool_config_path()}")

    if os.name == "posix":
        dirs_to_check = [st.tool_home(), st.auth_store_dir(create=False)]
        for d in dirs_to_check:
            if d.exists() and (d.stat().st_mode & 0o777) != 0o700:
                if fix:
                    d.chmod(0o700)
                else:
                    issues.append(f"insecure permissions on directory: {d}")
        astore = st.auth_store_dir(create=False)
        if astore.exists():
            for pfile in astore.glob("*.json"):
                if (pfile.stat().st_mode & 0o777) != SECRET_FILE_MODE:
                    if fix:
                        pfile.chmod(SECRET_FILE_MODE)
                    else:
                        issues.append(f"insecure permissions on file: {pfile}")

    providers: dict[str, dict[str, Any]] = {}
    active_provider = ""
    try:
        state = st.load_provider_state()
        active_provider = state.active_provider
        providers = state.providers
    except SwitchError as exc:
        issues.append(str(exc))

    if active_provider:
        print(f"current provider: {active_provider}")
        current_profile = st.auth_profile_path(active_provider)
        if not current_profile.exists():
            issues.append(
                f"missing auth snapshot for current provider: {current_profile}"
            )
    elif providers:
        issues.append(f"active_provider is missing from {st.tool_config_path()}")

    if providers:
        print("\nproviders:")
        for provider in sort_providers_by_recent(
            providers, ensure_recent_providers(st.recent_path())
        ):
            marker = "*" if provider == active_provider else " "
            profile = st.auth_profile_path(provider)
            exists = profile.exists()
            auth_state = "yes" if exists else "no"
            print(f"{marker} {provider:<16} auth={auth_state} path={profile}")
            if not exists:
                issues.append(
                    f"missing auth snapshot for provider '{provider}': {profile}"
                )
            else:
                try:
                    load_auth_json(profile)
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
