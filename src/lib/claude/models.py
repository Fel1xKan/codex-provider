from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import lib.claude.store as st
from lib.common.common_store import atomic_write_bytes
from lib.common.errors import SwitchError
from lib.common.model_catalog import load_model_catalog, merge_metadata
from lib.common.model_metadata import extract_model_metadata, model_record_map
from lib.common.network import (
    WireProtocol,
    fetch_provider_models,
)


def models_dir(*, create: bool = True) -> Path:
    mod = sys.modules.get("cli.claude_provider") or sys.modules.get("claude_provider")
    if mod and hasattr(mod, "MODELS_DIR"):
        path = mod.MODELS_DIR
    else:
        path = st.tool_home() / "models"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def models_path(provider: str, *, create: bool = False) -> Path:
    return models_dir(create=create) / f"{provider}.json"


def load_provider_models(provider: str) -> list[str]:
    return sorted(load_model_entries(provider))


def load_model_entries(provider: str) -> dict[str, dict[str, Any]]:
    path = models_path(provider)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SwitchError(f"invalid models file: {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("models"), list):
        raise SwitchError(f"models file must contain a models list: {path}")
    entries: dict[str, dict[str, Any]] = {}
    for item in data["models"]:
        if isinstance(item, str):
            entries[item] = {}
        elif isinstance(item, dict) and isinstance(item.get("id"), str):
            entry = {k: v for k, v in item.items() if k != "id"}
            entries[item["id"]] = entry
        else:
            raise SwitchError(f"models file must contain a models list: {path}")
    return entries


def save_provider_models(provider: str, models: list[str]) -> Path:
    return save_model_entries(provider, {m: {} for m in models})


def save_model_entries(provider: str, entries: dict[str, dict[str, Any]]) -> Path:
    path = models_path(provider, create=True)
    items: list[Any] = []
    for model_id in sorted(entries):
        extra = entries[model_id]
        if extra:
            items.append({"id": model_id, **extra})
        else:
            items.append(model_id)
    payload = (
        json.dumps(
            {"provider": provider, "models": items},
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")
    atomic_write_bytes(path, payload)
    return path


def _resolve_target(provider: str | None) -> str:
    state = st.ensure_provider_state(read_only=True)
    target = provider or state.active_provider
    if not target:
        raise SwitchError("no active provider; pass a provider name")
    if target not in state.providers:
        raise SwitchError(f"unknown provider '{target}'")
    return target


def _provider_endpoint(
    config: dict[str, Any],
) -> tuple[str, str]:
    base_url = config.get("base_url", "")
    models_url = config.get("models_url", "")
    if not base_url:
        raise SwitchError("provider has no base_url configured")
    return base_url, models_url


def _provider_api_key(provider: str) -> str:
    profile = st.auth_profile_path(provider, create=False)
    if not profile.exists():
        raise SwitchError(f"auth profile is missing for provider '{provider}'")
    payload = json.loads(profile.read_text(encoding="utf-8"))
    return payload.get("ANTHROPIC_AUTH_TOKEN") or payload.get("ANTHROPIC_API_KEY", "")


VALID_UPDATE_FIELDS = ("name", "limit", "options")


def _remote_metadata(result: Any) -> dict[str, dict[str, Any]]:
    return {
        model_id: extract_model_metadata(record)
        for model_id, record in model_record_map(result).items()
    }


def _catalog_metadata() -> dict[str, dict[str, Any]]:
    result = load_model_catalog(st.tool_home() / "model-catalog-cache.json")
    return result.entries | {
        alias: result.entries[canonical]
        for alias, canonical in result.aliases.items()
        if canonical in result.entries
    }


def _apply_remote_metadata(
    entry: dict[str, Any],
    metadata: dict[str, Any],
    *,
    is_new: bool,
) -> dict[str, Any]:
    next_entry = dict(entry)
    display_name = metadata.get("display_name")
    if display_name and (is_new or "name" not in next_entry):
        next_entry["name"] = display_name

    context_window = metadata.get("context_window")
    max_output_tokens = metadata.get("max_output_tokens")
    if context_window or max_output_tokens:
        raw_limit = next_entry.get("limit")
        limit = dict(raw_limit) if isinstance(raw_limit, dict) else {}
        if context_window and "context" not in limit:
            limit["context"] = context_window
        if max_output_tokens and "output" not in limit:
            limit["output"] = max_output_tokens
        next_entry["limit"] = limit
    return next_entry


def sync_provider_models(provider: str | None, dry_run: bool = False) -> int:
    target = _resolve_target(provider)
    state = st.ensure_provider_state(read_only=True)
    config = state.providers[target]
    base_url, models_url = _provider_endpoint(config)
    api_key = _provider_api_key(target)
    fetched = fetch_provider_models(
        base_url,
        api_key,
        WireProtocol.ANTHROPIC,
        models_url_override=models_url or None,
    )
    models = list(fetched)
    remote_metadata = _remote_metadata(fetched)
    catalog_metadata = _catalog_metadata()
    if not dry_run:
        existing = load_model_entries(target)
        merged = {
            m: _apply_remote_metadata(
                dict(existing.get(m, {})),
                merge_metadata(
                    catalog_metadata.get(m, {}),
                    remote_metadata.get(m, {}),
                ),
                is_new=m not in existing,
            )
            for m in models
        }
        for model_id, extra in existing.items():
            if model_id not in merged:
                merged[model_id] = dict(extra)
        path = save_model_entries(target, merged)
        action = "synced"
        print(f"{action} models for provider '{target}': {len(models)} models")
        print(f"models file: {path}")
    else:
        print(f"would sync models for provider '{target}': {len(models)} models")
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


def list_provider_models(provider: str | None, remote: bool = False) -> int:
    target = _resolve_target(provider)
    state = st.ensure_provider_state(read_only=True)
    config = state.providers[target]
    if remote:
        base_url, models_url = _provider_endpoint(config)
        api_key = _provider_api_key(target)
        models = fetch_provider_models(
            base_url,
            api_key,
            WireProtocol.ANTHROPIC,
            models_url_override=models_url or None,
        )
    else:
        models = load_provider_models(target)
    print(f"provider: {target}")
    print(f"models ({len(models)}):")
    for model in models:
        print(f"- {model}")
    return 0


def set_provider_model(
    provider: str | None,
    model: str,
    dry_run: bool = False,
    context_window: int | None = None,
    max_output_tokens: int | None = None,
) -> int:
    if not model or not model.strip():
        raise SwitchError("model must not be empty")
    model = model.strip()
    target = _resolve_target(provider)
    state = st.ensure_provider_state(read_only=dry_run)
    known = load_provider_models(target)
    if known and model not in known:
        raise SwitchError(
            f"unknown model '{model}' for provider '{target}', available: "
            + ", ".join(known)
        )
    limit_updates = {
        "context": context_window,
        "output": max_output_tokens,
    }
    limit_updates = {
        key: value for key, value in limit_updates.items() if value is not None
    }
    option_names = {"context": "--context-window", "output": "--max-output-tokens"}
    for field, value in limit_updates.items():
        if value <= 0:
            raise SwitchError(f"{option_names[field]} must be > 0")

    entries = load_model_entries(target)
    model_entry = dict(entries.get(model, {}))
    if limit_updates:
        raw_limit = model_entry.get("limit")
        limit = dict(raw_limit) if isinstance(raw_limit, dict) else {}
        limit.update(limit_updates)
        model_entry["limit"] = limit
        entries[model] = model_entry

    providers = dict(state.providers)
    config = dict(providers[target])
    provider_env = dict(config.get("env", {}))
    model_keys = (
        "ANTHROPIC_MODEL",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL",
        "ANTHROPIC_DEFAULT_OPUS_MODEL",
        "ANTHROPIC_DEFAULT_SONNET_MODEL",
        "ANTHROPIC_SUBAGENT_MODEL",
        "CLAUDE_CODE_SUBAGENT_MODEL",
    )
    for key in model_keys:
        provider_env[key] = model
    config["env"] = provider_env
    config["model"] = model
    providers[target] = config

    from lib.claude.edit import _render_tool_payload
    from lib.claude.switch import _render_settings_payload

    tool_payload = _render_tool_payload(
        state.settings_path, providers, state.active_provider
    )
    render_config = dict(config)
    render_config["auth_token"] = _provider_api_key(target)
    settings_payload = _render_settings_payload(state, target, render_config)
    if not dry_run:
        if limit_updates:
            save_model_entries(target, entries)
        atomic_write_bytes(
            st.tool_config_path(),
            tool_payload,
            secret=True,
            mode=0o600,
        )
        atomic_write_bytes(
            st.settings_path(),
            settings_payload,
            secret=True,
        )

    action = "would set" if dry_run else "set"
    print(f"{action} model: {target}/{model}")
    for field, value in limit_updates.items():
        print(f"- limit.{field} = {value}")
    return 0


def _parse_field_value(field: str, raw: str) -> Any:
    if field == "name":
        return raw
    if not raw.strip():
        return {}
    if field in ("limit", "options"):
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
        updates[field] = _parse_field_value(field, raw)
    return updates


def update_provider_model(
    provider: str | None,
    model: str,
    updates: dict[str, Any],
    dry_run: bool = False,
) -> int:
    if not model or not model.strip():
        raise SwitchError("model must not be empty")
    model = model.strip()
    if not updates:
        raise SwitchError("nothing to update; pass --set FIELD=VALUE")
    entries = load_model_entries(_resolve_target(provider))
    target = _resolve_target(provider)
    if model not in entries:
        known = sorted(entries)
        hint = f", available: {', '.join(known)}" if known else ""
        raise SwitchError(f"unknown model '{model}' for provider '{target}'{hint}")
    entry = dict(entries[model])
    changes: list[str] = []
    for field, value in updates.items():
        if field == "name":
            name = value.strip()
            if not name:
                if "name" in entry:
                    del entry["name"]
                    changes.append("remove name")
                else:
                    changes.append("name remains unset")
            else:
                entry["name"] = name
                changes.append(f"name = {name}")
        else:
            if value:
                entry[field] = value
                changes.append(f"{field} = {json.dumps(value, ensure_ascii=False)}")
            elif field in entry:
                del entry[field]
                changes.append(f"remove {field}")
            else:
                changes.append(f"{field} remains unset")
    entries[model] = entry
    if not dry_run:
        save_model_entries(target, entries)
    action = "would update" if dry_run else "updated"
    print(f"{action} model: {target}/{model}")
    for change in changes:
        print(f"- {change}")
    return 0


def models_command(
    command: str,
    provider: str | None,
    model: str | None,
    dry_run: bool,
    all_providers: bool,
    remote: bool,
    update_sets: list[str] | None = None,
    context_window: int | None = None,
    max_output_tokens: int | None = None,
) -> int:
    if command == "sync" and all_providers:
        if provider is not None:
            raise SwitchError("--all cannot be combined with a provider")
        return sync_all_models(dry_run)
    if command == "list":
        return list_provider_models(provider, remote)
    if command == "sync":
        return sync_provider_models(provider, dry_run)
    if command == "set":
        if not model:
            raise SwitchError("models set requires a model ID")
        return set_provider_model(
            provider,
            model,
            dry_run,
            context_window,
            max_output_tokens,
        )
    if command == "update":
        if not model:
            raise SwitchError("models update requires a model ID")
        return update_provider_model(
            provider, model, parse_update_sets(update_sets), dry_run
        )
    return 0
