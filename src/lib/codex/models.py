from __future__ import annotations

import json
import sys
from contextlib import nullcontext
from pathlib import Path
from typing import Any

import lib.codex.store as st
from lib.codex.backup import create_snapshot
from lib.codex.doctor import load_auth_json
from lib.codex.switch import switch_provider
from lib.common.common_store import FileChange, apply_changes
from lib.common.constants import MODE_OFFICIAL
from lib.common.errors import SwitchError
from lib.common.network import WireProtocol, fetch_provider_models
from lib.common.toml_config import (
    MODEL_CATALOG_FIELD,
    render_tool_config,
    validate_provider_name,
)


def catalogs_dir(*, create: bool = True) -> Path:
    path = st.tool_home() / "catalogs"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def default_catalog_path(provider: str) -> Path:
    return catalogs_dir(create=False) / f"{validate_provider_name(provider)}.json"


def _resolve_target(provider: str | None) -> str:
    state = st.ensure_provider_state(read_only=True)
    target = provider or state.active_provider
    if not target:
        raise SwitchError("no active provider; pass a provider name")
    target = validate_provider_name(target)
    if target not in state.providers:
        raise SwitchError(f"unknown provider '{target}'")
    return target


VALID_UPDATE_FIELDS = (
    "display_name",
    "description",
    "context_window",
    "max_context_window",
    "effective_context_window_percent",
    "auto_compact_token_limit",
    "default_reasoning_level",
    "default_verbosity",
    "default_service_tier",
    "priority",
    "support_verbosity",
    "supports_reasoning_summaries",
    "default_reasoning_summary",
    "supports_parallel_tool_calls",
    "supports_search_tool",
    "prefer_websockets",
    "use_responses_lite",
    "input_modalities",
    "truncation_policy",
    "variants",
)

_VARIANT_EFFORTS = ("low", "medium", "high", "xhigh", "max")

_SCALAR_INT_FIELDS = {
    "context_window",
    "max_context_window",
    "effective_context_window_percent",
    "auto_compact_token_limit",
    "priority",
}

_BOOL_FIELDS = {
    "support_verbosity",
    "supports_reasoning_summaries",
    "supports_parallel_tool_calls",
    "supports_search_tool",
    "prefer_websockets",
    "use_responses_lite",
}

_LIST_STR_FIELDS = {"input_modalities"}

_JSON_FIELDS = {"truncation_policy"}


def _default_variants() -> dict[str, dict[str, str]]:
    return {name: {"reasoningEffort": name} for name in _VARIANT_EFFORTS}


def minimal_catalog_entry(model_id: str) -> dict[str, Any]:
    return {
        "slug": model_id,
        "display_name": model_id,
        "description": f"Synced from provider /models: {model_id}",
        "default_reasoning_level": "max",
        "supported_reasoning_levels": [
            {"effort": "low", "description": "Light reasoning"},
            {"effort": "high", "description": "Enhanced reasoning"},
            {"effort": "max", "description": "Deep reasoning"},
        ],
        "shell_type": "shell_command",
        "visibility": "list",
        "supported_in_api": True,
        "priority": 0,
        "base_instructions": "",
        "supports_reasoning_summaries": True,
        "default_reasoning_summary": "none",
        "support_verbosity": False,
        "apply_patch_tool_type": "freeform",
        "truncation_policy": {"mode": "bytes", "limit": 10000},
        "context_window": 1048576,
        "max_context_window": 1048576,
        "effective_context_window_percent": 95,
        "supports_parallel_tool_calls": True,
        "experimental_supported_tools": [],
        "input_modalities": ["text"],
        "variants": _default_variants(),
    }


def _parse_bool(raw: str, field: str) -> bool:
    normalized = raw.strip().lower()
    if normalized in ("true", "1", "yes"):
        return True
    if normalized in ("false", "0", "no"):
        return False
    raise SwitchError(f"invalid boolean for --set {field}: {raw!r}")


