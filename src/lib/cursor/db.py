from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
from typing import Any

from lib.common.errors import SwitchError
from lib.cursor.store import (
    AUTH_DB_KEYS,
    REACTIVE_ACCOUNT_FIELDS,
    REACTIVE_STORAGE_KEY,
    db_path,
)


def _connect() -> sqlite3.Connection:
    path = db_path()
    if not path.exists():
        raise SwitchError(f"cursor state database not found: {path}")
    try:
        con = sqlite3.connect(str(path), timeout=10.0)
        con.execute("PRAGMA busy_timeout = 10000")
        return con
    except sqlite3.Error as exc:
        raise SwitchError(
            f"unable to open cursor state database {path}: {exc}"
        ) from exc


def _read_rows(con: sqlite3.Connection, keys: tuple[str, ...]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key in keys:
        try:
            row = con.execute(
                "SELECT value FROM ItemTable WHERE key = ?", (key,)
            ).fetchone()
        except sqlite3.Error as exc:
            raise SwitchError(f"unable to read cursor state database: {exc}") from exc
        if row is not None and row[0] is not None:
            result[key] = str(row[0])
    return result


def read_items(keys: tuple[str, ...]) -> dict[str, str]:
    con = _connect()
    try:
        return _read_rows(con, keys)
    finally:
        con.close()


def read_item(key: str) -> str | None:
    return read_items((key,)).get(key)


def update_items(updates: dict[str, str], dry_run: bool = False) -> None:
    if dry_run:
        return
    con = _connect()
    try:
        with con:
            for key, value in updates.items():
                con.execute(
                    "INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
                    (key, value),
                )
    except sqlite3.Error as exc:
        raise SwitchError(f"unable to write cursor state database: {exc}") from exc
    finally:
        con.close()


def delete_items(keys: tuple[str, ...], dry_run: bool = False) -> None:
    if dry_run:
        return
    con = _connect()
    try:
        with con:
            for key in keys:
                con.execute("DELETE FROM ItemTable WHERE key = ?", (key,))
    except sqlite3.Error as exc:
        raise SwitchError(f"unable to write cursor state database: {exc}") from exc
    finally:
        con.close()


def read_application_user() -> dict[str, Any] | None:
    raw = read_item(REACTIVE_STORAGE_KEY)
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise SwitchError(f"invalid cursor applicationUser JSON: {exc}") from exc
    return data if isinstance(data, dict) else None


def write_application_user(data: dict[str, Any], dry_run: bool = False) -> None:
    try:
        payload = json.dumps(data, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise SwitchError(f"unable to serialize cursor applicationUser: {exc}") from exc
    update_items({REACTIVE_STORAGE_KEY: payload}, dry_run=dry_run)


def current_auth_snapshot() -> dict[str, Any]:
    """Read the currently logged-in account state from the Cursor database."""
    items = read_items(AUTH_DB_KEYS)
    auth_data: dict[str, Any] = {}
    mapping = {
        "cursorAuth/accessToken": "accessToken",
        "cursorAuth/refreshToken": "refreshToken",
        "cursorAuth/cachedEmail": "cachedEmail",
        "cursorAuth/cachedSignUpType": "cachedSignUpType",
        "cursorAuth/cachedScopedProfile": "cachedScopedProfile",
        "cursorAuth/stripeMembershipType": "stripeMembershipType",
        "glass.lastSignedInAuthId": "lastSignedInAuthId",
    }
    for db_key, short_key in mapping.items():
        if db_key in items:
            auth_data[short_key] = items[db_key]

    app_user = read_application_user()
    if app_user is not None:
        for field in REACTIVE_ACCOUNT_FIELDS:
            if field in app_user:
                auth_data[field] = app_user[field]

    return auth_data


def auth_db_updates(auth_data: dict[str, Any]) -> dict[str, str]:
    """Build the ItemTable update map for an account's auth_data."""
    mapping = {
        "accessToken": "cursorAuth/accessToken",
        "refreshToken": "cursorAuth/refreshToken",
        "cachedEmail": "cursorAuth/cachedEmail",
        "cachedSignUpType": "cursorAuth/cachedSignUpType",
        "cachedScopedProfile": "cursorAuth/cachedScopedProfile",
        "stripeMembershipType": "cursorAuth/stripeMembershipType",
        "lastSignedInAuthId": "glass.lastSignedInAuthId",
    }
    updates: dict[str, str] = {}
    for short_key, db_key in mapping.items():
        value = auth_data.get(short_key)
        if value is not None:
            updates[db_key] = str(value)
    return updates


def apply_account_auth(auth_data: dict[str, Any], dry_run: bool = False) -> None:
    """Write an account's auth_data into the Cursor state database."""
    updates = auth_db_updates(auth_data)
    update_items(updates, dry_run=dry_run)

    account_fields = {
        field: auth_data[field]
        for field in REACTIVE_ACCOUNT_FIELDS
        if field in auth_data
    }
    if account_fields:
        app_user = read_application_user()
        if app_user is not None:
            app_user.update(account_fields)
            write_application_user(app_user, dry_run=dry_run)
    return None


def clear_account_auth(dry_run: bool = False) -> None:
    """Remove the logged-in auth state from the Cursor state database."""
    delete_items(AUTH_DB_KEYS, dry_run=dry_run)
    app_user = read_application_user()
    if app_user is not None:
        changed = False
        for field in REACTIVE_ACCOUNT_FIELDS:
            if field in app_user:
                app_user.pop(field)
                changed = True
        if changed:
            write_application_user(app_user, dry_run=dry_run)


def load_model_catalog() -> list[dict[str, Any]]:
    """Load the model catalog cached in the reactive storage blob."""
    app_user = read_application_user()
    if app_user is None:
        return []
    models = app_user.get("availableDefaultModels2")
    if not isinstance(models, list):
        return []
    return [m for m in models if isinstance(m, dict)]


def load_feature_model_ids() -> set[str]:
    """Collect model ids referenced by feature defaults and fallbacks."""
    app_user = read_application_user()
    if app_user is None:
        return set()
    feature_configs = app_user.get("featureModelConfigs")
    ids: set[str] = set()
    if isinstance(feature_configs, dict):
        for config in feature_configs.values():
            if not isinstance(config, dict):
                continue
            for key in ("defaultModel",):
                value = config.get(key)
                if isinstance(value, str):
                    ids.add(value)
            for key in ("fallbackModels", "bestOfNDefaultModels"):
                value = config.get(key)
                if isinstance(value, list):
                    ids.update(v for v in value if isinstance(v, str))
    return ids


def known_model_ids() -> set[str]:
    ids = {str(m.get("serverModelName")) for m in load_model_catalog()}
    ids.discard("")
    ids |= load_feature_model_ids()
    return ids


def read_current_model() -> str | None:
    """Return a short summary of the currently selected composer model."""
    app_user = read_application_user()
    if app_user is None:
        return None
    model_config = app_user.get("aiSettings", {}).get("modelConfig", {})
    if not isinstance(model_config, dict):
        return None
    composer = model_config.get("composer")
    if not isinstance(composer, dict):
        return None
    model_id = composer.get("modelName") or composer.get("modelId")
    if not isinstance(model_id, str) or not model_id:
        return None
    return model_id


def read_openai_base_url() -> str | None:
    """Return the custom OpenAI-compatible base URL override, if any."""
    app_user = read_application_user()
    if app_user is None:
        return None
    value = app_user.get("openAIBaseUrl")
    return value if isinstance(value, str) and value else None


def write_openai_base_url(base_url: str | None, dry_run: bool = False) -> None:
    """Set or clear the custom OpenAI-compatible base URL override."""
    app_user = read_application_user()
    if app_user is None:
        raise SwitchError(
            "cursor applicationUser state not found in the state database"
        )
    if base_url:
        app_user["openAIBaseUrl"] = base_url
    else:
        app_user.pop("openAIBaseUrl", None)
    write_application_user(app_user, dry_run=dry_run)


def read_openai_key_cipher() -> str | None:
    """Return the raw secret://cursorAuth/openAIKey value (opaque)."""
    return read_item("secret://cursorAuth/openAIKey")


def write_openai_key_cipher(cipher: str | None, dry_run: bool = False) -> None:
    """Write or clear the secret://cursorAuth/openAIKey value."""
    if dry_run:
        return
    con = _connect()
    try:
        with con:
            if cipher:
                con.execute(
                    "INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
                    ("secret://cursorAuth/openAIKey", cipher),
                )
            else:
                con.execute(
                    "DELETE FROM ItemTable WHERE key = ?",
                    ("secret://cursorAuth/openAIKey",),
                )
    except sqlite3.Error as exc:
        raise SwitchError(f"unable to write cursor state database: {exc}") from exc
    finally:
        con.close()


def user_added_models() -> list[dict[str, Any]]:
    """Return catalog entries that were manually added by the user."""
    return [m for m in load_model_catalog() if m.get("isUserAdded")]


def ensure_catalog_models(model_ids: list[str], dry_run: bool = False) -> int:
    """Add missing model ids to the catalog as user-added entries.

    Existing entries are preserved; ids are never removed. Returns the
    number of models added.
    """
    app_user = read_application_user()
    if app_user is None:
        raise SwitchError(
            "cursor applicationUser state not found in the state database"
        )
    catalog = app_user.get("availableDefaultModels2")
    if not isinstance(catalog, list):
        catalog = []
    known = {str(m.get("serverModelName") or m.get("name")) for m in catalog}
    added = 0
    for model_id in model_ids:
        if model_id in known:
            continue
        catalog.append(
            {
                "name": model_id,
                "defaultOn": False,
                "supportsAgent": True,
                "degradationStatus": 0,
                "supportsThinking": True,
                "supportsImages": True,
                "supportsMaxMode": True,
                "supportsNonMaxMode": True,
                "serverModelName": model_id,
                "isRecommendedForBackgroundComposer": False,
                "supportsPlanMode": True,
                "supportsSandboxing": True,
                "isUserAdded": True,
                "inputboxShortModelName": model_id,
                "parameterDefinitions": [],
                "variants": [],
                "legacySlugs": [],
                "idAliases": [],
                "namedModelSectionIndex": 1,
                "cloudAgentEffortModes": [],
                "modelPickerBadges": [],
            }
        )
        known.add(model_id)
        added += 1
    if added:
        app_user["availableDefaultModels2"] = catalog
        write_application_user(app_user, dry_run=dry_run)
    return added


def cursor_running() -> bool:
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq Cursor.exe", "/FO", "CSV"],
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return "Cursor.exe" in result.stdout
        except (OSError, subprocess.SubprocessError):
            return False
    if shutil.which("pgrep"):
        try:
            result = subprocess.run(
                ["pgrep", "-x", "Cursor"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode == 0:
                return True
            result = subprocess.run(
                ["pgrep", "-x", "cursor"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            return result.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False
    return False
