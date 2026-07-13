#!/usr/bin/env python3

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext, suppress
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from codex_provider_lib import (
    PRIVATE_DIR_MODE,
    SECRET_FILE_MODE,
    VERSION,
    MissingConfigError,
    MissingModelProviderError,
    SwitchError,
)
from codex_provider_lib.constants import PROVIDER_PREFIX
from codex_provider_lib.network import normalize_base_url, run_models_test
from codex_provider_lib.platform import (
    run_editor,
    select_provider_interactive,
)
from codex_provider_lib.toml_config import (
    build_provider_block,
    format_toml_value,
    redact_sensitive_config,
    render_runtime_config,
    render_tool_config,
    validate_provider_config,
    validate_provider_name,
)

if os.name == "nt":
    import msvcrt
else:
    import fcntl


TOOL_HOME = Path.home() / ".codex-provider"
TOOL_CONFIG_PATH = TOOL_HOME / "config.toml"
AUTH_STORE_DIR = TOOL_HOME / "auth"
DEFAULT_CODEX_DIR = Path.home() / ".codex"


@dataclass(frozen=True)
class FileSnapshot:
    exists: bool
    payload: bytes | None
    mode: int | None


@dataclass(frozen=True)
class FileChange:
    path: Path
    payload: bytes | None
    secret: bool = False


_lock_depth = 0
_lock_file: Any = None


def chmod_if_supported(path: Path, mode: int) -> None:
    if os.name != "nt":
        path.chmod(mode)


def ensure_private_dir(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True, mode=PRIVATE_DIR_MODE)
        chmod_if_supported(path, PRIVATE_DIR_MODE)
    except OSError as exc:
        raise SwitchError(f"unable to prepare private directory {path}: {exc}") from exc


def fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    fd = os.open(path, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write_bytes(
    path: Path, payload: bytes, *, secret: bool = False, mode: int | None = None
) -> None:
    ensure_private_dir(path.parent)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(payload)
            tmp.flush()
            os.fsync(tmp.fileno())

        target_mode = SECRET_FILE_MODE if secret else mode
        if target_mode is None and path.exists():
            target_mode = path.stat().st_mode & 0o777
        if target_mode is not None:
            chmod_if_supported(tmp_path, target_mode)

        os.replace(tmp_path, path)
        tmp_path = None
        if secret:
            chmod_if_supported(path, SECRET_FILE_MODE)
        fsync_directory(path.parent)
    except OSError as exc:
        raise SwitchError(f"unable to write {path}: {exc}") from exc
    finally:
        if tmp_path is not None:
            with suppress(OSError):
                tmp_path.unlink(missing_ok=True)


def atomic_write_text(
    path: Path, text: str, *, secret: bool = False, mode: int | None = None
) -> None:
    atomic_write_bytes(path, text.encode("utf-8"), secret=secret, mode=mode)


def snapshot_file(path: Path) -> FileSnapshot:
    try:
        if not path.exists():
            return FileSnapshot(False, None, None)
        return FileSnapshot(True, path.read_bytes(), path.stat().st_mode & 0o777)
    except OSError as exc:
        raise SwitchError(f"unable to snapshot {path}: {exc}") from exc


def restore_snapshot(path: Path, snapshot: FileSnapshot) -> None:
    if snapshot.exists:
        atomic_write_bytes(
            path,
            snapshot.payload or b"",
            mode=snapshot.mode,
            secret=path.name == "auth.json" or path.parent == AUTH_STORE_DIR,
        )
        return
    try:
        path.unlink(missing_ok=True)
        if path.parent.exists():
            fsync_directory(path.parent)
    except OSError as exc:
        raise SwitchError(f"unable to remove {path} during rollback: {exc}") from exc


def commit_file_changes(changes: list[FileChange]) -> None:
    snapshots = {change.path: snapshot_file(change.path) for change in changes}
    applied: list[FileChange] = []
    try:
        for change in changes:
            applied.append(change)
            if change.payload is None:
                change.path.unlink(missing_ok=True)
                if change.path.parent.exists():
                    fsync_directory(change.path.parent)
            else:
                atomic_write_bytes(change.path, change.payload, secret=change.secret)
    except (OSError, SwitchError) as exc:
        rollback_errors = []
        for change in reversed(applied):
            try:
                restore_snapshot(change.path, snapshots[change.path])
            except SwitchError as rollback_exc:
                rollback_errors.append(str(rollback_exc))
        detail = (
            f"; rollback errors: {'; '.join(rollback_errors)}"
            if rollback_errors
            else ""
        )
        raise SwitchError(f"unable to commit state changes: {exc}{detail}") from exc


@contextmanager
def state_lock() -> Iterator[None]:
    global _lock_depth, _lock_file
    if _lock_depth:
        _lock_depth += 1
        try:
            yield
        finally:
            _lock_depth -= 1
        return

    ensure_tool_home()
    lock_path = TOOL_HOME / ".lock"
    lock_file = lock_path.open("a+b")
    try:
        if os.name == "nt":
            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b"0")
                lock_file.flush()
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        else:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        _lock_file = lock_file
        _lock_depth = 1
        yield
    except OSError as exc:
        raise SwitchError(f"unable to lock provider state: {exc}") from exc
    finally:
        if _lock_depth:
            _lock_depth = 0
            try:
                if os.name == "nt":
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        _lock_file = None
        lock_file.close()


