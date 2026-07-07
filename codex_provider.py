#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import tomllib


TOOL_HOME = Path.home() / ".codex-provider"
TOOL_CONFIG_PATH = TOOL_HOME / "config.toml"
AUTH_STORE_DIR = TOOL_HOME / "auth"
DEFAULT_CODEX_DIR = Path.home() / ".codex"
PROVIDER_PREFIX = "model_providers."
PROVIDER_ORDER = [
    "base_url",
    "name",
    "requires_openai_auth",
    "wire_api",
    "supports_websockets",
]


class SwitchError(RuntimeError):
    pass


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
        tmp.write(payload)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = Path(tmp.name)
    if path.exists():
        shutil.copymode(path, tmp_path)
    os.replace(tmp_path, path)


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode())


def parse_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SwitchError(f"missing config file: {path}")
    try:
        return tomllib.loads(path.read_text())
    except Exception as exc:
        raise SwitchError(f"invalid TOML: {path}: {exc}") from exc


def ensure_tool_home() -> None:
    TOOL_HOME.mkdir(parents=True, exist_ok=True)
    AUTH_STORE_DIR.mkdir(parents=True, exist_ok=True)


def ensure_tool_config() -> dict[str, Any]:
    ensure_tool_home()
    if TOOL_CONFIG_PATH.exists():
        return read_tool_config()
    payload = (
        '# codex-provider tool config\n'
        f'codex_dir = "{DEFAULT_CODEX_DIR}"\n'
    )
    atomic_write_text(TOOL_CONFIG_PATH, payload)
    return {
        "codex_dir": str(DEFAULT_CODEX_DIR),
    }


def read_tool_config() -> dict[str, Any]:
    return parse_toml(TOOL_CONFIG_PATH)


def get_tool_config() -> dict[str, Any]:
    if TOOL_CONFIG_PATH.exists():
        return read_tool_config()
    return ensure_tool_config()


def get_codex_dir() -> Path:
    data = get_tool_config()
    codex_dir = data.get("codex_dir")
    if not isinstance(codex_dir, str) or not codex_dir:
        raise SwitchError(f"missing codex_dir in {TOOL_CONFIG_PATH}")
    return Path(codex_dir).expanduser()


def runtime_config_path() -> Path:
    return get_codex_dir() / "config.toml"


def runtime_auth_path() -> Path:
    return get_codex_dir() / "auth.json"


def auth_store_dir() -> Path:
    ensure_tool_home()
    return AUTH_STORE_DIR


def auth_profile_path(provider: str) -> Path:
    return auth_store_dir() / f"{provider}.json"


def validate_provider_name(provider: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", provider):
        raise SwitchError("provider name must match [A-Za-z0-9_-]+")
    return provider


def format_toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, list):
        return "[" + ", ".join(format_toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{key} = {format_toml_value(item)}" for key, item in value.items()) + " }"
    raise SwitchError(f"unsupported TOML value type: {type(value).__name__}")


def section_spans(text: str) -> list[tuple[str, int, int]]:
    matches = list(re.finditer(r"(?m)^\[([^\]]+)\]\s*$", text))
    spans = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        spans.append((match.group(1), match.start(), end))
    return spans


def remove_section(text: str, section_name: str) -> str:
    for name, start, end in section_spans(text):
        if name == section_name:
            prefix = text[:start].rstrip("\n")
            suffix = text[end:].lstrip("\n")
            if prefix and suffix:
                return prefix + "\n\n" + suffix
            if prefix:
                return prefix + "\n"
            return suffix
    return text


def remove_all_provider_sections(text: str) -> str:
    for name, _, _ in reversed(section_spans(text)):
        if name.startswith(PROVIDER_PREFIX):
            text = remove_section(text, name)
    return text.rstrip() + "\n"


def build_provider_block(provider: str, config: dict[str, Any]) -> str:
    lines = [f"[model_providers.{provider}]"]
    seen = set()
    for key in PROVIDER_ORDER:
        if key in config:
            lines.append(f"{key} = {format_toml_value(config[key])}")
            seen.add(key)
    for key in config.keys():
        if key in seen:
            continue
        lines.append(f"{key} = {format_toml_value(config[key])}")
    return "\n".join(lines) + "\n"