def _parse_update_value(field: str, raw: str) -> Any:
    if field == "variants":
        names = [part.strip() for part in raw.split(",")]
        names = [name for name in names if name]
        if not names:
            raise SwitchError("--set variants requires at least one effort name")
        unknown = [name for name in names if name not in _VARIANT_EFFORTS]
        if unknown:
            raise SwitchError(
                f"unknown variant effort(s) {', '.join(unknown)}; "
                f"available: {', '.join(_VARIANT_EFFORTS)}"
            )
        seen: list[str] = []
        for name in names:
            if name not in seen:
                seen.append(name)
        return {name: {"reasoningEffort": name} for name in seen}
    if field in _BOOL_FIELDS:
        return _parse_bool(raw, field)
    if field in _SCALAR_INT_FIELDS:
        try:
            value = int(raw.strip())
        except ValueError:
            raise SwitchError(f"invalid integer for --set {field}: {raw!r}") from None
        if field == "effective_context_window_percent" and not 1 <= value <= 100:
            raise SwitchError("--set effective_context_window_percent must be 1-100")
        if field != "effective_context_window_percent" and value < 0:
            raise SwitchError(f"--set {field} must be >= 0")
        return value
    if field in _LIST_STR_FIELDS:
        items = [part.strip() for part in raw.split(",")]
        items = [item for item in items if item]
        if not items:
            raise SwitchError(f"--set {field} requires at least one value")
        return items
    if field in _JSON_FIELDS:
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SwitchError(f"invalid JSON for --set {field}: {exc}") from exc
        if not isinstance(value, dict):
            raise SwitchError(f"--set {field} must be a JSON object")
        return value
    return raw


def parse_update_sets(values: list[str] | None) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    for item in values or []:
        field, sep, raw = item.partition("=")
        if not sep or not field:
            raise SwitchError(f"invalid --set value {item!r}; expected FIELD=VALUE")
        if field not in VALID_UPDATE_FIELDS:
            raise SwitchError(
                f"unknown field '{field}'; available: " + ", ".join(VALID_UPDATE_FIELDS)
            )
        if field in updates:
            raise SwitchError(f"duplicate --set field '{field}'")
        updates[field] = _parse_update_value(field, raw)
    return updates


