from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lib.common.common_store import FileLockManager
from lib.common.errors import SwitchError

ACCOUNT_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")
PROVIDER_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")

AUTH_DB_KEYS = (
    "cursorAuth/accessToken",
    "cursorAuth/refreshToken",
    "cursorAuth/cachedEmail",
    "cursorAuth/cachedSignUpType",
    "cursorAuth/cachedScopedProfile",
    "cursorAuth/stripeMembershipType",
    "glass.lastSignedInAuthId",
)

REACTIVE_STORAGE_KEY = (
    "src.vs.platform.reactivestorage.browser.reactiveStorageServiceImpl."
    "persistentStorage.applicationUser"
)
SERVER_CONFIG_KEY = "cursorai/serverConfig"

# Optional reactive-storage account fields written during account switch.
REACTIVE_ACCOUNT_FIELDS = (
    "dashboardUserId",
    "membershipType",
    "isEnterprise",
)


def _module() -> Any:
    return sys.modules.get("cli.cursor_provider") or sys.modules.get("cursor_provider")


def home() -> Path:
    mod = _module()
    if mod and hasattr(mod, "HOME"):
        return mod.HOME
    return Path.home()


def cursor_dir() -> Path:
    mod = _module()
    if mod and hasattr(mod, "CURSOR_DIR"):
        return mod.CURSOR_DIR
    if sys.platform == "win32":
        return home() / "AppData" / "Roaming" / "Cursor"
    if sys.platform == "darwin":
        return home() / "Library" / "Application Support" / "Cursor"
    return home() / ".config" / "Cursor"


def db_path() -> Path:
    mod = _module()
    if mod and hasattr(mod, "DB_PATH"):
        return mod.DB_PATH
    return cursor_dir() / "User" / "globalStorage" / "state.vscdb"


def tool_home() -> Path:
    mod = _module()
    if mod and hasattr(mod, "TOOL_HOME"):
        return mod.TOOL_HOME
    return home() / ".cursor-provider"


def data_dir() -> Path:
    mod = _module()
    if mod and hasattr(mod, "DATA_DIR"):
        return mod.DATA_DIR
    return tool_home()


def state_dir() -> Path:
    mod = _module()
    if mod and hasattr(mod, "STATE_DIR"):
        return mod.STATE_DIR
    return tool_home() / "state"


def auth_path() -> Path:
    mod = _module()
    if mod and hasattr(mod, "AUTH_PATH"):
        return mod.AUTH_PATH
    return tool_home() / "auth.json"


def state_path() -> Path:
    mod = _module()
    if mod and hasattr(mod, "STATE_PATH"):
        return mod.STATE_PATH
    return state_dir() / "state.json"


def recent_path() -> Path:
    mod = _module()
    if mod and hasattr(mod, "RECENT_PATH"):
        return mod.RECENT_PATH
    return state_dir() / "recent.json"


def lock_path() -> Path:
    mod = _module()
    if mod and hasattr(mod, "LOCK_PATH"):
        return mod.LOCK_PATH
    return state_dir() / "cursor-provider.lock"


lock_mgr = FileLockManager(lock_path())


def acquire_lock() -> None:
    lock_mgr.lock_path = lock_path()
    lock_mgr.acquire()


def release_lock() -> None:
    lock_mgr.release()


@dataclass(frozen=True)
class AccountState:
    name: str
    email: str
    display_name: str
    auth_method: str
    auth_data: dict[str, Any]


@dataclass(frozen=True)
class ProviderState:
    name: str
    base_url: str
    api_key: str
    api_key_cipher: str
    models: list[str]


@dataclass(frozen=True)
class StoreState:
    current: str
    accounts: dict[str, AccountState]
    current_provider: str
    providers: dict[str, ProviderState]


def extract_account_info(auth_data: dict[str, Any]) -> tuple[str, str, str]:
    email = str(auth_data.get("cachedEmail") or "")
    display_name = ""
    auth_method = str(auth_data.get("cachedSignUpType") or "")

    scoped_profile = auth_data.get("cachedScopedProfile")
    if isinstance(scoped_profile, str):
        try:
            profile = json.loads(scoped_profile)
            if isinstance(profile, dict):
                display_name = str(profile.get("displayName") or "")
        except (OSError, ValueError):
            pass

    access_token = auth_data.get("accessToken")
    if isinstance(access_token, str):
        try:
            from lib.common.jwt_helper import parse_jwt_claims

            claims = parse_jwt_claims(access_token)
            if claims:
                sub = str(claims.get("sub") or "")
                if "|" in sub and not auth_method:
                    auth_method = sub.split("|", 1)[0]
                if not display_name:
                    display_name = str(claims.get("name") or "")
        except Exception:
            pass

    return email, display_name, auth_method


def load_store() -> StoreState:
    state_file = state_path()
    if not state_file.exists():
        return StoreState(current="", accounts={}, current_provider="", providers={})
    try:
        raw = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SwitchError(f"invalid cursor state JSON: {state_file}: {exc}") from exc

    if not isinstance(raw, dict):
        raise SwitchError(f"cursor state file must contain an object: {state_file}")

    current = str(raw.get("current", ""))
    accounts_raw = raw.get("accounts", {})
    if not isinstance(accounts_raw, dict):
        accounts_raw = {}

    accounts: dict[str, AccountState] = {}
    for acc_name, acc_info in accounts_raw.items():
        if isinstance(acc_info, dict):
            auth_data = acc_info.get("auth_data", {})
            if not isinstance(auth_data, dict):
                auth_data = {}
            email, display_name, auth_method = extract_account_info(auth_data)
            accounts[acc_name] = AccountState(
                name=acc_name,
                email=acc_info.get("email") or email,
                display_name=acc_info.get("display_name") or display_name,
                auth_method=acc_info.get("auth_method") or auth_method,
                auth_data=auth_data,
            )

    current_provider = str(raw.get("current_provider", ""))
    providers_raw = raw.get("providers", {})
    if not isinstance(providers_raw, dict):
        providers_raw = {}
    providers: dict[str, ProviderState] = {}
    for prov_name, prov_info in providers_raw.items():
        if not isinstance(prov_info, dict):
            continue
        models = prov_info.get("models", [])
        if not isinstance(models, list):
            models = []
        providers[prov_name] = ProviderState(
            name=prov_name,
            base_url=str(prov_info.get("base_url") or ""),
            api_key=str(prov_info.get("api_key") or ""),
            api_key_cipher=str(prov_info.get("api_key_cipher") or ""),
            models=[str(m) for m in models],
        )

    return StoreState(
        current=current,
        accounts=accounts,
        current_provider=current_provider,
        providers=providers,
    )


def accounts_data_dict(store: StoreState) -> dict[str, dict[str, Any]]:
    return {
        name: {
            "email": a.email,
            "display_name": a.display_name,
            "auth_method": a.auth_method,
            "auth_data": a.auth_data,
        }
        for name, a in store.accounts.items()
    }


def providers_data_dict(store: StoreState) -> dict[str, dict[str, Any]]:
    return {
        name: {
            "base_url": p.base_url,
            "api_key": p.api_key,
            "api_key_cipher": p.api_key_cipher,
            "models": p.models,
        }
        for name, p in store.providers.items()
    }