def extract_runtime_model_provider(text: str) -> str:
    match = re.search(r'(?m)^model_provider\s*=\s*"([^"\n]+)"\s*$', text)
    if not match:
        raise SwitchError("top-level model_provider is missing in runtime config")
    return match.group(1)


def set_runtime_model_provider(text: str, provider: str) -> str:
    pattern = re.compile(r'(?m)^(model_provider\s*=\s*")([^"\n]+)(")\s*$')
    match = pattern.search(text)
    if not match:
        raise SwitchError("unable to find active top-level model_provider line in runtime config")
    return text[: match.start(2)] + provider + text[match.end(2) :]


def insert_current_provider_block(text: str, provider: str, config: dict[str, Any]) -> str:
    block = build_provider_block(provider, config).rstrip("\n")
    pattern = re.compile(r'(?m)^model_provider\s*=\s*"[^"\n]+"\s*$')
    match = pattern.search(text)
    if not match:
        raise SwitchError("unable to place current provider block in runtime config")
    insert_at = match.end()
    return text[:insert_at] + "\n\n" + block + "\n" + text[insert_at:]


def render_runtime_config(base_text: str, current_provider: str, config: dict[str, Any]) -> str:
    text = set_runtime_model_provider(base_text, current_provider)
    text = remove_all_provider_sections(text)
    text = insert_current_provider_block(text, current_provider, config)
    return text


def render_tool_config(codex_dir: Path, providers: dict[str, dict[str, Any]]) -> str:
    lines = [
        "# codex-provider tool config",
        f"codex_dir = {format_toml_value(str(codex_dir))}",
    ]
    for provider in sorted(providers.keys()):
        lines.append("")
        lines.append(build_provider_block(provider, providers[provider]).rstrip("\n"))
    return "\n".join(lines) + "\n"


def load_provider_registry() -> tuple[Path, dict[str, dict[str, Any]]]:
    data = get_tool_config()
    codex_dir = get_codex_dir()
    providers = data.get("model_providers", {})
    if providers is None:
        providers = {}
    if not isinstance(providers, dict):
        raise SwitchError(f"invalid [model_providers.*] in {TOOL_CONFIG_PATH}")
    normalized: dict[str, dict[str, Any]] = {}
    for provider, config in providers.items():
        if not isinstance(config, dict):
            raise SwitchError(f"invalid provider config for {provider} in {TOOL_CONFIG_PATH}")
        normalized[provider] = dict(config)
    return codex_dir, normalized


def write_provider_registry(codex_dir: Path, providers: dict[str, dict[str, Any]], dry_run: bool) -> None:
    if dry_run:
        return
    atomic_write_text(TOOL_CONFIG_PATH, render_tool_config(codex_dir, providers))


def load_runtime_config() -> tuple[str, dict[str, Any], str]:
    path = runtime_config_path()
    text = path.read_text()
    data = parse_toml(path)
    current = data.get("model_provider")
    if not isinstance(current, str) or not current:
        raise SwitchError("top-level model_provider is missing in runtime config")
    return current, data, text


def sync_runtime_provider(current_provider: str, provider_config: dict[str, Any], dry_run: bool) -> None:
    _, _, text = load_runtime_config()
    updated = render_runtime_config(text, current_provider, provider_config)
    if not dry_run:
        atomic_write_text(runtime_config_path(), updated)


def migrate_provider_registry(dry_run: bool = False) -> tuple[str, dict[str, dict[str, Any]]]:
    ensure_tool_home()
    current, data, text = load_runtime_config()
    providers = data.get("model_providers", {})
    if not isinstance(providers, dict) or not providers:
        raise SwitchError("no [model_providers.*] found in runtime config to migrate")

    normalized: dict[str, dict[str, Any]] = {}
    for provider, config in providers.items():
        if not isinstance(config, dict):
            raise SwitchError(f"invalid provider config for {provider} in runtime config")
        normalized[provider] = dict(config)

    write_provider_registry(get_codex_dir(), normalized, dry_run)
    sync_runtime_provider(current, normalized[current], dry_run)
    return current, normalized


