from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

import tomlkit

from codex_provider_lib.constants import (
    PROVIDER_ORDER,
    RUNTIME_PROVIDER_ID,
    SENSITIVE_KEY_PARTS,
)
from codex_provider_lib.errors import SwitchError
from codex_provider_lib.network import normalize_base_url


def validate_provider_name(provider: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", provider):
        raise SwitchError("provider name must match [A-Za-z0-9_-]+")
    return provider


def validate_provider_config(provider: str, config: dict[str, Any]) -> None:
    base_url = config.get("base_url")
    if not isinstance(base_url, str) or not base_url:
        raise SwitchError(f"base_url is missing for provider: {provider}")
    normalize_base_url(base_url)


def redact_sensitive_config(value: Any, key: str = "") -> Any:
    normalized_key = key.lower().replace("-", "_")
    if any(part in normalized_key for part in SENSITIVE_KEY_PARTS):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            item_key: redact_sensitive_config(item, str(item_key))
            for item_key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive_config(item) for item in value]
    return value


def toml_value(value: Any) -> Any:
    if isinstance(value, dict):
        inline = tomlkit.inline_table()
        for key, item in value.items():
            inline.add(str(key), toml_value(item))
        return inline
    try:
        return tomlkit.item(value)
    except (TypeError, ValueError) as exc:
        raise SwitchError(
            f"unsupported TOML value type: {type(value).__name__}"
        ) from exc


def format_toml_value(value: Any) -> str:
    return toml_value(value).as_string()


def build_provider_table(config: dict[str, Any]) -> Any:
    table = tomlkit.table()
    seen = set()
    for key in PROVIDER_ORDER:
        if key in config:
            table.add(key, toml_value(config[key]))
            seen.add(key)
    for key, value in config.items():
        if key not in seen:
            table.add(key, toml_value(value))
    return table


def build_provider_block(provider: str, config: dict[str, Any]) -> str:
    provider = validate_provider_name(provider)
    document = tomlkit.document()
    providers_table = tomlkit.table()
    providers_table.add(provider, build_provider_table(config))
    document.add("model_providers", providers_table)
    return tomlkit.dumps(document)


def render_runtime_config(base_text: str, config: dict[str, Any]) -> str:
    try:
        document = tomlkit.parse(base_text)
    except tomlkit.exceptions.ParseError as exc:
        raise SwitchError(f"invalid runtime TOML: {exc}") from exc
    document["model_provider"] = RUNTIME_PROVIDER_ID
    if "model_providers" in document:
        del document["model_providers"]
    providers_table = tomlkit.table()
    providers_table.add(RUNTIME_PROVIDER_ID, build_provider_table(config))
    document.add("model_providers", providers_table)
    rendered = tomlkit.dumps(document)
    try:
        tomllib.loads(rendered)
    except tomllib.TOMLDecodeError as exc:
        raise SwitchError(f"generated runtime TOML is invalid: {exc}") from exc
    return rendered


def render_tool_config(
    codex_dir: Path,
    providers: dict[str, dict[str, Any]],
    base_text: str | None = None,
    *,
    active_provider: str | None = None,
) -> str:
    try:
        document = (
            tomlkit.parse(base_text)
            if base_text is not None
            else tomlkit.parse("# codex-provider tool config\n")
        )
    except tomlkit.exceptions.ParseError as exc:
        raise SwitchError(f"invalid tool config TOML: {exc}") from exc

    document["codex_dir"] = str(codex_dir)
    if active_provider is not None:
        if active_provider:
            document["active_provider"] = validate_provider_name(active_provider)
        elif "active_provider" in document:
            del document["active_provider"]
    if "legacy_provider_ids" in document:
        del document["legacy_provider_ids"]
    existing_data = tomllib.loads(tomlkit.dumps(document)).get("model_providers", {})
    existing_table = document.get("model_providers")
    if existing_table is None:
        existing_table = tomlkit.table()
        document.add("model_providers", existing_table)

    for existing_provider in list(existing_table.keys()):
        if existing_provider not in providers:
            del existing_table[existing_provider]

    for provider in sorted(providers):
        provider = validate_provider_name(provider)
        if existing_data.get(provider) == providers[provider]:
            continue
        existing_table[provider] = build_provider_table(providers[provider])

    rendered = tomlkit.dumps(document)
    try:
        tomllib.loads(rendered)
    except tomllib.TOMLDecodeError as exc:
        raise SwitchError(f"generated tool config TOML is invalid: {exc}") from exc
    return rendered