def parse_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise MissingConfigError(f"missing config file: {path}")
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise SwitchError(f"invalid TOML: {path}: {exc}") from exc


def ensure_tool_home() -> None:
    ensure_private_dir(TOOL_HOME)
    ensure_private_dir(AUTH_STORE_DIR)


def ensure_tool_config() -> dict[str, Any]:
    ensure_tool_home()
    if TOOL_CONFIG_PATH.exists():
        return read_tool_config()
    payload = (
        "# codex-provider tool config\n"
        f"codex_dir = {format_toml_value(str(DEFAULT_CODEX_DIR))}\n"
    )
    atomic_write_text(TOOL_CONFIG_PATH, payload, mode=SECRET_FILE_MODE)
    return {
        "codex_dir": str(DEFAULT_CODEX_DIR),
    }


def read_tool_config() -> dict[str, Any]:
    return parse_toml(TOOL_CONFIG_PATH)


def get_tool_config(*, create: bool = True) -> dict[str, Any]:
    if TOOL_CONFIG_PATH.exists():
        return read_tool_config()
    if create:
        return ensure_tool_config()
    return {"codex_dir": str(DEFAULT_CODEX_DIR)}


def get_codex_dir(*, create: bool = True) -> Path:
    data = get_tool_config(create=create)
    codex_dir = data.get("codex_dir")
    if not isinstance(codex_dir, str) or not codex_dir:
        raise SwitchError(f"missing codex_dir in {TOOL_CONFIG_PATH}")
    return Path(codex_dir).expanduser()


def runtime_config_path(codex_dir: Path | None = None, *, create: bool = True) -> Path:
    return (codex_dir or get_codex_dir(create=create)) / "config.toml"


def runtime_auth_path(codex_dir: Path | None = None, *, create: bool = True) -> Path:
    return (codex_dir or get_codex_dir(create=create)) / "auth.json"


def auth_store_dir(*, create: bool = True) -> Path:
    if create:
        ensure_tool_home()
    return AUTH_STORE_DIR


def auth_profile_path(provider: str, *, create: bool = True) -> Path:
    provider = validate_provider_name(provider)
    root = auth_store_dir(create=create).resolve()
    path = (root / f"{provider}.json").resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise SwitchError(f"auth profile path escapes auth store: {provider}") from exc
    return path


def derive_provider_name(base_url: str) -> str:
    parsed = urlparse(base_url)
    if not parsed.scheme or not parsed.hostname:
        raise SwitchError(
            "base_url must include scheme and host, for example: https://api.example.com"
        )

    labels = parsed.hostname.split(".")
    while len(labels) > 1 and labels[0].lower() in {"api", "www"}:
        labels = labels[1:]

    name = re.sub(r"[^A-Za-z0-9_-]+", "-", labels[0]).strip("-_").lower()
    if not name:
        raise SwitchError(f"unable to derive provider name from base_url: {base_url}")
    return validate_provider_name(name)


def load_provider_registry(
    *, create: bool = True
) -> tuple[Path, dict[str, dict[str, Any]]]:
    data = get_tool_config(create=create)
    codex_dir_value = data.get("codex_dir")
    if not isinstance(codex_dir_value, str) or not codex_dir_value:
        raise SwitchError(f"missing codex_dir in {TOOL_CONFIG_PATH}")
    codex_dir = Path(codex_dir_value).expanduser()
    providers = data.get("model_providers", {})
    if providers is None:
        providers = {}
    if not isinstance(providers, dict):
        raise SwitchError(f"invalid [model_providers.*] in {TOOL_CONFIG_PATH}")
    normalized: dict[str, dict[str, Any]] = {}
    for provider, config in providers.items():
        provider = validate_provider_name(provider)
        if not isinstance(config, dict):
            raise SwitchError(
                f"invalid provider config for {provider} in {TOOL_CONFIG_PATH}"
            )
        validate_provider_config(provider, config)
        normalized[provider] = dict(config)
    return codex_dir, normalized


