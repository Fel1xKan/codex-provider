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
from lib.common.model_catalog import (
    REASONING_EFFORTS,
    load_model_catalog,
    merge_metadata,
)
from lib.common.model_metadata import extract_model_metadata, model_record_map
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
    "max_output_tokens",
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
    "supported_reasoning_levels",
    "variants",
)

# Reasoning-effort ladder used when neither the provider metadata nor the
# built-in model catalog knows a model's levels. Codex renders a model's
# `supported_reasoning_levels` in the `/model` picker, so the effort names
# Codex can select have to be written there. OpenCode's `variants` map is not
# part of Codex's model schema and is ignored by Codex.
FALLBACK_REASONING_LEVELS: tuple[str, ...] = (
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
)
_LEVEL_DESCRIPTIONS = {
    "none": "Model does not reason",
    "minimal": "Fastest responses with minimal reasoning",
    "low": "Fast responses with lighter reasoning",
    "medium": "Balances speed and reasoning depth for everyday tasks",
    "high": "Greater reasoning depth for complex problems",
    "xhigh": "Extra high reasoning depth for complex problems",
    "max": "Maximum reasoning depth for the hardest problems",
    "ultra": "Maximum reasoning with automatic task delegation",
}
# Level Codex preselects for a model that does not name its own default. The
# middle of the ladder is the useful starting point: `max`/`ultra` burn usage
# limits, and `low`/`minimal` throw away reasoning the model can afford.
DEFAULT_REASONING_LEVEL = "medium"
_PREFERRED_DEFAULT_LEVELS: tuple[str, ...] = (
    "medium",
    "high",
    "low",
    "minimal",
    "xhigh",
    "max",
    "ultra",
    "none",
)
# Update fields that map onto a different catalog key. Codex selects reasoning
# levels through `supported_reasoning_levels`; `variants` stays accepted as an
# alias so the shared `models update` command keeps one shape per effort list.
_UPDATE_FIELD_TARGETS = {"variants": "supported_reasoning_levels"}