def load_catalog(path: Path) -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SwitchError(f"invalid catalog JSON: {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("models"), list):
        raise SwitchError(f"catalog must contain a models list: {path}")
    entries: dict[str, dict[str, Any]] = {}
    for item in data["models"]:
        if isinstance(item, dict) and isinstance(item.get("slug"), str):
            entries[item["slug"]] = item
    return entries


def render_catalog(entries: dict[str, dict[str, Any]]) -> bytes:
    models = [entries[key] for key in sorted(entries)]
    return (json.dumps({"models": models}, indent=2, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


def catalog_pointer_path(config: dict[str, Any]) -> Path | None:
    value = config.get(MODEL_CATALOG_FIELD)
    if isinstance(value, str) and value.strip():
        return Path(value.strip()).expanduser()
    return None


def _fetch_ids(target: str, config: dict[str, Any]) -> list[str]:
    if config.get("mode") == MODE_OFFICIAL:
        raise SwitchError(
            f"provider '{target}' uses official Codex login; models sync does not apply"
        )
    base_url = config.get("base_url", "")
    if not base_url:
        raise SwitchError(f"provider '{target}' has no base_url configured")
    profile = st.auth_profile_path(target, create=False)
    if not profile.exists():
        raise SwitchError(f"auth profile is missing for provider '{target}': {profile}")
    api_key = load_auth_json(profile).get("OPENAI_API_KEY", "")
    return fetch_provider_models(base_url, api_key, WireProtocol.OPENAI)


def _resolve_catalog_path(
    target: str, config: dict[str, Any], state: st.ProviderState
) -> tuple[Path, bool]:
    pointer = catalog_pointer_path(config)
    if pointer is not None:
        return pointer, pointer.exists()
    default = default_catalog_path(target)
    return default, default.exists()


def sync_provider_models(target: str, dry_run: bool) -> int:
    lock = nullcontext() if dry_run else st.state_lock()
    with lock:
        state = st.ensure_provider_state(read_only=dry_run)
        if target not in state.providers:
            raise SwitchError(f"unknown provider '{target}'")
        config = state.providers[target]
        model_ids = _fetch_ids(target, config)
        catalog_path, catalog_exists = _resolve_catalog_path(target, config, state)
        existing = load_catalog(catalog_path) if catalog_exists else {}
        merged: dict[str, dict[str, Any]] = {}
        added = 0
        for model_id in model_ids:
            if model_id in existing:
                merged[model_id] = existing[model_id]
            else:
                merged[model_id] = minimal_catalog_entry(model_id)
                added += 1
        for model_id, entry in existing.items():
            if model_id not in merged:
                merged[model_id] = entry
        payload = render_catalog(merged)

        if dry_run:
            print(f"would sync models for provider '{target}': {len(model_ids)} models")
            print(f"would add {added} new models to catalog: {catalog_path}")
            return 0

        pointer = catalog_pointer_path(config)
        changes: list[FileChange] = []
        if pointer is None:
            default = default_catalog_path(target)
            providers = dict(state.providers)
            updated_config = dict(providers[target])
            updated_config[MODEL_CATALOG_FIELD] = str(default).replace(
                str(Path.home()), "~"
            )
            providers[target] = updated_config
            base_text = (
                st.tool_config_path().read_text(encoding="utf-8")
                if st.tool_config_path().exists()
                else None
            )
            tool_payload = render_tool_config(
                state.codex_dir,
                providers,
                base_text=base_text,
                active_provider=state.active_provider,
            ).encode("utf-8")
            changes.append(FileChange(st.tool_config_path(), tool_payload, secret=True))
            catalog_path = default
            create_snapshot("models-sync", target, state=state)
        changes.append(FileChange(catalog_path, payload))
        apply_changes(changes)
        if target == state.active_provider:
            switch_provider(target, dry_run=False, snapshot=False)

    print(f"synced models for provider '{target}': {len(model_ids)} models")
    print(f"added {added} new models to catalog: {catalog_path}")
    return 0


def sync_all_models(dry_run: bool = False) -> int:
    state = st.ensure_provider_state(read_only=True)
    if not state.providers:
        raise SwitchError("no providers configured")
    failures = 0
    for target in sorted(state.providers):
        try:
            sync_provider_models(target, dry_run)
        except SwitchError as exc:
            print(f"error: {exc}", file=sys.stderr)
            failures += 1
    return 0 if failures == 0 else 1


def list_provider_models(provider: str | None) -> int:
    target = _resolve_target(provider)
    state = st.ensure_provider_state(read_only=True)
    config = state.providers[target]
    catalog_path, catalog_exists = _resolve_catalog_path(target, config, state)
    models = sorted(load_catalog(catalog_path)) if catalog_exists else []
    print(f"provider: {target}")
    print(f"catalog: {catalog_path}")
    print(f"models ({len(models)}):")
    for model in models:
        print(f"- {model}")
    return 0


def _runtime_model_path(state: st.ProviderState) -> tuple[Path, str, dict[str, Any]]:
    runtime_config = st.runtime_config_path(state.codex_dir)
    if not runtime_config.exists():
        return runtime_config, "", {}
    try:
        data = st.parse_toml(runtime_config)
    except SwitchError as exc:
        raise SwitchError(f"invalid runtime TOML: {runtime_config}: {exc}") from exc
    text = runtime_config.read_text(encoding="utf-8")
    return runtime_config, text, data


def set_provider_model(provider: str | None, model: str, dry_run: bool = False) -> int:
    if not model or not model.strip():
        raise SwitchError("model must not be empty")
    model = model.strip()
    if "/" in model:
        maybe_provider, _, maybe_model = model.partition("/")
        raise SwitchError(
            f"invalid model '{model}'; use a bare model ID "
            f"(did you mean '{maybe_model}' for provider '{maybe_provider}'?)"
        )
    target = _resolve_target(provider)
    lock = nullcontext() if dry_run else st.state_lock()
    with lock:
        state = st.ensure_provider_state(read_only=dry_run)
        config = state.providers[target]
        catalog_path, catalog_exists = _resolve_catalog_path(target, config, state)
        known = sorted(load_catalog(catalog_path)) if catalog_exists else []
        if known and model not in known:
            raise SwitchError(
                f"unknown model '{model}' for provider '{target}', available: "
                + ", ".join(known)
            )
        runtime_config, base_text, _ = _runtime_model_path(state)
        import tomlkit

        try:
            document = tomlkit.parse(base_text) if base_text else tomlkit.document()
        except tomlkit.exceptions.ParseError as exc:
            raise SwitchError(f"invalid runtime TOML: {exc}") from exc
        document["model"] = model
        import tomllib

        rendered = tomlkit.dumps(document)
        try:
            tomllib.loads(rendered)
        except tomllib.TOMLDecodeError as exc:
            raise SwitchError(f"generated runtime TOML is invalid: {exc}") from exc
        if not dry_run:
            create_snapshot("models-set", target, state=state)
            apply_changes([FileChange(runtime_config, rendered.encode("utf-8"))])

    action = "would set" if dry_run else "set"
    print(f"{action} model: {target}/{model}")
    return 0


def _load_target_catalog(target: str) -> tuple[Path, dict[str, dict[str, Any]]]:
    state = st.ensure_provider_state(read_only=True)
    config = state.providers[target]
    catalog_path, catalog_exists = _resolve_catalog_path(target, config, state)
    if not catalog_exists:
        raise SwitchError(
            f"no catalog for provider '{target}'; run cpx models sync {target}"
        )
    return catalog_path, load_catalog(catalog_path)


def update_provider_model(
    provider: str | None,
    model: str,
    updates: dict[str, Any],
    dry_run: bool = False,
) -> int:
    if not model or not model.strip():
        raise SwitchError("model must not be empty")
    model = model.strip()
    if "/" in model:
        maybe_provider, _, maybe_model = model.partition("/")
        raise SwitchError(
            f"invalid model '{model}'; use a bare model ID "
            f"(did you mean '{maybe_model}' for provider '{maybe_provider}'?)"
        )
    if not updates:
        raise SwitchError("nothing to update; pass --set FIELD=VALUE")
    target = _resolve_target(provider)
    lock = nullcontext() if dry_run else st.state_lock()
    with lock:
        state = st.ensure_provider_state(read_only=dry_run)
        if target not in state.providers:
            raise SwitchError(f"unknown provider '{target}'")
        config = state.providers[target]
        catalog_path, catalog_exists = _resolve_catalog_path(target, config, state)
        if not catalog_exists:
            raise SwitchError(
                f"no catalog for provider '{target}'; run cpx models sync {target}"
            )
        entries = load_catalog(catalog_path)
        if model not in entries:
            raise SwitchError(
                f"unknown model '{model}' for provider '{target}', available: "
                + ", ".join(sorted(entries))
            )
        entry = dict(entries[model])
        changes: list[str] = []
        for field, value in updates.items():
            if isinstance(value, str):
                text = value.strip()
                if not text:
                    if field in entry:
                        del entry[field]
                        changes.append(f"remove {field}")
                    else:
                        changes.append(f"{field} remains unset")
                else:
                    entry[field] = text
                    changes.append(f"{field} = {text}")
            else:
                entry[field] = value
                if field == "variants":
                    changes.append(f"variants = {', '.join(sorted(value))}")
                else:
                    changes.append(f"{field} = {json.dumps(value, ensure_ascii=False)}")
        entries[model] = entry
        payload = render_catalog(entries)
        if not dry_run:
            create_snapshot("models-update", target, state=state)
            apply_changes([FileChange(catalog_path, payload)])
    action = "would update" if dry_run else "updated"
    print(f"{action} model: {target}/{model}")
    for change in changes:
        print(f"- {change}")
    return 0


def models_command(
    command: str,
    provider: str | None,
    model: str | None = None,
    dry_run: bool = False,
    all_providers: bool = False,
    update_sets: list[str] | None = None,
) -> int:
    if command == "sync" and all_providers:
        if provider is not None:
            raise SwitchError("--all cannot be combined with a provider")
        return sync_all_models(dry_run)
    if command == "list":
        return list_provider_models(provider)
    if command == "sync":
        return sync_provider_models(_resolve_target(provider), dry_run)
    if command == "set":
        if not model:
            raise SwitchError("models set requires a model ID")
        return set_provider_model(provider, model, dry_run)
    if command == "update":
        if not model:
            raise SwitchError("models update requires a model ID")
        return update_provider_model(
            provider, model, parse_update_sets(update_sets), dry_run
        )
    return 0
