from __future__ import annotations

import sys
from typing import Any

import lib.opencode.admin as adm
from lib.common.common_store import FileChange, apply_changes
from lib.common.errors import SwitchError
from lib.common.network import WireProtocol
from lib.common.network import fetch_provider_models as fetch_models
from lib.opencode.patch import patch_default_model, patch_provider_models
from lib.opencode.store import (
    ConfigState,
    load_auth_keys,
    load_state,
    provider_models,
)

# OpenCode accepts provider-specific options in each model variant.  These
# reasoning-effort names are useful for the OpenAI-compatible providers this
# CLI manages, while keeping the config shape compatible with OpenCode's
# built-in variant selector.
DEFAULT_VARIANT_NAMES = ("low", "medium", "high", "xhigh", "max")


def default_model_variants() -> dict[str, dict[str, str]]:
    """Return fresh default variants for a newly discovered model."""
    return {name: {"reasoningEffort": name} for name in DEFAULT_VARIANT_NAMES}


def fetch_provider_models(
    base_url: str, api_key: str, anthropic: bool = False
) -> list[str]:
    protocol = WireProtocol.ANTHROPIC if anthropic else WireProtocol.OPENAI
    return fetch_models(base_url, api_key, protocol)


def add_models_parser(subparsers: Any) -> None:
    models_parser = subparsers.add_parser("models", help="Manage provider models")
    models_sub = models_parser.add_subparsers(dest="models_command", required=True)
    list_p = models_sub.add_parser("list", help="List models for a provider")
    list_p.add_argument("provider", nargs="?", help="Provider name")
    sync_p = models_sub.add_parser("sync", help="Sync models from provider API")
    sync_p.add_argument("provider", nargs="?", help="Provider name")
    sync_p.add_argument("--dry-run", action="store_true", help="Perform a dry run")
    sync_p.add_argument(
        "--force",
        action="store_true",
        help="Refresh default variants for every synced model",
    )
    sync_p.add_argument(
        "--all",
        action="store_true",
        help="Sync models for every configured provider",
    )


VALID_UPDATE_FIELDS = ("name", "limit", "options", "variants")


def _parse_field_value(field: str, raw: str) -> Any:
    if field == "name":
        return raw
    if not raw.strip():
        return {}
    if field in ("limit", "options", "variants"):
        import json

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
    if "/" in model:
        requested_provider, _, requested_model = model.partition("/")
        state = load_state()
        target = provider or state.current_provider
        if requested_provider != target:
            raise SwitchError(
                f"model provider '{requested_provider}' does not match "
                f"target '{target}'"
            )
        model = requested_model
        if not model:
            raise SwitchError("model must not be empty")
    if not updates:
        raise SwitchError("nothing to update; pass --set FIELD=VALUE")
    state = load_state()
    target = provider or state.current_provider
    if not target:
        raise SwitchError("no current provider; pass a provider name")
    if target not in state.providers:
        raise SwitchError(f"unknown provider '{target}'")
    models = provider_models(state, target)
    if model not in models:
        raise SwitchError(
            f"unknown model '{target}/{model}', available: " + ", ".join(sorted(models))
        )
    entry = dict(models[model])
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
        elif field == "variants":
            if value:
                entry["variants"] = value
                changes.append(f"variants = {sorted(value)}")
            elif "variants" in entry:
                del entry["variants"]
                changes.append("remove variants")
            else:
                changes.append("variants remains unset")
        else:
            import json

            if value:
                entry[field] = value
                changes.append(f"{field} = {json.dumps(value, ensure_ascii=False)}")
            elif field in entry:
                del entry[field]
                changes.append(f"remove {field}")
            else:
                changes.append(f"{field} remains unset")
    model_objs = {name: dict(cfg) for name, cfg in models.items()}
    model_objs[model] = entry
    updated = patch_provider_models(state.text, target, model_objs)
    if not dry_run:
        adm.atomic_write_config(state.path, state.text, updated)
    action = "would update" if dry_run else "updated"
    print(f"{action} model: {target}/{model}")
    for change in changes:
        print(f"- {change}")
    return 0


