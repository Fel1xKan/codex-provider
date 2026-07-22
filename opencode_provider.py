#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import json5

from codex_provider_lib import VERSION, SwitchError
from codex_provider_lib.cli import (
    add_ping_parser,
    add_test_parser,
)
from codex_provider_lib.cli import (
    dispatch_test as dispatch_common_test,
)
from codex_provider_lib.network import normalize_base_url, run_models_test
from codex_provider_lib.platform import select_provider_interactive

if os.name == "nt":
    import msvcrt
else:
    import fcntl


CONFIG_DIR = (
    Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "opencode"
)
DATA_DIR = (
    Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "opencode"
)
STATE_DIR = (
    Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    / "opencode"
)
AUTH_PATH = DATA_DIR / "auth.json"
MODEL_STATE_PATH = STATE_DIR / "model.json"
LOCK_PATH = STATE_DIR / "opencode-provider.lock"
CONFIG_NAMES = ("opencode.jsonc", "opencode.json", "config.json")
PROVIDER_PATTERN = re.compile(r"^[^/\s]+$")


@dataclass(frozen=True)
class ConfigState:
    path: Path
    text: str
    data: dict[str, Any]
    providers: dict[str, dict[str, Any]]
    current_provider: str | None
    current_model: str | None
    model_source: str


@dataclass(frozen=True)
class Token:
    kind: str
    start: int
    end: int
    text: str


def config_path() -> Path:
    for name in CONFIG_NAMES:
        candidate = CONFIG_DIR / name
        if candidate.is_file():
            return candidate
    raise SwitchError(
        "OpenCode global config not found; expected one of: "
        + ", ".join(str(CONFIG_DIR / name) for name in CONFIG_NAMES)
    )


