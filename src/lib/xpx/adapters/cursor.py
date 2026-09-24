from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from lib.common.errors import SwitchError
from lib.common.oscrypt import encrypt_secret_plaintext
from lib.xpx.adapters.base import MergedProviderSpec, TargetAdapter, TargetStatus

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


def _build_cursor_model_entry(model_id: str) -> dict[str, Any]:
    return {
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


def _ensure_catalog_models(app_user: dict[str, Any], model_ids: list[str]) -> int:
    catalog = app_user.get("availableDefaultModels2")
    if not isinstance(catalog, list):
        catalog = []
    known = {
        str(m.get("serverModelName") or m.get("name"))
        for m in catalog
        if isinstance(m, dict)
    }
    added = 0
    for model_id in model_ids:
        if not model_id or model_id in known:
            continue
        catalog.append(_build_cursor_model_entry(model_id))
        known.add(model_id)
        added += 1
    if added:
        app_user["availableDefaultModels2"] = catalog
    return added


def get_cursor_dir() -> Path:
    override = os.environ.get("CURSOR_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", "")) / "Cursor"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Cursor"
    return Path.home() / ".config" / "Cursor"


def get_cursor_db_path() -> Path:
    override = os.environ.get("CURSOR_DB_PATH")
    if override:
        return Path(override)
    return get_cursor_dir() / "User" / "globalStorage" / "state.vscdb"