_SCALAR_INT_FIELDS = {
    "context_window",
    "max_context_window",
    "max_output_tokens",
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

# Codex rejects a catalog whose `input_modalities` uses any other value, so
# provider metadata has to be narrowed to these before it reaches the catalog.
CODEX_INPUT_MODALITIES = ("text", "image", "audio")


def _codex_input_modalities(values: Any) -> list[str]:
    """Keep only the input modalities Codex can parse."""

    if not isinstance(values, list):
        return []
    kept = [
        name
        for name in (str(value).strip() for value in values)
        if name in CODEX_INPUT_MODALITIES
    ]
    if kept and "text" not in kept:
        kept.insert(0, "text")
    return kept


def reasoning_levels(levels: Any = None) -> list[dict[str, str]]:
    """Render Codex `supported_reasoning_levels` entries.

    Ladder entries may be plain effort names or mapping entries that carry the
    vendor's own wording, such as `{"effort": "none", "description": "Thinking
    disabled"}`. A catalog description wins over the generic table below.
    """

    names = levels if levels else list(FALLBACK_REASONING_LEVELS)
    rendered: list[dict[str, str]] = []
    for level in names:
        if isinstance(level, dict):
            name = str(level.get("effort", "")).strip()
            description = level.get("description")
        else:
            name = str(level).strip()
            description = None
        if not name:
            continue
        if not isinstance(description, str) or not description.strip():
            description = _LEVEL_DESCRIPTIONS.get(name, name)
        rendered.append({"effort": name, "description": description})
    return rendered


def default_reasoning_level(levels: list[str] | tuple[str, ...] | None) -> str:
    """Pick the level Codex preselects for a model.

    A model's own `reasoning_default` wins when the built-in catalog provides
    one; otherwise the ladder is searched for the preferred starting level.
    """

    names = list(levels) if levels else list(FALLBACK_REASONING_LEVELS)
    for candidate in _PREFERRED_DEFAULT_LEVELS:
        if candidate in names:
            return candidate
    return names[0] if names else DEFAULT_REASONING_LEVEL


def default_reasoning_ladder() -> list[dict[str, str]]:
    """Return the fallback ladder for models with no known levels."""

    return reasoning_levels(None)


def _ladder_efforts(levels: Any) -> list[str]:
    """Read the effort names out of a catalog `supported_reasoning_levels`."""

    if not isinstance(levels, list):
        return []
    names: list[str] = []
    for level in levels:
        name = level.get("effort") if isinstance(level, dict) else None
        if isinstance(name, str) and name.strip() and name.strip() not in names:
            names.append(name.strip())
    return names


def _has_generated_ladder(entry: dict[str, Any]) -> bool:
    """Report whether a catalog entry still carries an untouched ladder.

    Sync may rewrite a ladder it generated itself (including the three-level
    `low, high, max` shape that shipped before the built-in catalog knew each
    model's levels), but never a ladder a user edited or set explicitly.
    """

    names = _ladder_efforts(entry.get("supported_reasoning_levels"))
    if not names:
        return True
    return names in (list(FALLBACK_REASONING_LEVELS), ["low", "high", "max"])


def _has_generated_default(entry: dict[str, Any], levels: list[str]) -> bool:
    """Report whether `default_reasoning_level` is still a value sync wrote.

    Every catalog written before model reasoning levels were known preselected
    `max`, so that value is treated as generated and refreshed; any other
    in-ladder value is a deliberate user choice and is preserved.
    """

    current = entry.get("default_reasoning_level")
    if not isinstance(current, str) or not current.strip():
        return True
    if current not in levels:
        return True
    return current == "max"


def _apply_reasoning_levels(
    entry: dict[str, Any],
    metadata: dict[str, Any],
    *,
    is_new: bool,
    force: bool,
) -> dict[str, Any]:
    """Apply the built-in catalog's reasoning ladder to a model entry."""

    known_levels = metadata.get("reasoning_levels")
    known = isinstance(known_levels, list) and bool(known_levels)
    rewritten = _has_generated_ladder(entry)
    if not (is_new or force or rewritten):
        # The entry declares its own ladder; leave it alone.
        return entry
    ladder: list[Any] = list(known_levels) if known else list(FALLBACK_REASONING_LEVELS)
    levels = [level["effort"] for level in reasoning_levels(ladder)]

    next_entry = dict(entry)
    next_entry["supported_reasoning_levels"] = reasoning_levels(ladder)
    # Codex ignores OpenCode's `variants` map; drop it so catalogs stay clean.
    next_entry.pop("variants", None)
    if is_new or force or _has_generated_default(entry, levels):
        configured = metadata.get("reasoning_default")
        next_entry["default_reasoning_level"] = (
            configured
            if isinstance(configured, str) and configured in levels
            else default_reasoning_level(levels)
        )
    return next_entry


def minimal_catalog_entry(model_id: str) -> dict[str, Any]:
    return {
        "slug": model_id,
        "display_name": model_id,
        "description": f"Synced from provider /models: {model_id}",
        "default_reasoning_level": default_reasoning_level(None),
        "supported_reasoning_levels": default_reasoning_ladder(),
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
    }


def _parse_bool(raw: str, field: str) -> bool:
    normalized = raw.strip().lower()
    if normalized in ("true", "1", "yes"):
        return True
    if normalized in ("false", "0", "no"):
        return False
    raise SwitchError(f"invalid boolean for --set {field}: {raw!r}")


def _parse_update_value(field: str, raw: str) -> Any:
    if field in {"variants", "supported_reasoning_levels"}:
        names = [part.strip() for part in raw.split(",")]
        names = [name for name in names if name]
        if not names:
            raise SwitchError(f"--set {field} requires at least one reasoning level")
        unknown = [name for name in names if name not in REASONING_EFFORTS]
        if unknown:
            raise SwitchError(
                f"unknown reasoning level(s) {', '.join(unknown)}; "
                f"available: {', '.join(REASONING_EFFORTS)}"
            )
        seen: list[str] = []
        for name in names:
            if name not in seen:
                seen.append(name)
        return reasoning_levels(seen)
    if field == "default_reasoning_level":
        value = raw.strip()
        if value and value not in REASONING_EFFORTS:
            raise SwitchError(
                f"unknown reasoning level {value!r}; "
                f"available: {', '.join(REASONING_EFFORTS)}"
            )
        return value
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


def _fetch_models(target: str, config: dict[str, Any]) -> Any:
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


def _fetch_ids(target: str, config: dict[str, Any]) -> list[str]:
    return list(_fetch_models(target, config))


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
    model_id = str(next_entry.get("slug", ""))
    display_name = metadata.get("display_name")
    if display_name and (is_new or next_entry.get("display_name") in (None, model_id)):
        next_entry["display_name"] = display_name

    context_window = metadata.get("context_window")
    default_context = minimal_catalog_entry(model_id)["context_window"]
    if context_window and (
        is_new or next_entry.get("context_window") == default_context
    ):
        next_entry["context_window"] = context_window
        if is_new or next_entry.get("max_context_window") == default_context:
            next_entry["max_context_window"] = context_window

    max_output_tokens = metadata.get("max_output_tokens")
    if max_output_tokens and (is_new or "max_output_tokens" not in next_entry):
        next_entry["max_output_tokens"] = max_output_tokens

    input_modalities = _codex_input_modalities(metadata.get("input_modalities"))
    if input_modalities and (is_new or next_entry.get("input_modalities") == ["text"]):
        next_entry["input_modalities"] = input_modalities
    return next_entry


def _resolve_catalog_path(
    target: str, config: dict[str, Any], state: st.ProviderState
) -> tuple[Path, bool]:
    pointer = catalog_pointer_path(config)
    if pointer is not None:
        return pointer, pointer.exists()
    default = default_catalog_path(target)
    return default, default.exists()


def sync_provider_models(target: str, dry_run: bool, force: bool = False) -> int:
    lock = nullcontext() if dry_run else st.state_lock()
    with lock:
        state = st.ensure_provider_state(read_only=dry_run)
        if target not in state.providers:
            raise SwitchError(f"unknown provider '{target}'")
        config = state.providers[target]
        fetched = _fetch_models(target, config)
        model_ids = list(fetched)
        remote_metadata = _remote_metadata(fetched)
        catalog_metadata = _catalog_metadata()
        catalog_path, catalog_exists = _resolve_catalog_path(target, config, state)
        existing = load_catalog(catalog_path) if catalog_exists else {}
        merged: dict[str, dict[str, Any]] = {}
        added = 0
        refreshed = 0
        for model_id in model_ids:
            metadata = merge_metadata(
                catalog_metadata.get(model_id, {}),
                remote_metadata.get(model_id, {}),
            )
            if model_id in existing:
                entry = _apply_remote_metadata(
                    existing[model_id],
                    metadata,
                    is_new=False,
                )
                is_new = False
            else:
                entry = _apply_remote_metadata(
                    minimal_catalog_entry(model_id), metadata, is_new=True
                )
                is_new = True
                added += 1

            before = _ladder_efforts(entry.get("supported_reasoning_levels"))
            entry = _apply_reasoning_levels(entry, metadata, is_new=is_new, force=force)
            after = _ladder_efforts(entry.get("supported_reasoning_levels"))
            if force and after != before:
                refreshed += 1
            merged[model_id] = entry
        for model_id, entry in existing.items():
            if model_id not in merged:
                # Retained models are not offered by the provider any more, so
                # only the built-in catalog can describe them.
                merged[model_id] = _apply_reasoning_levels(
                    entry,
                    catalog_metadata.get(model_id, {}),
                    is_new=False,
                    force=force,
                )
        payload = render_catalog(merged)

        if dry_run:
            print(f"would sync models for provider '{target}': {len(model_ids)} models")
            print(f"would add {added} new models to catalog: {catalog_path}")
            if force:
                print(f"would refresh reasoning levels for {refreshed} models")
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
    if force:
        print(f"refreshed reasoning levels for {refreshed} models: {catalog_path}")
    return 0


def sync_all_models(dry_run: bool = False, force: bool = False) -> int:
    state = st.ensure_provider_state(read_only=True)
    if not state.providers:
        raise SwitchError("no providers configured")
    failures = 0
    for target in sorted(state.providers):
        try:
            sync_provider_models(target, dry_run, force)
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
        limit_updates = {
            "context_window": context_window,
            "max_output_tokens": max_output_tokens,
        }
        limit_updates = {
            field: value for field, value in limit_updates.items() if value is not None
        }
        for field, value in limit_updates.items():
            if value <= 0:
                raise SwitchError(f"--{field} must be > 0")

        catalog_changes: list[str] = []
        catalog_payload: bytes | None = None
        if limit_updates:
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
            if context_window is not None:
                entry["context_window"] = context_window
                entry["max_context_window"] = context_window
                catalog_changes.extend(
                    [
                        f"context_window = {context_window}",
                        f"max_context_window = {context_window}",
                    ]
                )
            if max_output_tokens is not None:
                entry["max_output_tokens"] = max_output_tokens
                catalog_changes.append(f"max_output_tokens = {max_output_tokens}")
            entries[model] = entry
            catalog_payload = render_catalog(entries)

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
            changes = [FileChange(runtime_config, rendered.encode("utf-8"))]
            if catalog_payload is not None:
                changes.insert(0, FileChange(catalog_path, catalog_payload))
            apply_changes(changes)

    action = "would set" if dry_run else "set"
    print(f"{action} model: {target}/{model}")
    for change in catalog_changes:
        print(f"- {change}")
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
            key = _UPDATE_FIELD_TARGETS.get(field, field)
            if isinstance(value, str):
                text = value.strip()
                if not text:
                    if key in entry:
                        del entry[key]
                        changes.append(f"remove {key}")
                    else:
                        changes.append(f"{key} remains unset")
                else:
                    entry[key] = text
                    changes.append(f"{key} = {text}")
            else:
                entry[key] = value
                if key == "supported_reasoning_levels":
                    names = [level["effort"] for level in value]
                    changes.append(f"{key} = {', '.join(names)}")
                else:
                    changes.append(f"{key} = {json.dumps(value, ensure_ascii=False)}")
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
    force: bool = False,
    update_sets: list[str] | None = None,
    context_window: int | None = None,
    max_output_tokens: int | None = None,
) -> int:
    if command == "sync" and all_providers:
        if provider is not None:
            raise SwitchError("--all cannot be combined with a provider")
        return sync_all_models(dry_run, force)
    if command == "list":
        return list_provider_models(provider)
    if command == "sync":
        return sync_provider_models(_resolve_target(provider), dry_run, force)
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