def read_jsonc(path: Path) -> tuple[str, dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SwitchError(f"unable to read OpenCode config {path}: {exc}") from exc
    try:
        data = json5.loads(text)
    except ValueError as exc:
        raise SwitchError(f"invalid JSON/JSONC in OpenCode config: {path}") from exc
    if not isinstance(data, dict):
        raise SwitchError(f"OpenCode config must contain an object: {path}")
    return text, data


def split_model(value: object, path: Path) -> tuple[str | None, str | None]:
    if value is None:
        return None, None
    if not isinstance(value, str) or "/" not in value:
        raise SwitchError(
            f"invalid model in {path}; expected provider/model, found {value!r}"
        )
    provider, model = value.split("/", 1)
    if not provider or not model:
        raise SwitchError(
            f"invalid model in {path}; expected provider/model, found {value!r}"
        )
    return provider, model


def load_state() -> ConfigState:
    path = config_path()
    text, data = read_jsonc(path)
    raw_providers = data.get("provider", {})
    if raw_providers is None:
        raw_providers = {}
    if not isinstance(raw_providers, dict):
        raise SwitchError(f"provider must contain an object in {path}")

    providers: dict[str, dict[str, Any]] = {}
    for provider, config in raw_providers.items():
        if not isinstance(provider, str) or not PROVIDER_PATTERN.fullmatch(provider):
            raise SwitchError(f"invalid provider ID in {path}: {provider!r}")
        if not isinstance(config, dict):
            raise SwitchError(f"provider '{provider}' must contain an object in {path}")
        models = config.get("models", {})
        if models is not None and not isinstance(models, dict):
            raise SwitchError(
                f"models for provider '{provider}' must contain an object in {path}"
            )
        providers[provider] = config

    current_provider, current_model = split_model(data.get("model"), path)
    model_source = "global config" if current_provider else "OpenCode fallback"
    if current_provider is None:
        current_provider, current_model = recent_configured_model(providers)
        if current_provider:
            model_source = "recent model"
    return ConfigState(
        path,
        text,
        data,
        providers,
        current_provider,
        current_model,
        model_source,
    )


def recent_configured_model(
    providers: dict[str, dict[str, Any]],
) -> tuple[str | None, str | None]:
    try:
        data = json.loads(MODEL_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None, None
    if not isinstance(data, dict) or not isinstance(data.get("recent"), list):
        return None, None
    for item in data["recent"]:
        if not isinstance(item, dict):
            continue
        provider = item.get("providerID")
        model = item.get("modelID")
        if not isinstance(provider, str) or not isinstance(model, str):
            continue
        config = providers.get(provider)
        if not isinstance(config, dict):
            continue
        models = config.get("models")
        if isinstance(models, dict) and model in models:
            return provider, model
    return None, None


def provider_models(state: ConfigState, provider: str) -> dict[str, dict[str, Any]]:
    if provider not in state.providers:
        available = ", ".join(sorted(state.providers)) or "(none)"
        raise SwitchError(f"unknown provider '{provider}', available: {available}")
    raw_models = state.providers[provider].get("models", {}) or {}
    models: dict[str, dict[str, Any]] = {}
    for model, config in raw_models.items():
        if not isinstance(model, str) or not model:
            raise SwitchError(f"invalid model ID for provider '{provider}': {model!r}")
        if not isinstance(config, dict):
            raise SwitchError(f"model '{provider}/{model}' must contain an object")
        models[model] = config
    return models


def load_auth_provider_ids() -> set[str]:
    if not AUTH_PATH.exists():
        return set()
    try:
        data = json.loads(AUTH_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SwitchError(f"invalid OpenCode auth JSON: {AUTH_PATH}") from exc
    if not isinstance(data, dict):
        raise SwitchError(f"OpenCode auth file must contain an object: {AUTH_PATH}")
    return {provider for provider in data if isinstance(provider, str)}


def provider_has_auth(
    provider: str, config: dict[str, Any], auth_provider_ids: set[str]
) -> bool:
    options = config.get("options")
    config_key = options.get("apiKey") if isinstance(options, dict) else None
    return bool(config_key) or provider in auth_provider_ids


def load_auth_keys() -> dict[str, str]:
    if not AUTH_PATH.exists():
        return {}
    try:
        data = json.loads(AUTH_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SwitchError(f"invalid OpenCode auth JSON: {AUTH_PATH}") from exc
    if not isinstance(data, dict):
        raise SwitchError(f"OpenCode auth file must contain an object: {AUTH_PATH}")
    result = {}
    for provider, value in data.items():
        if isinstance(value, dict) and value.get("type") == "api":
            key = value.get("key")
            if isinstance(key, str) and key:
                result[provider] = key
    return result


def provider_api_key(provider: str, config: dict[str, Any]) -> str:
    options = config.get("options")
    configured = options.get("apiKey") if isinstance(options, dict) else None
    if isinstance(configured, str) and configured:
        match = re.fullmatch(r"\{env:([^}]+)\}", configured)
        if match:
            value = os.environ.get(match.group(1))
            if value:
                return value
        elif not configured.startswith("{"):
            return configured
    auth_key = load_auth_keys().get(provider)
    if auth_key:
        return auth_key
    raise SwitchError(
        f"API key is missing for provider '{provider}'; configure options.apiKey "
        "or run OpenCode /connect"
    )


def provider_base_url(provider: str, config: dict[str, Any]) -> str:
    options = config.get("options")
    base_url = options.get("baseURL") if isinstance(options, dict) else None
    if not isinstance(base_url, str) or not base_url:
        raise SwitchError(
            f"options.baseURL is missing for provider '{provider}'; "
            "automatic model discovery requires an OpenAI-compatible endpoint"
        )
    return base_url.rstrip("/")


def fetch_models(provider: str, config: dict[str, Any], timeout: float) -> list[str]:
    if timeout <= 0:
        raise SwitchError("timeout must be greater than 0")
    url = provider_base_url(provider, config) + "/models"
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {provider_api_key(provider, config)}",
            "Accept": "application/json",
            "User-Agent": f"opencode-provider/{VERSION}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(2 * 1024 * 1024 + 1)
    except urllib.error.HTTPError as exc:
        raise SwitchError(
            f"models request failed: HTTP {exc.code} {exc.reason}"
        ) from exc
    except urllib.error.URLError as exc:
        raise SwitchError(f"models request failed: {exc.reason}") from exc
    except TimeoutError as exc:
        raise SwitchError(f"models request timed out after {timeout:g}s") from exc
    if len(body) > 2 * 1024 * 1024:
        raise SwitchError("models response exceeds 2 MiB")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SwitchError(f"models response is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise SwitchError(
            "models response is not OpenAI-compatible: expected data array"
        )
    models = []
    for item in payload["data"]:
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]:
            models.append(item["id"])
    return list(dict.fromkeys(models))


def test_provider(provider: str | None, timeout: float) -> int:
    state = load_state()
    target = provider or state.current_provider
    if not target:
        raise SwitchError("no current provider; pass a provider name")
    if target not in state.providers:
        raise SwitchError(f"unknown provider '{target}'")
    config = state.providers[target]
    return run_models_test(
        target,
        normalize_base_url(provider_base_url(target, config)),
        provider_api_key(target, config),
        timeout,
        state.current_provider,
        program="opencode-provider",
    )


def test_all_providers(timeout: float) -> int:
    state = load_state()
    if not state.providers:
        raise SwitchError("no providers configured")
    results = []
    for index, provider in enumerate(sorted(state.providers)):
        if index:
            print("")
        try:
            result = test_provider(provider, timeout)
        except SwitchError as exc:
            print(f"current provider: {state.current_provider or '(none)'}")
            print(f"test provider: {provider}")
            print("result: failed")
            print(f"error: {exc}")
            result = 1
        results.append((provider, result))
    available = sum(result == 0 for _, result in results)
    print("")
    print("provider test summary:")
    for provider, result in results:
        print(f"- {provider}: {'ok' if result == 0 else 'failed'}")
    print(f"available: {available}/{len(results)}")
    return 0 if available == len(results) else 1


def test_direct_base_url(base_url: str, api_key: str, timeout: float) -> int:
    return run_models_test(
        "direct",
        normalize_base_url(base_url),
        api_key,
        timeout,
        None,
        program="opencode-provider",
    )


def dispatch_test(
    args: list[str], api_key_stdin: bool, timeout: float, test_all: bool = False
) -> int:
    return dispatch_common_test(
        args,
        api_key_stdin,
        timeout,
        test_all,
        test_provider,
        test_all_providers,
        test_direct_base_url,
    )


def run_opencode_ping(provider: str, model: str, timeout: float, prompt: str) -> int:
    if timeout <= 0:
        raise SwitchError("timeout must be greater than 0")
    executable = shutil.which("opencode")
    if not executable:
        raise SwitchError("opencode command not found on PATH")
    command = [executable, "run", "--model", f"{provider}/{model}", prompt]
    print(f"ping provider: {provider}")
    print(f"ping model: {provider}/{model}")
    print(f"timeout: {timeout:g}s")
    sys.stdout.flush()
    try:
        result = subprocess.run(command, stdin=subprocess.DEVNULL, timeout=timeout)
    except subprocess.TimeoutExpired:
        print("ping result: failed")
        print(f"error: opencode run timed out after {timeout:g}s")
        return 1
    except KeyboardInterrupt:
        print("ping result: interrupted")
        raise
    if result.returncode == 0:
        print("ping result: ok")
        return 0
    print("ping result: failed")
    print(f"opencode exit code: {result.returncode}")
    return result.returncode


def ping_provider(
    provider: str | None, timeout: float, model: str | None, prompt: str
) -> int:
    state = load_state()
    target = provider or state.current_provider
    if not target:
        raise SwitchError("no current provider; pass a provider name")
    selected = resolve_model(state, target, model)
    if selected is None:
        raise SwitchError("ping cancelled")
    return run_opencode_ping(target, selected, timeout, prompt)


def provider_is_enabled(state: ConfigState, provider: str) -> bool:
    enabled = state.data.get("enabled_providers")
    disabled = state.data.get("disabled_providers")
    if isinstance(enabled, list) and provider not in enabled:
        return False
    return not isinstance(disabled, list) or provider not in disabled


def print_list() -> int:
    state = load_state()
    auth_provider_ids = load_auth_provider_ids()
    for provider in sorted(state.providers):
        marker = "*" if provider == state.current_provider else " "
        models = provider_models(state, provider)
        auth = provider_has_auth(provider, state.providers[provider], auth_provider_ids)
        enabled = provider_is_enabled(state, provider)
        print(
            f"{marker} {provider:<24} models={len(models):<3} "
            f"auth={'yes' if auth else 'no':<3} enabled={'yes' if enabled else 'no'}"
        )
    return 0


def print_status() -> int:
    state = load_state()
    print(f"global config: {state.path}")
    print(f"auth file: {AUTH_PATH}")
    print(f"default provider: {state.current_provider or '(OpenCode fallback)'}")
    print(f"default model: {state.current_model or '(OpenCode fallback)'}")
    print(f"model source: {state.model_source}")
    print("")
    return print_list()


def select_model_interactive(
    provider: str, models: dict[str, dict[str, Any]]
) -> str | None:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise SwitchError(
            f"provider '{provider}' has multiple models; pass --model with one of: "
            + ", ".join(sorted(models))
        )
    names = sorted(models)
    print(f"Models for {provider}:")
    for index, model in enumerate(names, start=1):
        display_name = models[model].get("name")
        suffix = f" ({display_name})" if isinstance(display_name, str) else ""
        print(f"{index:>2}. {model}{suffix}")
    value = input("Model number (Enter to cancel): ").strip()
    if not value:
        return None
    try:
        index = int(value)
    except ValueError as exc:
        raise SwitchError("model selection must be a number") from exc
    if index < 1 or index > len(names):
        raise SwitchError(f"model selection must be between 1 and {len(names)}")
    return names[index - 1]


def resolve_model(
    state: ConfigState, provider: str, requested: str | None
) -> str | None:
    models = provider_models(state, provider)
    if not models:
        raise SwitchError(
            f"provider '{provider}' has no configured models; run "
            f"opencode-provider models sync {provider}"
        )
    if requested and "/" in requested:
        requested_provider, requested = requested.split("/", 1)
        if requested_provider != provider:
            raise SwitchError(
                f"model provider '{requested_provider}' does not match "
                f"target '{provider}'"
            )
    if requested:
        if requested not in models:
            raise SwitchError(
                f"unknown model '{provider}/{requested}', available: "
                + ", ".join(sorted(models))
            )
        return requested
    if state.current_model in models:
        return state.current_model
    if len(models) == 1:
        return next(iter(models))
    return select_model_interactive(provider, models)


def tokenize_jsonc(text: str) -> list[Token]:
    tokens = []
    index = 0
    while index < len(text):
        char = text[index]
        if char.isspace():
            index += 1
            continue
        if text.startswith("//", index):
            newline = text.find("\n", index + 2)
            index = len(text) if newline < 0 else newline + 1
            continue
        if text.startswith("/*", index):
            end = text.find("*/", index + 2)
            if end < 0:
                raise SwitchError("unterminated block comment in OpenCode config")
            index = end + 2
            continue
        if char in "{}[]:,":
            tokens.append(Token(char, index, index + 1, char))
            index += 1
            continue
        if char in {'"', "'"}:
            start = index
            quote = char
            index += 1
            while index < len(text):
                if text[index] == "\\":
                    index += 2
                    continue
                if text[index] == quote:
                    index += 1
                    tokens.append(Token("string", start, index, text[start:index]))
                    break
                index += 1
            else:
                raise SwitchError("unterminated string in OpenCode config")
            continue
        start = index
        while index < len(text):
            if text[index].isspace() or text[index] in "{}[]:,":
                break
            if text.startswith("//", index) or text.startswith("/*", index):
                break
            index += 1
        tokens.append(Token("value", start, index, text[start:index]))
    return tokens


def patch_default_model(text: str, target: str) -> str:
    tokens = tokenize_jsonc(text)
    if not tokens or tokens[0].kind != "{":
        raise SwitchError("OpenCode config must contain a top-level object")

    depth = 0
    root_close_index = None
    properties: list[tuple[str, int, int]] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.kind in {"{", "["}:
            depth += 1
            index += 1
            continue
        if token.kind in {"}", "]"}:
            if token.kind == "}" and depth == 1:
                root_close_index = index
            depth -= 1
            index += 1
            continue
        if (
            depth == 1
            and token.kind == "string"
            and index + 2 < len(tokens)
            and tokens[index + 1].kind == ":"
        ):
            try:
                key = json5.loads(token.text)
            except ValueError as exc:
                raise SwitchError(f"invalid config property name: {exc}") from exc
            value_token = tokens[index + 2]
            properties.append((key, index, index + 2))
            if key == "model":
                if value_token.kind != "string":
                    raise SwitchError("top-level model must be a string")
                encoded = json.dumps(target, ensure_ascii=False)
                return text[: value_token.start] + encoded + text[value_token.end :]
        index += 1

    if root_close_index is None:
        raise SwitchError("OpenCode config top-level object is not closed")

    close = tokens[root_close_index]
    encoded = json.dumps(target, ensure_ascii=False)
    newline = "\r\n" if "\r\n" in text else "\n"
    close_line = text.rfind("\n", 0, close.start) + 1
    close_indent = text[close_line : close.start]
    if close_indent.strip():
        close_line = close.start
        close_indent = ""
    if properties:
        first_key = tokens[properties[0][1]]
        first_line = text.rfind("\n", 0, first_key.start) + 1
        indent = text[first_line : first_key.start]
        if indent.strip():
            indent = close_indent + "  "
        last_value = tokens[root_close_index - 1]
        trailing_comma = last_value.kind == ","
        if trailing_comma:
            last_value = tokens[root_close_index - 2]
        comma = "" if trailing_comma else ","
        before = text[: last_value.end] + comma + text[last_value.end : close_line]
    else:
        indent = close_indent + "  "
        before = text[:close_line]
    if before and not before.endswith(("\n", "\r")):
        before += newline
    return (
        before
        + f'{indent}"model": {encoded}{newline}{close_indent}'
        + text[close.start :]
    )


def object_matches(tokens: list[Token]) -> dict[int, int]:
    stack: list[int] = []
    matches: dict[int, int] = {}
    for index, token in enumerate(tokens):
        if token.kind == "{":
            stack.append(index)
        elif token.kind == "}" and stack:
            matches[stack.pop()] = index
    return matches


def object_properties(tokens: list[Token], start: int, end: int) -> dict[str, int]:
    return {
        key: value
        for key, (_, value) in object_property_entries(tokens, start, end).items()
    }


def object_property_entries(
    tokens: list[Token], start: int, end: int
) -> dict[str, tuple[int, int]]:
    result = {}
    depth = 0
    for index in range(start + 1, end):
        token = tokens[index]
        if token.kind in {"{", "["}:
            depth += 1
        elif token.kind in {"}", "]"}:
            depth -= 1
        elif (
            depth == 0
            and token.kind == "string"
            and index + 2 < end
            and tokens[index + 1].kind == ":"
        ):
            result[json5.loads(token.text)] = (index, index + 2)
    return result


def patch_delete_provider(text: str, provider: str) -> str:
    tokens = tokenize_jsonc(text)
    matches = object_matches(tokens)
    root_end = matches.get(0)
    if root_end is None:
        raise SwitchError("OpenCode config must contain a top-level object")
    provider_value = object_properties(tokens, 0, root_end).get("provider")
    provider_end = matches.get(provider_value) if provider_value is not None else None
    if provider_value is None or provider_end is None:
        raise SwitchError("provider config must contain an object")
    entries = object_property_entries(tokens, provider_value, provider_end)
    entry = entries.get(provider)
    if entry is None:
        raise SwitchError(f"unknown provider '{provider}'")
    key_index, value_index = entry
    value_end = matches.get(value_index)
    if value_end is None:
        raise SwitchError(f"provider '{provider}' must contain an object")

    start = tokens[key_index].start
    end = tokens[value_end].end
    if value_end + 1 < provider_end and tokens[value_end + 1].kind == ",":
        end = tokens[value_end + 1].end
    elif key_index > provider_value + 1 and tokens[key_index - 1].kind == ",":
        start = tokens[key_index - 1].start
    return text[:start] + text[end:]


def patch_provider_models(text: str, provider: str, model_ids: list[str]) -> str:
    if not model_ids:
        return text
    tokens = tokenize_jsonc(text)
    matches = object_matches(tokens)
    root_end = matches.get(0)
    if root_end is None:
        raise SwitchError("OpenCode config must contain a top-level object")
    root_props = object_properties(tokens, 0, root_end)
    provider_value = root_props.get("provider")
    provider_end = matches.get(provider_value) if provider_value is not None else None
    if provider_value is None or provider_end is None:
        raise SwitchError("provider config must contain an object")
    provider_props = object_properties(tokens, provider_value, provider_end)
    target_value = provider_props.get(provider)
    target_end = matches.get(target_value) if target_value is not None else None
    if target_value is None or target_end is None:
        raise SwitchError(f"provider '{provider}' must contain an object")
    target_props = object_properties(tokens, target_value, target_end)
    models_value = target_props.get("models")
    if models_value is not None:
        models_end = matches.get(models_value)
        if models_end is None:
            raise SwitchError(
                f"models for provider '{provider}' must contain an object"
            )
        existing = object_properties(tokens, models_value, models_end)
        missing = [model for model in model_ids if model not in existing]
        if not missing:
            return text
        close = tokens[models_end]
        line = text.rfind("\n", 0, close.start) + 1
        indent = text[line : close.start] + "  "
        previous = tokens[models_end - 1]
        comma = "" if previous.kind == "," else ","
        additions = "".join(
            f"{indent}{json.dumps(model)}: {{}}"
            f"{',' if index < len(missing) - 1 else ''}\n"
            for index, model in enumerate(missing)
        )
        return (
            text[: close.start].rstrip()
            + comma
            + "\n"
            + additions
            + text[close.start :]
        )

    close = tokens[target_end]
    line = text.rfind("\n", 0, close.start) + 1
    indent = text[line : close.start] + "  "
    previous = tokens[target_end - 1]
    comma = "" if previous.kind == "," else ","
    entries = ",\n".join(f"{indent}{json.dumps(model)}: {{}}" for model in model_ids)
    return (
        text[: close.start].rstrip()
        + comma
        + f'\n{indent}"models": {{\n{entries}\n{text[line : close.start]}}}'
        + text[close.start :]
    )


def sync_provider(provider: str, timeout: float, dry_run: bool) -> int:
    lock = nullcontext() if dry_run else state_lock()
    with lock:
        state = load_state()
        if provider not in state.providers:
            available = ", ".join(sorted(state.providers)) or "(none)"
            raise SwitchError(f"unknown provider '{provider}', available: {available}")
        discovered = fetch_models(provider, state.providers[provider], timeout)
        existing = provider_models(state, provider)
        missing = [model for model in discovered if model not in existing]
        if missing and not dry_run:
            updated = patch_provider_models(state.text, provider, missing)
            read_jsonc_text(state.path, updated)
            atomic_write_config(state.path, state.text, updated)
    print(f"provider: {provider}")
    print(f"discovered models: {len(discovered)}")
    print(f"added models: {len(missing)}")
    for model in missing:
        print(f"- {model}")
    if dry_run:
        print("result: dry-run")
    return 0


def sync_all_providers(timeout: float, dry_run: bool) -> int:
    state = load_state()
    results = []
    for provider in sorted(state.providers):
        try:
            result = sync_provider(provider, timeout, dry_run)
        except SwitchError as exc:
            print(f"provider: {provider}")
            print(f"result: failed: {exc}")
            result = 1
        results.append(result)
        print("")
    return 0 if all(result == 0 for result in results) else 1


def atomic_write_config(path: Path, original: str, updated: str) -> None:
    try:
        if path.read_text(encoding="utf-8") != original:
            raise SwitchError(f"OpenCode config changed while switching: {path}")
        mode = path.stat().st_mode & 0o777
        temp_path: Path | None = None
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temp_path = Path(handle.name)
            handle.write(updated.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        if os.name != "nt":
            temp_path.chmod(mode)
        os.replace(temp_path, path)
        temp_path = None
    except OSError as exc:
        raise SwitchError(f"unable to update OpenCode config {path}: {exc}") from exc
    finally:
        if "temp_path" in locals() and temp_path is not None:
            with suppress(OSError):
                temp_path.unlink(missing_ok=True)


@contextmanager
def state_lock() -> Iterator[None]:
    try:
        LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOCK_PATH.open("a+b") as lock_file:
            if os.name == "nt":
                lock_file.seek(0, os.SEEK_END)
                if lock_file.tell() == 0:
                    lock_file.write(b"0")
                    lock_file.flush()
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
            else:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if os.name == "nt":
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    except OSError as exc:
        raise SwitchError(f"unable to lock OpenCode provider state: {exc}") from exc


def switch_provider(provider: str, requested_model: str | None, dry_run: bool) -> int:
    lock = nullcontext() if dry_run else state_lock()
    with lock:
        state = load_state()
        if provider not in state.providers:
            available = ", ".join(sorted(state.providers)) or "(none)"
            raise SwitchError(f"unknown provider '{provider}', available: {available}")
        if not provider_is_enabled(state, provider):
            raise SwitchError(
                f"provider '{provider}' is excluded by enabled_providers "
                "or disabled_providers"
            )
        model = resolve_model(state, provider, requested_model)
        if model is None:
            print("switch cancelled")
            return 0
        target = f"{provider}/{model}"
        configured_model = state.data.get("model")
        if configured_model == target:
            print(f"already using default model: {target}")
            return 0
        updated = patch_default_model(state.text, target)
        _, validated = read_jsonc_text(state.path, updated)
        if validated.get("model") != target:
            raise SwitchError("updated config did not contain the requested model")
        if not dry_run:
            atomic_write_config(state.path, state.text, updated)

    action = "would switch" if dry_run else "switched"
    effective_model = (
        f"{state.current_provider}/{state.current_model}"
        if state.current_provider and state.current_model
        else "(OpenCode fallback)"
    )
    print(f"{action} default model: {configured_model or effective_model} -> {target}")
    print(f"global config: {state.path}")
    return 0


def delete_provider(provider: str, delete_auth: bool, dry_run: bool) -> int:
    lock = nullcontext() if dry_run else state_lock()
    with lock:
        state = load_state()
        if provider not in state.providers:
            available = ", ".join(sorted(state.providers)) or "(none)"
            raise SwitchError(f"unknown provider '{provider}', available: {available}")
        if provider == state.current_provider:
            raise SwitchError(
                "cannot delete the current provider; switch to another provider first"
            )
        updated = patch_delete_provider(state.text, provider)
        _, validated = read_jsonc_text(state.path, updated)
        providers = validated.get("provider")
        if isinstance(providers, dict) and provider in providers:
            raise SwitchError("updated config still contains the deleted provider")
        if not dry_run:
            atomic_write_config(state.path, state.text, updated)

        auth_removed = False
        if delete_auth and AUTH_PATH.exists():
            try:
                auth_text = AUTH_PATH.read_text(encoding="utf-8")
                auth_data = json.loads(auth_text)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise SwitchError(f"invalid OpenCode auth JSON: {AUTH_PATH}") from exc
            if isinstance(auth_data, dict) and provider in auth_data:
                auth_data.pop(provider)
                auth_removed = True
                if not dry_run:
                    payload = json.dumps(auth_data, ensure_ascii=False, indent=2) + "\n"
                    atomic_write_config(AUTH_PATH, auth_text, payload)

    action = "would delete" if dry_run else "deleted"
    print(f"{action} provider: {provider}")
    if delete_auth:
        auth_action = "would remove" if dry_run else "removed"
        if auth_removed:
            print(f"{auth_action} auth entry: {provider}")
        else:
            print(f"auth entry not found: {provider}")
    else:
        print(f"kept auth entry: {provider}")
    return 0


def read_jsonc_text(path: Path, text: str) -> tuple[str, dict[str, Any]]:
    try:
        data = json5.loads(text)
    except ValueError as exc:
        raise SwitchError(f"updated OpenCode config is invalid: {path}") from exc
    if not isinstance(data, dict):
        raise SwitchError(f"OpenCode config must contain an object: {path}")
    return text, data


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="opencode-provider",
        description="Switch the default provider/model in OpenCode global config.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list", help="List providers from OpenCode global config")
    subparsers.add_parser(
        "status", help="Show the current global default and providers"
    )
    models_parser = subparsers.add_parser(
        "models", help="Discover models from OpenAI-compatible providers"
    )
    models_subparsers = models_parser.add_subparsers(
        dest="models_command", required=True
    )
    models_list = models_subparsers.add_parser(
        "list", help="Fetch and display models without changing config"
    )
    models_list.add_argument("provider", help="Provider ID")
    models_list.add_argument("--timeout", type=float, default=30.0)
    models_sync = models_subparsers.add_parser(
        "sync", help="Fetch and add missing models to global config"
    )
    models_sync.add_argument("provider", nargs="?", help="Provider ID")
    models_sync.add_argument("--all", action="store_true", help="Sync every provider")
    models_sync.add_argument("--timeout", type=float, default=30.0)
    models_sync.add_argument(
        "--dry-run", action="store_true", help="Preview additions without writing"
    )
    add_test_parser(subparsers)
    add_ping_parser(subparsers, "opencode")
    switch_parser = subparsers.add_parser(
        "switch", help="Switch the global default provider/model"
    )
    switch_parser.add_argument(
        "provider",
        nargs="?",
        help="Provider ID; opens an interactive picker when omitted",
    )
    switch_parser.add_argument(
        "-m", "--model", help="Model ID or provider/model; prompts when ambiguous"
    )
    switch_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the config change without writing",
    )
    delete_parser = subparsers.add_parser(
        "delete", help="Delete a provider from OpenCode global config"
    )
    delete_parser.add_argument("provider", help="Provider ID to delete")
    delete_parser.add_argument(
        "--full", action="store_true", help="Also remove the OpenCode auth entry"
    )
    delete_parser.add_argument(
        "--dry-run", action="store_true", help="Preview changes without writing"
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
        if args.command == "test":
            return dispatch_test(args.args, args.api_key_stdin, args.timeout, args.all)
        if args.command in {"ping", "p"}:
            return ping_provider(args.provider, args.timeout, args.model, args.prompt)
        if args.command == "models":
            if args.models_command == "list":
                state = load_state()
                if args.provider not in state.providers:
                    raise SwitchError(f"unknown provider '{args.provider}'")
                models = fetch_models(
                    args.provider, state.providers[args.provider], args.timeout
                )
                print(f"provider: {args.provider}")
                print(f"models: {len(models)}")
                for model in models:
                    print(f"- {model}")
                return 0
            if args.models_command == "sync":
                if args.all and args.provider:
                    raise SwitchError("models sync --all cannot include a provider")
                if args.all:
                    return sync_all_providers(args.timeout, args.dry_run)
                if not args.provider:
                    raise SwitchError("models sync requires a provider or --all")
                return sync_provider(args.provider, args.timeout, args.dry_run)
        if args.command == "switch":
            provider = args.provider
            if provider is None:
                state = load_state()
                provider = select_provider_interactive(
                    state.current_provider or "", list(state.providers)
                )
                if provider is None:
                    print("switch cancelled")
                    return 0
            return switch_provider(provider, args.model, args.dry_run)
        if args.command == "delete":
            return delete_provider(args.provider, args.full, args.dry_run)
    except SwitchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