def ensure_registry_ready() -> tuple[str, dict[str, dict[str, Any]]]:
    ensure_tool_home()
    codex_dir, providers = load_provider_registry()
    if providers:
        current, _, _ = load_runtime_config()
        return current, providers

    current, migrated = migrate_provider_registry(dry_run=False)
    return current, migrated


def add_provider(
    provider: str,
    base_url: str,
    display_name: str | None,
    wire_api: str,
    requires_openai_auth: bool,
    supports_websockets: bool | None,
    auth_file: str | None,
    dry_run: bool,
) -> int:
    provider = validate_provider_name(provider)
    current, providers = ensure_registry_ready()
    if provider in providers:
        raise SwitchError(f"provider already exists: {provider}")

    providers = dict(providers)
    providers[provider] = {
        "base_url": base_url,
        "name": display_name or provider,
        "wire_api": wire_api,
    }
    if requires_openai_auth:
        providers[provider]["requires_openai_auth"] = True
    if supports_websockets is not None:
        providers[provider]["supports_websockets"] = supports_websockets

    auth_source = Path(auth_file).expanduser() if auth_file else runtime_auth_path()
    if not auth_source.exists():
        raise SwitchError(f"auth source not found: {auth_source}")

    if not dry_run:
        write_provider_registry(get_codex_dir(), providers, dry_run=False)
        atomic_write_bytes(auth_profile_path(provider), auth_source.read_bytes())

    action = "would add" if dry_run else "added"
    print(f"{action} provider: {provider}")
    print(f"{'would create' if dry_run else 'created'} auth profile: {auth_profile_path(provider)} from {auth_source}")
    print(f"current provider remains: {current}")
    return 0


def delete_provider(provider: str, delete_auth: bool, dry_run: bool) -> int:
    provider = validate_provider_name(provider)
    current, providers = ensure_registry_ready()
    if provider not in providers:
        known = ", ".join(providers.keys())
        raise SwitchError(f"unknown provider '{provider}', available: {known}")
    if provider == current:
        raise SwitchError("cannot delete the current active provider; switch away first")

    providers = dict(providers)
    providers.pop(provider)

    if not dry_run:
        write_provider_registry(get_codex_dir(), providers, dry_run=False)
        if delete_auth and auth_profile_path(provider).exists():
            auth_profile_path(provider).unlink()

    action = "would delete" if dry_run else "deleted"
    print(f"{action} provider: {provider}")
    if delete_auth:
        detail = "would remove" if dry_run else "removed"
        print(f"{detail} auth profile: {auth_profile_path(provider)}")
    else:
        print(f"kept auth profile: {auth_profile_path(provider)}")
    return 0


def save_current_auth(current_provider: str, dry_run: bool) -> None:
    path = runtime_auth_path()
    if not path.exists():
        return
    if not dry_run:
        atomic_write_bytes(auth_profile_path(current_provider), path.read_bytes())


def restore_target_auth(provider: str, dry_run: bool) -> None:
    target = auth_profile_path(provider)
    if not target.exists():
        raise SwitchError(f"missing auth profile: {target}")
    if not dry_run:
        atomic_write_bytes(runtime_auth_path(), target.read_bytes())


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