class CursorAdapter(TargetAdapter):
    name = "cursor"
    display_name = "Cursor IDE"
    supported_protocols = ["openai"]
    binary_name = "cursor"
    install_guide = (
        "Cursor is a desktop AI editor. Download and install from https://cursor.com, "
        "then run 'Install cursor command in PATH' inside Cursor."
    )

    def __init__(self, db_path_override: Path | None = None) -> None:
        self._db_path = db_path_override

    @property
    def path(self) -> Path:
        return self._db_path or get_cursor_db_path()

    def detect(self) -> bool:
        return (
            self.path.exists()
            or self.path.parent.is_dir()
            or shutil.which("cursor") is not None
        )

    def _connect(self) -> sqlite3.Connection:
        if not self.path.exists():
            raise SwitchError(f"cursor state database not found: {self.path}")
        con = sqlite3.connect(str(self.path), timeout=5.0)
        con.execute("PRAGMA busy_timeout = 5000")
        return con

    def _ensure_db_initialized(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(self.path), timeout=5.0)
        try:
            con.execute(
                "CREATE TABLE IF NOT EXISTS ItemTable "
                "(key TEXT PRIMARY KEY, value TEXT)"
            )
            con.execute(
                "INSERT OR IGNORE INTO ItemTable (key, value) "
                "VALUES ('applicationUser', '{}')"
            )
            con.commit()
        finally:
            con.close()

    def _read_application_user(self, con: sqlite3.Connection) -> dict[str, Any]:
        try:
            row = con.execute(
                "SELECT value FROM ItemTable WHERE key = 'applicationUser'"
            ).fetchone()
            if row and row[0]:
                data = json.loads(row[0])
                if isinstance(data, dict):
                    return data
            return {}
        except Exception:
            return {}

    def _write_application_user(
        self, con: sqlite3.Connection, app_user: dict[str, Any]
    ) -> None:
        payload = json.dumps(app_user, ensure_ascii=False)
        con.execute(
            "INSERT OR REPLACE INTO ItemTable (key, value) "
            "VALUES ('applicationUser', ?)",
            (payload,),
        )

    def get_status(self) -> TargetStatus:
        ver = self.get_cli_version()
        bin_p = self.get_binary_path()
        if not self.path.is_file():
            return TargetStatus(
                installed=self.detect(),
                active_type="none",
                active_name="-",
                config_path=str(self.path),
                cli_version=ver,
                binary_path=bin_p,
            )
        try:
            con = self._connect()
            try:
                app_user = self._read_application_user(con)
                base_url = app_user.get("openAIBaseUrl")
                model_config = (
                    app_user.get("aiSettings", {}).get("modelConfig", {})
                    if isinstance(app_user.get("aiSettings"), dict)
                    else {}
                )
                composer = (
                    model_config.get("composer", {})
                    if isinstance(model_config, dict)
                    else {}
                )
                model = (
                    composer.get("modelName") or composer.get("modelId")
                    if isinstance(composer, dict)
                    else None
                )
                if base_url:
                    active_name = str(app_user.get("xpxProviderName") or base_url)
                    return TargetStatus(
                        installed=True,
                        active_type="provider",
                        active_name=active_name,
                        active_model=str(model) if model else None,
                        config_path=str(self.path),
                        cli_version=ver,
                        binary_path=bin_p,
                    )
                return TargetStatus(
                    installed=True,
                    active_type="official",
                    active_name="cursor",
                    active_model=str(model) if model else None,
                    config_path=str(self.path),
                    cli_version=ver,
                    binary_path=bin_p,
                )
            finally:
                con.close()
        except Exception as exc:
            return TargetStatus(
                installed=True,
                active_type="error",
                active_name=f"read error: {exc}",
                config_path=str(self.path),
                cli_version=ver,
                binary_path=bin_p,
            )

    def apply(self, spec: MergedProviderSpec) -> None:
        self._ensure_db_initialized()
        con = self._connect()
        try:
            with con:
                app_user = self._read_application_user(con)
                app_user["openAIBaseUrl"] = spec.base_url
                app_user["xpxProviderName"] = spec.name

                model_ids: list[str] = []
                if spec.model:
                    model_ids.append(spec.model)
                try:
                    from lib.xpx.store.catalog_store import CatalogStore
                    from lib.xpx.store.provider_store import ProviderStore

                    cat = CatalogStore().get(spec.name)
                    if cat:
                        model_ids.extend(cat.models.keys())
                    pv = ProviderStore().get(spec.name)
                    if pv and pv.models:
                        model_ids.extend(pv.models)
                except Exception:
                    pass

                _ensure_catalog_models(app_user, model_ids)

                if spec.model:
                    ai_settings = app_user.setdefault("aiSettings", {})
                    if not isinstance(ai_settings, dict):
                        ai_settings = {}
                        app_user["aiSettings"] = ai_settings
                    model_config = ai_settings.setdefault("modelConfig", {})
                    if not isinstance(model_config, dict):
                        model_config = {}
                        ai_settings["modelConfig"] = model_config

                    now_ms = int(time.time() * 1000)
                    for surface in SURFACES:
                        entry = model_config.setdefault(surface, {})
                        if not isinstance(entry, dict):
                            entry = {}
                            model_config[surface] = entry
                        entry["modelName"] = spec.model
                        entry["modelId"] = spec.model
                        entry["selectedModels"] = [
                            {"modelId": spec.model, "parameters": []}
                        ]

                    last_used = app_user.setdefault("modelLastUsedAt", {})
                    if isinstance(last_used, dict):
                        last_used[spec.model] = now_ms

                self._write_application_user(con, app_user)

                cipher = encrypt_secret_plaintext(spec.api_key)
                key_value = cipher or spec.api_key
                con.execute(
                    "INSERT OR REPLACE INTO ItemTable (key, value) "
                    "VALUES ('secret://cursorAuth/openAIKey', ?)",
                    (key_value,),
                )
        except sqlite3.Error as exc:
            raise SwitchError(f"unable to write cursor database: {exc}") from exc
        finally:
            con.close()

    def refresh_catalog(self, provider_name: str | None = None) -> bool:
        if not self.path.is_file():
            return False
        try:
            con = self._connect()
            try:
                with con:
                    app_user = self._read_application_user(con)
                    base_url = app_user.get("openAIBaseUrl")
                    if not base_url:
                        return False
                    active_pv = app_user.get("xpxProviderName")
                    if provider_name and active_pv and provider_name != active_pv:
                        return False

                    pv_name = provider_name or active_pv
                    model_ids: list[str] = []
                    default_model: str | None = None

                    if pv_name:
                        try:
                            from lib.xpx.store.catalog_store import CatalogStore
                            from lib.xpx.store.provider_store import ProviderStore

                            cat = CatalogStore().get(pv_name)
                            if cat:
                                model_ids.extend(cat.models.keys())
                            pv = ProviderStore().get(pv_name)
                            if pv:
                                if pv.default_model:
                                    default_model = pv.default_model
                                    model_ids.append(pv.default_model)
                                if pv.models:
                                    model_ids.extend(pv.models)
                        except Exception:
                            pass

                    _ensure_catalog_models(app_user, model_ids)

                    if default_model:
                        ai_settings = app_user.setdefault("aiSettings", {})
                        if not isinstance(ai_settings, dict):
                            ai_settings = {}
                            app_user["aiSettings"] = ai_settings
                        model_config = ai_settings.setdefault("modelConfig", {})
                        if not isinstance(model_config, dict):
                            model_config = {}
                            ai_settings["modelConfig"] = model_config

                        now_ms = int(time.time() * 1000)
                        for surface in SURFACES:
                            entry = model_config.setdefault(surface, {})
                            if not isinstance(entry, dict):
                                entry = {}
                                model_config[surface] = entry
                            entry["modelName"] = default_model
                            entry["modelId"] = default_model
                            entry["selectedModels"] = [
                                {"modelId": default_model, "parameters": []}
                            ]

                        last_used = app_user.setdefault("modelLastUsedAt", {})
                        if isinstance(last_used, dict):
                            last_used[default_model] = now_ms

                    self._write_application_user(con, app_user)
                    return True
            finally:
                con.close()
        except Exception:
            return False

    def clear(self) -> None:
        if self.path.is_file():
            con = self._connect()
            try:
                with con:
                    app_user = self._read_application_user(con)
                    app_user.pop("openAIBaseUrl", None)
                    app_user.pop("xpxProviderName", None)
                    self._write_application_user(con, app_user)
                    con.execute(
                        "DELETE FROM ItemTable WHERE key = 'secret://cursorAuth/openAIKey'"
                    )
            except Exception as exc:
                raise SwitchError(f"unable to reset cursor state: {exc}") from exc
            finally:
                con.close()

    def ping(
        self, prompt: str, timeout: int, spec: MergedProviderSpec | None = None
    ) -> tuple[bool, str]:
        cmd = ["cursor", "--version"]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            out = proc.stdout.strip() or proc.stderr.strip()
            return proc.returncode == 0, out
        except Exception as exc:
            return False, str(exc)

    def update(self, dry_run: bool = False) -> tuple[bool, str]:
        msg = (
            "Cursor updates automatically in the background. Check for updates "
            "inside Cursor (Help > Check for Updates) or visit https://cursor.com."
        )
        if dry_run:
            return True, f"guide: {msg}"
        return True, msg
