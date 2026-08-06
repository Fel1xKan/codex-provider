from __future__ import annotations

import json
import time
from typing import Any

import lib.cursor.db as db
from lib.common.errors import SwitchError

SURFACES = (
    "composer",
    "cmd-k",
    "background-composer",
    "composer-ensemble",
    "plan-execution",
    "spec",
    "deep-search",
    "quick-agent",
)


def _current_selection() -> dict[str, str]:
    app_user = db.read_application_user()
    if app_user is None:
        return {}
    model_config = app_user.get("aiSettings", {}).get("modelConfig", {})
    if not isinstance(model_config, dict):
        return {}
    result: dict[str, str] = {}
    for surface in SURFACES:
        entry = model_config.get(surface)
        if isinstance(entry, dict):
            model_id = entry.get("modelName")
            if isinstance(model_id, str) and model_id:
                parameters = entry.get("selectedModels")
                if isinstance(parameters, list) and parameters:
                    params = parameters[0].get("parameters", [])
                    if isinstance(params, list) and params:
                        param_str = ", ".join(str(p.get("value")) for p in params)
                        result[surface] = f"{model_id} ({param_str})"
                        continue
                result[surface] = model_id
    return result


def model_list_command() -> int:
    catalog = db.load_model_catalog()
    print(f"model catalog ({len(catalog)}):")
    for model in catalog:
        model_id = str(model.get("serverModelName") or "")
        display = str(model.get("clientDisplayName") or model_id)
        print(f"- {model_id} ({display})")

    print("")
    print("current selection:")
    selection = _current_selection()
    if not selection:
        print("  (none; Cursor is using server defaults)")
    for surface, model_id in selection.items():
        print(f"  {surface}: {model_id}")
    return 0


def model_set_command(model_id: str, dry_run: bool = False, force: bool = False) -> int:
    if not model_id:
        raise SwitchError("model id must not be empty")

    known = db.known_model_ids()
    if model_id not in known:
        hint = ""
        if known:
            matches = sorted(known, key=lambda m: abs(len(m) - len(model_id)))[:3]
            hint = f"; did you mean {', '.join(matches)}?"
        raise SwitchError(
            f"unknown model id: {model_id} (not found in the Cursor model "
            f"catalog{hint})"
        )

    app_user = db.read_application_user()
    if app_user is None:
        raise SwitchError(
            "cursor applicationUser state not found in the state database"
        )

    ai_settings = app_user.get("aiSettings")
    if not isinstance(ai_settings, dict):
        ai_settings = {}
        app_user["aiSettings"] = ai_settings
    model_config = ai_settings.get("modelConfig")
    if not isinstance(model_config, dict):
        model_config = {}
        ai_settings["modelConfig"] = model_config

    now_ms = int(time.time() * 1000)
    for surface in SURFACES:
        entry = model_config.get(surface)
        if not isinstance(entry, dict):
            entry = {}
            model_config[surface] = entry
        entry["modelName"] = model_id
        entry["selectedModels"] = [{"modelId": model_id, "parameters": []}]

    last_used = app_user.get("modelLastUsedAt")
    if not isinstance(last_used, dict):
        last_used = {}
        app_user["modelLastUsedAt"] = last_used
    last_used[model_id] = now_ms

    if dry_run:
        print(f"would set model for {len(SURFACES)} surfaces: {model_id}")
        for surface in SURFACES:
            print(f"  would update {surface}")
        return 0

    from lib.cursor.commands import _ensure_cursor_quit

    _ensure_cursor_quit(force)
    db.write_application_user(app_user)
    surfaces = ", ".join(SURFACES)
    print(f"set model: {model_id}")
    print(f"applied to: {surfaces}")
    return 0


def format_model_payload(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


def _target_provider(provider_name: str | None):
    import lib.cursor.store as st

    store = st.load_store()
    target = provider_name or store.current_provider
    if not target:
        raise SwitchError("no current provider; pass a provider name")
    if target not in store.providers:
        raise SwitchError(f"provider not found: {target}")
    return store.providers[target]


def models_sync_command(
    provider_name: str | None,
    api_key_stdin: bool = False,
    timeout: float = 30.0,
    dry_run: bool = False,
    force: bool = False,
) -> int:
    import lib.cursor.db as db
    import lib.cursor.store as st
    from lib.common.cli import read_api_key
    from lib.cursor.commands import _ensure_cursor_quit, _save_state_file
    from lib.cursor.providers import _fetch_model_ids

    prov = _target_provider(provider_name)
    key = prov.api_key
    if not key:
        key = read_api_key(api_key_stdin)

    print(f"fetching models from {prov.base_url}...")
    model_ids = _fetch_model_ids(prov.base_url, key, timeout)
    if not model_ids:
        raise SwitchError("no models returned by the provider")
    print(f"remote models ({len(model_ids)}):")
    for model_id in sorted(model_ids):
        print(f"- {model_id}")

    added = 0
    if not dry_run:
        _ensure_cursor_quit(force)
        added = db.ensure_catalog_models(model_ids)
        st.acquire_lock()
        try:
            store = st.load_store()
            providers = st.providers_data_dict(store)
            existing = providers.get(prov.name, {})
            merged = sorted(set(model_ids) | set(existing.get("models", [])))
            providers[prov.name] = {
                "base_url": prov.base_url,
                "api_key": prov.api_key,
                "api_key_cipher": prov.api_key_cipher,
                "models": merged,
            }
            st.state_dir().mkdir(parents=True, exist_ok=True)
            _save_state_file(
                store.current,
                st.accounts_data_dict(store),
                current_provider=store.current_provider,
                providers=providers,
            )
        finally:
            st.release_lock()

    action = "would add" if dry_run else "added"
    print(f"{action} {added} new models to the Cursor catalog")
    return 0