def archive_legacy_profiles() -> list[tuple[Path, Path]]:
    moved = []
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    for path in list_legacy_profiles():
        target = path.with_name(f"{path.name}.bak.{timestamp}")
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
    providers: dict[str, dict[str, Any]] = {}
    try:
        current, _, runtime_text = load_runtime_config()
    except SwitchError as exc:
        runtime_text = ""
        issues.append(str(exc))

    try:
        _, providers = load_provider_registry()
    except SwitchError as exc:
        issues.append(str(exc))

    if current:
        print(f"current provider: {current}")
        if current not in providers:
            issues.append(f"current provider missing from registry: {current}")
        if not auth_profile_path(current).exists():
            issues.append(f"missing auth snapshot for current provider: {auth_profile_path(current)}")

    if providers:
        print("")
        print("providers:")
        for provider in sorted(providers.keys()):
            marker = "*" if provider == current else " "
            profile = auth_profile_path(provider)
            exists = profile.exists()
            print(f"{marker} {provider:<16} auth={'yes' if exists else 'no'} path={profile}")
            if not exists:
                issues.append(f"missing auth snapshot for provider '{provider}': {profile}")

    provider_sections = [name for name, _, _ in section_spans(runtime_text) if name.startswith(PROVIDER_PREFIX)]
    if len(provider_sections) != 1:
        issues.append(
            f"runtime config should contain exactly 1 provider block, found {len(provider_sections)}"
        )
    elif current and provider_sections[0] != f"{PROVIDER_PREFIX}{current}":
        issues.append(
            f"runtime config provider block mismatch: expected {PROVIDER_PREFIX}{current}, found {provider_sections[0]}"
        )

    legacy_profiles = list_legacy_profiles()
    moved_legacy_profiles: list[tuple[Path, Path]] = []
    if fix and legacy_profiles:
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
    if issues:
        print("doctor result: issues found")
        for issue in issues:
            print(f"- {issue}")
        return 1

    print("doctor result: ok")
    return 0


def switch_provider(provider: str, dry_run: bool) -> int:
    provider = validate_provider_name(provider)
    current, providers = ensure_registry_ready()
    if provider not in providers:
        known = ", ".join(sorted(providers.keys()))
        raise SwitchError(f"unknown provider '{provider}', available: {known}")
    if provider == current:
        print(f"already using provider: {provider}")
        return 0

    save_current_auth(current, dry_run)
    restore_target_auth(provider, dry_run)
    sync_runtime_provider(provider, providers[provider], dry_run)

    action = "would switch" if dry_run else "switched"
    print(f"{action} provider: {current} -> {provider}")
    print(f"{'would refresh' if dry_run else 'refreshed'} auth.json from {auth_profile_path(provider)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codex-provider",
        description="Provider registry manager for Codex model_provider and auth.json.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="List providers from ~/.codex-provider/config.toml")
    subparsers.add_parser("status", help="Show current provider and auth profile availability")
    doctor_parser = subparsers.add_parser("doctor", help="Create ~/.codex-provider if needed and run basic checks")
    doctor_parser.add_argument("--fix", action="store_true", help="Archive legacy ~/.codex/auth.json.* files to .bak.<timestamp>")

    switch_parser = subparsers.add_parser("switch", help="Switch current runtime provider")
    switch_parser.add_argument("provider", help="Provider name from registry")
    switch_parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing files")

    add_parser = subparsers.add_parser("add", help="Add a provider config and auth profile")
    add_parser.add_argument("provider", help="New provider name")
    add_parser.add_argument("--base-url", required=True, help="Provider base_url")
    add_parser.add_argument("--name", help="Display name stored in provider config")
    add_parser.add_argument("--wire-api", default="responses", help="wire_api value, default: responses")
    add_parser.add_argument("--requires-openai-auth", action="store_true", help="Set requires_openai_auth = true")
    add_parser.add_argument("--supports-websockets", choices=["true", "false"], help="Set supports_websockets explicitly")
    add_parser.add_argument("--auth-file", help="Path to auth json source; defaults to current ~/.codex/auth.json")
    add_parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing files")

    delete_parser = subparsers.add_parser("delete", help="Delete a provider config from registry")
    delete_parser.add_argument("provider", help="Provider name to delete")
    delete_parser.add_argument("--full", action="store_true", help="Also remove ~/.codex-provider/auth/<provider>.json")
    delete_parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing files")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "list":
            return print_list()
        if args.command == "status":
            return print_status()
        if args.command == "doctor":
            return doctor(args.fix)
        if args.command == "switch":
            return switch_provider(args.provider, args.dry_run)
        if args.command == "add":
            supports_websockets = None
            if args.supports_websockets is not None:
                supports_websockets = args.supports_websockets == "true"
            return add_provider(
                provider=args.provider,
                base_url=args.base_url,
                display_name=args.name,
                wire_api=args.wire_api,
                requires_openai_auth=args.requires_openai_auth,
                supports_websockets=supports_websockets,
                auth_file=args.auth_file,
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

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