def sync_provider_models(
    state: ConfigState, target: str, dry_run: bool, force: bool = False
) -> int:
    config = state.providers[target]
    options = config.get("options", {})
    base_url = options.get("baseURL") if isinstance(options, dict) else None
    if not isinstance(base_url, str):
        raise SwitchError(f"provider '{target}' has no options.baseURL configured")
    keys = load_auth_keys().get(target, [])
    api_key = keys[0] if keys else ""
    anthropic = config.get("npm") == "@ai-sdk/anthropic"
    models_list = fetch_provider_models(base_url, api_key, anthropic)
    existing_models = provider_models(state, target)
    model_objs: dict[str, dict[str, Any]] = {}
    for m in models_list:
        if m in existing_models and isinstance(existing_models[m], dict):
            model_objs[m] = dict(existing_models[m])
            if force:
                model_objs[m]["variants"] = default_model_variants()
        else:
            model_objs[m] = {"variants": default_model_variants()}
    updated = patch_provider_models(state.text, target, model_objs)

    if not dry_run:
        adm.atomic_write_config(state.path, state.text, updated)

    action = "would sync" if dry_run else "synced"
    print(f"{action} models for provider '{target}': {len(models_list)} models")
    return 0


def sync_all_models(state: ConfigState, dry_run: bool, force: bool = False) -> int:
    failures = 0
    for target in sorted(state.providers):
        try:
            sync_provider_models(load_state(), target, dry_run, force)
        except SwitchError as exc:
            print(f"error: {exc}", file=sys.stderr)
            failures += 1
    return 0 if failures == 0 else 1


def set_provider_model(provider: str | None, model: str, dry_run: bool = False) -> int:
    from lib.common.recent import record_recent_provider
    from lib.opencode.store import recent_path

    if not model or not model.strip():
        raise SwitchError("model must not be empty")
    model = model.strip()
    state = load_state()
    target = provider or state.current_provider
    if not target:
        raise SwitchError("no current provider; pass a provider name")
    if target not in state.providers:
        raise SwitchError(f"unknown provider '{target}'")
    if "/" in model:
        requested_provider, _, requested_model = model.partition("/")
        if requested_provider != target:
            raise SwitchError(
                f"model provider '{requested_provider}' does not match "
                f"target '{target}'"
            )
        model = requested_model
        if not model:
            raise SwitchError("model must not be empty")
    models = provider_models(state, target)
    if not models:
        raise SwitchError(
            f"provider '{target}' has no configured models; run "
            f"opx models sync {target}"
        )
    if model not in models:
        raise SwitchError(
            f"unknown model '{target}/{model}', available: " + ", ".join(sorted(models))
        )
    desired = f"{target}/{model}"
    if state.data.get("model") == desired:
        print(f"already using default model: {desired}")
        return 0
    updated = patch_default_model(state.text, desired)
    if not dry_run:
        apply_changes([FileChange(state.path, updated.encode("utf-8"))])
        record_recent_provider(recent_path(), target)
    action = "would set" if dry_run else "set"
    print(f"{action} model: {desired}")
    return 0


def models_command(
    command: str,
    provider: str | None,
    model: str | None = None,
    dry_run: bool = False,
    all_providers: bool = False,
    force: bool = False,
    update_sets: list[str] | None = None,
) -> int:
    state = load_state()
    if command == "sync" and all_providers:
        if provider is not None:
            raise SwitchError("--all cannot be combined with a provider")
        return sync_all_models(state, dry_run, force)
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
    target = provider or state.current_provider
    if not target:
        raise SwitchError("no current provider; pass a provider name")
    if target not in state.providers:
        raise SwitchError(f"unknown provider '{target}'")
    config = state.providers[target]
    anthropic = config.get("npm") == "@ai-sdk/anthropic"

    if command == "list":
        options = config.get("options", {})
        base_url = options.get("baseURL") if isinstance(options, dict) else None
        if isinstance(base_url, str) and base_url:
            keys = load_auth_keys().get(target, [])
            api_key = keys[0] if keys else ""
            models = fetch_provider_models(base_url, api_key, anthropic)
        else:
            models = list(provider_models(state, target).keys())
        print(f"provider: {target}")
        print(f"models ({len(models)}):")
        for m in models:
            print(f"- {m}")
        return 0

    if command == "sync":
        return sync_provider_models(state, target, dry_run, force)

    return 0