def load_runtime_config(
    codex_dir: Path | None = None, *, create: bool = True
) -> tuple[str, dict[str, Any], str]:
    path = runtime_config_path(codex_dir, create=create)
    if not path.exists():
        raise MissingConfigError(f"missing runtime config: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SwitchError(f"unable to read runtime config {path}: {exc}") from exc
    data = parse_toml(path)
    current = data.get("model_provider")
    if not isinstance(current, str) or not current:
        providers = data.get("model_providers", {})
        if not providers:
            raise MissingModelProviderError(
                "top-level model_provider is not initialized in runtime config"
            )
        raise SwitchError(
            "top-level model_provider is missing while runtime provider blocks exist"
        )
    return validate_provider_name(current), data, text


def migrate_provider_registry(
    dry_run: bool = False, codex_dir: Path | None = None
) -> tuple[str, dict[str, dict[str, Any]]]:
    if not dry_run:
        ensure_tool_home()
    codex_dir = codex_dir or get_codex_dir(create=not dry_run)
    current, data, text = load_runtime_config(codex_dir, create=not dry_run)
    providers = data.get("model_providers", {})
    if not isinstance(providers, dict) or not providers:
        raise SwitchError("no [model_providers.*] found in runtime config to migrate")

    normalized: dict[str, dict[str, Any]] = {}
    for provider, config in providers.items():
        provider = validate_provider_name(provider)
        if not isinstance(config, dict):
            raise SwitchError(
                f"invalid provider config for {provider} in runtime config"
            )
        validate_provider_config(provider, config)
        normalized[provider] = dict(config)

    if current not in normalized:
        raise SwitchError(
            f"current provider '{current}' is missing from runtime provider blocks"
        )

    if dry_run:
        return current, normalized

    with state_lock():
        base_text = (
            TOOL_CONFIG_PATH.read_text(encoding="utf-8")
            if TOOL_CONFIG_PATH.exists()
            else None
        )
        tool_payload = render_tool_config(codex_dir, normalized, base_text).encode(
            "utf-8"
        )
        runtime_payload = render_runtime_config(
            text, current, normalized[current]
        ).encode("utf-8")
        commit_file_changes(
            [
                FileChange(TOOL_CONFIG_PATH, tool_payload),
                FileChange(runtime_config_path(codex_dir), runtime_payload),
            ]
        )
    return current, normalized


def ensure_registry_ready(
    *, read_only: bool = False
) -> tuple[str, dict[str, dict[str, Any]]]:
    if not read_only:
        ensure_tool_home()
    codex_dir, providers = load_provider_registry(create=not read_only)
    if providers:
        try:
            current, _, _ = load_runtime_config(codex_dir, create=not read_only)
        except MissingConfigError:
            return "", providers
        if current not in providers:
            raise SwitchError(
                f"current provider '{current}' is missing from {TOOL_CONFIG_PATH}"
            )
        return current, providers

    try:
        current, migrated = migrate_provider_registry(
            dry_run=read_only, codex_dir=codex_dir
        )
    except MissingConfigError:
        return "", {}
    return current, migrated


def add_provider(
    provider: str | None,
    base_url: str,
    api_key: str,
    display_name: str | None,
    wire_api: str,
    supports_websockets: bool | None,
    dry_run: bool,
) -> int:
    base_url = normalize_base_url(base_url)
    provider = (
        validate_provider_name(provider) if provider else derive_provider_name(base_url)
    )
    if not api_key:
        raise SwitchError("api_key must not be empty")

    lock = nullcontext() if dry_run else state_lock()
    with lock:
        current, providers = ensure_registry_ready(read_only=dry_run)
        if provider in providers:
            raise SwitchError(f"provider already exists: {provider}")

        providers = dict(providers)
        providers[provider] = {
            "base_url": base_url,
            "name": display_name or provider,
            "requires_openai_auth": True,
            "wire_api": wire_api,
        }
        if supports_websockets is not None:
            providers[provider]["supports_websockets"] = supports_websockets

        if not dry_run:
            base_text = TOOL_CONFIG_PATH.read_text(encoding="utf-8")
            registry_payload = render_tool_config(
                get_codex_dir(), providers, base_text
            ).encode("utf-8")
            auth_payload = (
                json.dumps({"OPENAI_API_KEY": api_key}, indent=2).encode("utf-8")
                + b"\n"
            )
            commit_file_changes(
                [
                    FileChange(TOOL_CONFIG_PATH, registry_payload),
                    FileChange(auth_profile_path(provider), auth_payload, secret=True),
                ]
            )

    action = "would add" if dry_run else "added"
    print(f"{action} provider: {provider}")
    profile = auth_profile_path(provider, create=not dry_run)
    print(f"{'would create' if dry_run else 'created'} auth profile: {profile}")
    print(f"current provider remains: {current or '(none)'}")
    return 0


def delete_provider(provider: str, delete_auth: bool, dry_run: bool) -> int:
    provider = validate_provider_name(provider)
    lock = nullcontext() if dry_run else state_lock()
    with lock:
        current, providers = ensure_registry_ready(read_only=dry_run)
        profile = auth_profile_path(provider, create=not dry_run)
        if provider not in providers:
            if delete_auth and profile.exists():
                if not dry_run:
                    commit_file_changes([FileChange(profile, None, secret=True)])
                detail = "would remove" if dry_run else "removed"
                print(f"provider not found: {provider}")
                print(f"{detail} auth profile: {profile}")
                return 0
            known = ", ".join(sorted(providers.keys()))
            raise SwitchError(f"unknown provider '{provider}', available: {known}")
        if provider == current:
            raise SwitchError(
                "cannot delete the current active provider; switch away first"
            )

        providers = dict(providers)
        providers.pop(provider)

        if not dry_run:
            base_text = TOOL_CONFIG_PATH.read_text(encoding="utf-8")
            registry_payload = render_tool_config(
                get_codex_dir(), providers, base_text
            ).encode("utf-8")
            changes = [FileChange(TOOL_CONFIG_PATH, registry_payload)]
            if delete_auth and profile.exists():
                changes.append(FileChange(profile, None, secret=True))
            commit_file_changes(changes)

    action = "would delete" if dry_run else "deleted"
    print(f"{action} provider: {provider}")
    if delete_auth:
        detail = "would remove" if dry_run else "removed"
        print(f"{detail} auth profile: {profile}")
    else:
        print(f"kept auth profile: {profile}")
    return 0


def load_auth_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SwitchError(f"auth file not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SwitchError(f"invalid auth JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SwitchError(f"auth JSON must contain an object: {path}")
    return payload


def print_status() -> int:
    current, providers = ensure_registry_ready()
    print(f"tool config: {TOOL_CONFIG_PATH}")
    print(f"runtime config: {runtime_config_path()}")
    print(f"current provider: {current}")
    print(f"runtime auth: {runtime_auth_path()}")
    print("")
    for provider in sorted(providers.keys()):
        marker = "*" if provider == current else " "
        auth_exists = auth_profile_path(provider).exists()
        print(f"{marker} {provider:<16} auth={'yes' if auth_exists else 'no'}")
    return 0


def print_list() -> int:
    current, providers = ensure_registry_ready()
    for provider in sorted(providers.keys()):
        marker = "*" if provider == current else " "
        print(f"{marker} {provider}")
    return 0


def resolve_provider(
    provider: str | None,
) -> tuple[str, dict[str, dict[str, Any]], str]:
    current, providers = ensure_registry_ready()
    target = provider or current
    if target not in providers:
        known = ", ".join(sorted(providers.keys()))
        raise SwitchError(f"unknown provider '{target}', available: {known}")
    return current, providers, target


def auth_target_path(provider: str | None) -> tuple[str | None, Path]:
    if provider is None:
        current, _, _ = load_runtime_config()
        return current, runtime_auth_path()
    provider = validate_provider_name(provider)
    return provider, auth_profile_path(provider)


def show_auth(provider: str | None) -> int:
    target, path = auth_target_path(provider)
    if not path.exists():
        raise SwitchError(f"auth file not found: {path}")

    print(f"auth file: {path}")
    if target is None:
        print("scope: runtime")
    else:
        print(f"provider: {target}")
    print("")

    payload = load_auth_json(path)
    print("fields:")
    for key in sorted(payload):
        value = payload[key]
        state = "configured" if value not in (None, "", [], {}) else "empty"
        print(f"- {key}: {state} ({type(value).__name__})")
    return 0


def edit_auth(provider: str | None) -> int:
    target, path = auth_target_path(provider)
    if not path.exists():
        raise SwitchError(f"auth file not found: {path}")

    print(f"opening {path}")
    if target is None:
        print("scope: runtime")
    else:
        print(f"provider: {target}")
    before = snapshot_file(path)
    run_editor(path)
    try:
        load_auth_json(path)
    except SwitchError:
        restore_snapshot(path, before)
        raise
    chmod_if_supported(path, SECRET_FILE_MODE)
    return 0


def show_provider_config(provider: str | None) -> int:
    current, providers, target = resolve_provider(provider)
    print(f"tool config: {TOOL_CONFIG_PATH}")
    print(f"runtime config: {runtime_config_path()}")
    print(f"current provider: {current}")
    print(f"show provider: {target}")
    print(f"auth profile: {auth_profile_path(target)}")
    print("")
    redacted = redact_sensitive_config(providers[target])
    print(build_provider_block(target, redacted).rstrip("\n"))
    return 0


def edit_provider_config(provider: str | None) -> int:
    _, _, target = resolve_provider(provider)

    print(f"opening {TOOL_CONFIG_PATH}")
    print(f"target provider: {target}")
    before = snapshot_file(TOOL_CONFIG_PATH)
    run_editor(TOOL_CONFIG_PATH)
    try:
        load_provider_registry()
    except SwitchError:
        restore_snapshot(TOOL_CONFIG_PATH, before)
        raise
    return 0


def load_provider_api_key(provider: str) -> str:
    path = auth_profile_path(provider)
    payload = load_auth_json(path)
    api_key = payload.get("OPENAI_API_KEY")
    if not isinstance(api_key, str) or not api_key:
        raise SwitchError(f"OPENAI_API_KEY is missing in auth profile: {path}")
    return api_key


def test_provider(provider: str | None, timeout: float) -> int:
    current, providers, target = resolve_provider(provider)
    config = providers[target]
    base_url = config.get("base_url")
    if not isinstance(base_url, str) or not base_url:
        raise SwitchError(f"base_url is missing for provider: {target}")

    api_key = load_provider_api_key(target)
    return run_models_test(
        target, normalize_base_url(base_url), api_key, timeout, current
    )


def test_direct_base_url(base_url: str, api_key: str, timeout: float) -> int:
    base_url = normalize_base_url(base_url)
    if not api_key:
        raise SwitchError("api_key must not be empty")
    return run_models_test("direct", base_url, api_key, timeout, None)


def looks_like_url(value: str) -> bool:
    parsed = urlparse(value)
    return bool(parsed.scheme and parsed.hostname)


def read_api_key(api_key_stdin: bool, prompt: str = "API key: ") -> str:
    if api_key_stdin:
        api_key = sys.stdin.readline().strip()
    elif sys.stdin.isatty():
        api_key = getpass.getpass(prompt).strip()
    else:
        raise SwitchError("API key input requires a TTY or --api-key-stdin")
    if not api_key:
        raise SwitchError("api_key must not be empty")
    return api_key


def dispatch_test(args: list[str], api_key_stdin: bool, timeout: float) -> int:
    if not args:
        if api_key_stdin:
            raise SwitchError("--api-key-stdin requires a base_url")
        return test_provider(None, timeout)

    if len(args) == 1:
        target = args[0]
        if looks_like_url(target):
            api_key = read_api_key(api_key_stdin)
            return test_direct_base_url(target, api_key, timeout)
        if api_key_stdin:
            raise SwitchError("--api-key-stdin requires a direct base_url")
        return test_provider(target, timeout)

    raise SwitchError(
        "test accepts either [provider] or <base-url>; API keys must not be "
        "passed as command arguments"
    )


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


@contextmanager
def temporary_provider(provider: str) -> Iterator[str]:
    provider = validate_provider_name(provider)
    with state_lock():
        current, providers = ensure_registry_ready()
        if provider not in providers:
            known = ", ".join(sorted(providers))
            raise SwitchError(f"unknown provider '{provider}', available: {known}")
        if provider == current:
            yield provider
            return

        target_auth = auth_profile_path(provider)
        load_auth_json(target_auth)
        runtime_config = runtime_config_path()
        runtime_auth = runtime_auth_path()
        original_config = snapshot_file(runtime_config)
        original_auth = snapshot_file(runtime_auth)
        base_text = (
            original_config.payload.decode("utf-8")
            if original_config.exists and original_config.payload is not None
            else f'model_provider = "{provider}"\n'
        )
        runtime_payload = render_runtime_config(
            base_text, provider, providers[provider]
        ).encode("utf-8")
        commit_file_changes(
            [
                FileChange(runtime_auth, target_auth.read_bytes(), secret=True),
                FileChange(runtime_config, runtime_payload),
            ]
        )
        try:
            print(f"temporarily using provider: {provider}")
            yield provider
        finally:
            commit_file_changes(
                [
                    FileChange(
                        runtime_auth,
                        original_auth.payload if original_auth.exists else None,
                        secret=True,
                    ),
                    FileChange(
                        runtime_config,
                        original_config.payload if original_config.exists else None,
                    ),
                ]
            )
            print(f"restored provider: {current}")


def ping_provider(
    provider: str | None, timeout: float, model: str | None, prompt: str
) -> int:
    if provider is None:
        current, _, _ = load_runtime_config()
        return run_codex_ping(current, timeout, model, prompt)
    with temporary_provider(provider) as current:
        return run_codex_ping(current, timeout, model, prompt)


def archive_legacy_profiles() -> list[tuple[Path, Path]]:
    moved = []
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    for path in list_legacy_profiles():
        target = path.with_name(f"{path.name}.bak.{timestamp}")
        sequence = 1
        while target.exists():
            target = path.with_name(f"{path.name}.bak.{timestamp}.{sequence}")
            sequence += 1
        path.rename(target)
        moved.append((path, target))
    return moved


def list_legacy_profiles() -> list[Path]:
    paths = []
    for path in sorted(get_codex_dir().glob("auth.json.*")):
        if ".bak." in path.name:
            continue
        paths.append(path)
    return paths


def doctor(fix: bool) -> int:
    ensure_tool_home()
    issues = []

    print(f"tool home: {TOOL_HOME}")
    print(f"tool config: {TOOL_CONFIG_PATH}")
    print(f"auth store: {AUTH_STORE_DIR}")
    print(f"codex dir: {get_codex_dir()}")

    if not TOOL_CONFIG_PATH.exists():
        issues.append(f"missing tool config: {TOOL_CONFIG_PATH}")

    current = None
    runtime_data: dict[str, Any] = {}
    providers: dict[str, dict[str, Any]] = {}
    try:
        current, runtime_data, _ = load_runtime_config()
    except SwitchError as exc:
        issues.append(str(exc))

    try:
        _, providers = load_provider_registry()
    except SwitchError as exc:
        issues.append(str(exc))

    if current:
        print(f"current provider: {current}")
        if current not in providers:
            issues.append(f"current provider missing from registry: {current}")
        current_profile = auth_profile_path(current)
        if not current_profile.exists():
            issues.append(
                f"missing auth snapshot for current provider: {current_profile}"
            )

    if providers:
        print("")
        print("providers:")
        for provider in sorted(providers.keys()):
            marker = "*" if provider == current else " "
            profile = auth_profile_path(provider)
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

    runtime_providers = runtime_data.get("model_providers", {})
    if not isinstance(runtime_providers, dict):
        runtime_providers = {}
    if len(runtime_providers) != 1:
        issues.append(
            "runtime config should contain exactly 1 provider block, "
            f"found {len(runtime_providers)}"
        )
    elif current and current not in runtime_providers:
        found = next(iter(runtime_providers))
        issues.append(
            "runtime config provider block mismatch: "
            f"expected {PROVIDER_PREFIX}{current}, found {PROVIDER_PREFIX}{found}"
        )

    runtime_auth = runtime_auth_path()
    if runtime_auth.exists():
        try:
            load_auth_json(runtime_auth)
        except SwitchError as exc:
            issues.append(str(exc))

    permission_fixes: list[tuple[Path, int]] = []
    if os.name != "nt":
        expected_modes = [
            (TOOL_HOME, PRIVATE_DIR_MODE),
            (AUTH_STORE_DIR, PRIVATE_DIR_MODE),
        ]
        expected_modes.extend(
            (auth_profile_path(provider), SECRET_FILE_MODE)
            for provider in providers
            if auth_profile_path(provider).exists()
        )
        if runtime_auth.exists():
            expected_modes.append((runtime_auth, SECRET_FILE_MODE))
        for path, expected_mode in expected_modes:
            actual_mode = path.stat().st_mode & 0o777
            if actual_mode != expected_mode:
                if fix:
                    chmod_if_supported(path, expected_mode)
                    permission_fixes.append((path, expected_mode))
                else:
                    issues.append(
                        f"insecure permissions for {path}: "
                        f"{actual_mode:03o}, expected {expected_mode:03o}"
                    )

    legacy_profiles = list_legacy_profiles()
    moved_legacy_profiles: list[tuple[Path, Path]] = []
    if fix and legacy_profiles:
        with state_lock():
            moved_legacy_profiles = archive_legacy_profiles()
            legacy_profiles = []
    if legacy_profiles:
        issues.append(
            "legacy auth snapshots still exist in ~/.codex: "
            + ", ".join(path.name for path in legacy_profiles)
        )

    print("")
    if moved_legacy_profiles:
        print("doctor fix:")
        for src, dst in moved_legacy_profiles:
            print(f"- moved {src.name} -> {dst.name}")
        print("")
    if permission_fixes:
        print("doctor permissions:")
        for path, mode in permission_fixes:
            print(f"- set {path} to {mode:03o}")
        print("")
    if issues:
        print("doctor result: issues found")
        for issue in issues:
            print(f"- {issue}")
        return 1

    print("doctor result: ok")
    return 0


def prompt_provider_selection() -> str | None:
    current, providers = ensure_registry_ready()
    return select_provider_interactive(current, list(providers.keys()))


def switch_provider(provider: str, dry_run: bool) -> int:
    provider = validate_provider_name(provider)
    lock = nullcontext() if dry_run else state_lock()
    with lock:
        current, providers = ensure_registry_ready(read_only=dry_run)
        if provider not in providers:
            known = ", ".join(sorted(providers.keys()))
            raise SwitchError(f"unknown provider '{provider}', available: {known}")
        if provider == current:
            print(f"already using provider: {provider}")
            return 0

        target_auth = auth_profile_path(provider, create=not dry_run)
        load_auth_json(target_auth)
        codex_dir = get_codex_dir(create=not dry_run)
        runtime_config = runtime_config_path(codex_dir, create=not dry_run)
        runtime_auth = runtime_auth_path(codex_dir, create=not dry_run)
        if runtime_config.exists():
            base_text = runtime_config.read_text(encoding="utf-8")
        else:
            base_text = f'model_provider = "{provider}"\n'
        runtime_payload = render_runtime_config(
            base_text, provider, providers[provider]
        ).encode("utf-8")

        if not dry_run:
            changes = []
            if current and runtime_auth.exists():
                changes.append(
                    FileChange(
                        auth_profile_path(current),
                        runtime_auth.read_bytes(),
                        secret=True,
                    )
                )
            changes.extend(
                [
                    FileChange(runtime_auth, target_auth.read_bytes(), secret=True),
                    FileChange(runtime_config, runtime_payload),
                ]
            )
            commit_file_changes(changes)

    action = "would switch" if dry_run else "switched"
    if current:
        print(f"{action} provider: {current} -> {provider}")
    else:
        print(f"{'would activate' if dry_run else 'activated'} provider: {provider}")
    target_profile = auth_profile_path(provider, create=not dry_run)
    print(
        f"{'would refresh' if dry_run else 'refreshed'} auth.json from {target_profile}"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codex-provider",
        description="Provider registry manager for Codex model_provider and auth.json.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "list", help="List providers from ~/.codex-provider/config.toml"
    )
    subparsers.add_parser(
        "status", help="Show current provider and auth profile availability"
    )
    auth_parser = subparsers.add_parser(
        "auth", help="Inspect or edit runtime/provider auth.json files"
    )
    auth_subparsers = auth_parser.add_subparsers(dest="auth_command", required=True)
    auth_detail_parser = auth_subparsers.add_parser(
        "detail", help="Show auth metadata without printing credential values"
    )
    auth_detail_parser.add_argument(
        "provider",
        nargs="?",
        help="Provider name; defaults to current runtime auth.json",
    )
    auth_edit_parser = auth_subparsers.add_parser(
        "edit",
        help="Open runtime auth.json or a provider auth snapshot in $VISUAL or $EDITOR",
    )
    auth_edit_parser.add_argument(
        "provider",
        nargs="?",
        help="Provider name; defaults to current runtime auth.json",
    )
    config_parser = subparsers.add_parser(
        "config", help="Inspect or edit provider config blocks"
    )
    config_subparsers = config_parser.add_subparsers(
        dest="config_command", required=True
    )
    config_detail_parser = config_subparsers.add_parser(
        "detail", help="Show a provider config block from ~/.codex-provider/config.toml"
    )
    config_detail_parser.add_argument(
        "provider", nargs="?", help="Provider name; defaults to current provider"
    )
    config_edit_parser = config_subparsers.add_parser(
        "edit", help="Open ~/.codex-provider/config.toml in $VISUAL or $EDITOR"
    )
    config_edit_parser.add_argument(
        "provider",
        nargs="?",
        help="Provider name to validate before opening; defaults to current provider",
    )
    doctor_parser = subparsers.add_parser(
        "doctor", help="Create ~/.codex-provider if needed and run basic checks"
    )
    doctor_parser.add_argument(
        "--fix",
        action="store_true",
        help="Archive legacy ~/.codex/auth.json.* files to .bak.<timestamp>",
    )

    switch_parser = subparsers.add_parser(
        "switch", help="Switch current runtime provider"
    )
    switch_parser.add_argument(
        "provider",
        nargs="?",
        help="Provider name from registry; opens interactive picker when omitted",
    )
    switch_parser.add_argument(
        "--dry-run", action="store_true", help="Preview changes without writing files"
    )

    test_parser = subparsers.add_parser(
        "test", help="Test a provider or direct base_url with /models"
    )
    test_parser.add_argument(
        "args",
        nargs="*",
        metavar="provider|base_url",
        help="No args/current provider, provider name, or direct base_url",
    )
    test_parser.add_argument(
        "--api-key-stdin",
        action="store_true",
        help="Read API key from stdin for direct base_url tests",
    )
    test_parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="HTTP timeout in seconds, default: 30",
    )

    ping_parser = subparsers.add_parser(
        "ping",
        aliases=["p"],
        help="Test one provider temporarily with a minimal codex exec",
    )
    ping_parser.add_argument(
        "provider", nargs="?", help="Provider name; defaults to current provider"
    )
    ping_parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="codex exec timeout in seconds, default: 120",
    )
    ping_parser.add_argument("-m", "--model", help="Override model for this ping")
    ping_parser.add_argument(
        "--prompt", default="say hi", help='Prompt for codex exec, default: "say hi"'
    )

    add_parser = subparsers.add_parser(
        "add", help="Add a provider config and auth profile"
    )
    add_parser.add_argument("base_url", help="Provider base_url")
    add_parser.add_argument("legacy_api_key", nargs="?", help=argparse.SUPPRESS)
    add_parser.add_argument(
        "--api-key-stdin",
        action="store_true",
        help="Read API key from stdin instead of a hidden interactive prompt",
    )
    add_parser.add_argument(
        "--provider", help="Provider name; defaults to the base_url domain"
    )
    add_parser.add_argument("--name", help="Display name stored in provider config")
    add_parser.add_argument(
        "--wire-api", default="responses", help="wire_api value, default: responses"
    )
    add_parser.add_argument(
        "--supports-websockets",
        choices=["true", "false"],
        help="Set supports_websockets explicitly",
    )
    add_parser.add_argument(
        "--dry-run", action="store_true", help="Preview changes without writing files"
    )

    delete_parser = subparsers.add_parser(
        "delete", help="Delete a provider config from registry"
    )
    delete_parser.add_argument("provider", help="Provider name to delete")
    delete_parser.add_argument(
        "--full",
        action="store_true",
        help="Also remove ~/.codex-provider/auth/<provider>.json",
    )
    delete_parser.add_argument(
        "--dry-run", action="store_true", help="Preview changes without writing files"
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "list":
            return print_list()
        if args.command == "status":
            return print_status()
        if args.command == "auth":
            if args.auth_command == "detail":
                return show_auth(args.provider)
            if args.auth_command == "edit":
                return edit_auth(args.provider)
        if args.command == "config":
            if args.config_command == "detail":
                return show_provider_config(args.provider)
            if args.config_command == "edit":
                return edit_provider_config(args.provider)
        if args.command == "doctor":
            return doctor(args.fix)
        if args.command == "switch":
            provider = args.provider
            if provider is None:
                provider = prompt_provider_selection()
                if provider is None:
                    print("switch cancelled")
                    return 0
            return switch_provider(provider, args.dry_run)
        if args.command == "test":
            return dispatch_test(args.args, args.api_key_stdin, args.timeout)
        if args.command in {"ping", "p"}:
            return ping_provider(args.provider, args.timeout, args.model, args.prompt)
        if args.command == "add":
            if args.legacy_api_key is not None:
                raise SwitchError(
                    "API keys must not be passed as a command argument; "
                    "use the hidden prompt or --api-key-stdin"
                )
            supports_websockets = None
            if args.supports_websockets is not None:
                supports_websockets = args.supports_websockets == "true"
            api_key = read_api_key(args.api_key_stdin)
            return add_provider(
                provider=args.provider,
                base_url=args.base_url,
                api_key=api_key,
                display_name=args.name,
                wire_api=args.wire_api,
                supports_websockets=supports_websockets,
                dry_run=args.dry_run,
            )
        if args.command == "delete":
            return delete_provider(
                provider=args.provider,
                delete_auth=args.full,
                dry_run=args.dry_run,
            )
    except SwitchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except OSError as exc:
        print(f"error: filesystem or process operation failed: {exc}", file=sys.stderr)
        return 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
