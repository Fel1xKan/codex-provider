from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import lib.codex.store as st
from lib.common.common_store import inspect_file_lock
from lib.common.constants import (
    MODE_OFFICIAL,
    OFFICIAL_MODEL_PROVIDER_ID,
    RUNTIME_PROVIDER_ID,
    SECRET_FILE_MODE,
)
from lib.common.errors import SwitchError
from lib.common.recent import (
    ensure_recent_providers,
    sort_providers_by_recent,
)


def load_auth_json(path: Path) -> dict[str, Any]:
    import json

    if not path.exists():
        raise SwitchError(f"auth file not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SwitchError(f"invalid auth JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SwitchError(f"auth JSON must contain an object: {path}")
    return payload


def run_codex_ping(current: str, timeout: float, model: str | None, prompt: str) -> int:
    if timeout <= 0:
        raise SwitchError("timeout must be greater than 0")
    codex_path = shutil.which("codex")
    if not codex_path:
        raise SwitchError("codex command not found on PATH")

    command = [
        codex_path,
        "exec",
        "--ephemeral",
        "--ignore-rules",
        "--skip-git-repo-check",
        "-C",
        "/tmp",
    ]
    if model:
        command.extend(["-m", model])
    command.append(prompt)

    print(f"ping provider: {current}")
    print(f"timeout: {timeout:g}s")
    sys.stdout.flush()
    try:
        result = subprocess.run(command, stdin=subprocess.DEVNULL, timeout=timeout)
    except subprocess.TimeoutExpired:
        print("ping result: failed")
        print(f"error: codex exec timed out after {timeout:g}s")
        return 1
    except KeyboardInterrupt:
        print("ping result: interrupted")
        raise

    if result.returncode == 0:
        print("ping result: ok")
        return 0

    print("ping result: failed")
    print(f"codex exit code: {result.returncode}")
    return result.returncode


def doctor(fix: bool) -> int:
    st.ensure_tool_home()
    issues = []

    print(f"tool home: {st.tool_home()}")
    print(f"tool config: {st.tool_config_path()}")
    print(f"auth store: {st.auth_store_dir()}")
    print(f"codex dir: {st.get_codex_dir()}")
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

        rauth = st.runtime_auth_path(st.get_codex_dir())
        if rauth.exists() and (rauth.stat().st_mode & 0o777) != SECRET_FILE_MODE:
            if fix:
                rauth.chmod(SECRET_FILE_MODE)
            else:
                issues.append(f"insecure permissions on file: {rauth}")

        astore = st.auth_store_dir(create=False)
        if astore.exists():
            for pfile in astore.glob("*.json"):
                if (pfile.stat().st_mode & 0o777) != SECRET_FILE_MODE:
                    if fix:
                        pfile.chmod(SECRET_FILE_MODE)
                    else:
                        issues.append(f"insecure permissions on file: {pfile}")

    active_provider = ""
    runtime_provider = None
    runtime_data: dict[str, Any] = {}
    providers: dict[str, dict[str, Any]] = {}
    try:
        runtime_provider, runtime_data, _ = st.load_runtime_config()
    except SwitchError as exc:
        issues.append(str(exc))

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

    active_mode = ""
    if active_provider and active_provider in providers:
        active_mode = providers[active_provider].get("mode", "api")

    if runtime_provider:
        print(f"runtime provider: {runtime_provider}")
        expected_provider = (
            OFFICIAL_MODEL_PROVIDER_ID
            if active_mode == MODE_OFFICIAL
            else RUNTIME_PROVIDER_ID
        )
        if active_provider and runtime_provider != expected_provider:
            issues.append(
                "runtime model_provider mismatch: "
                f"expected {expected_provider}, found {runtime_provider}"
            )
    elif active_provider and active_mode == MODE_OFFICIAL:
        issues.append(
            "runtime model_provider missing: "
            f"expected {OFFICIAL_MODEL_PROVIDER_ID}"
        )

    if active_mode == MODE_OFFICIAL:
        runtime_providers = runtime_data.get("model_providers")
        if (
            isinstance(runtime_providers, dict)
            and RUNTIME_PROVIDER_ID in runtime_providers
        ):
            issues.append(
                "official provider isolation mismatch: managed runtime provider "
                f"block '{RUNTIME_PROVIDER_ID}' is still present"
            )

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
