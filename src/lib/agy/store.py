from __future__ import annotations

import json
import os
import re
import sys
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lib.common.common_store import FileLockManager
from lib.common.errors import SwitchError

WINCRED_TARGET = "gemini:antigravity"
WINCRED_USER = "antigravity"

ACCOUNT_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


def home() -> Path:
    mod = sys.modules.get("cli.agy_provider") or sys.modules.get("agy_provider")
    if mod and hasattr(mod, "HOME"):
        return mod.HOME
    return Path.home()


def gemini_dir() -> Path:
    mod = sys.modules.get("cli.agy_provider") or sys.modules.get("agy_provider")
    if mod and hasattr(mod, "GEMINI_DIR"):
        return mod.GEMINI_DIR
    return home() / ".gemini"


def cli_dir() -> Path:
    mod = sys.modules.get("cli.agy_provider") or sys.modules.get("agy_provider")
    if mod and hasattr(mod, "CLI_DIR"):
        return mod.CLI_DIR
    return gemini_dir() / "antigravity-cli"


def config_dir() -> Path:
    mod = sys.modules.get("cli.agy_provider") or sys.modules.get("agy_provider")
    if mod and hasattr(mod, "CONFIG_DIR"):
        return mod.CONFIG_DIR
    return gemini_dir() / "config"


def oauth_token_path() -> Path:
    mod = sys.modules.get("cli.agy_provider") or sys.modules.get("agy_provider")
    if mod and hasattr(mod, "OAUTH_TOKEN_PATH"):
        return mod.OAUTH_TOKEN_PATH
    return cli_dir() / "antigravity-oauth-token"


def standalone_oauth_token_path() -> Path:
    mod = sys.modules.get("cli.agy_provider") or sys.modules.get("agy_provider")
    if mod and hasattr(mod, "STANDALONE_OAUTH_TOKEN_PATH"):
        return mod.STANDALONE_OAUTH_TOKEN_PATH
    return cli_dir() / "jetski-standalone-oauth-token"


def config_path() -> Path:
    mod = sys.modules.get("cli.agy_provider") or sys.modules.get("agy_provider")
    if mod and hasattr(mod, "CONFIG_PATH"):
        return mod.CONFIG_PATH
    return config_dir() / "config.json"


def settings_path() -> Path:
    mod = sys.modules.get("cli.agy_provider") or sys.modules.get("agy_provider")
    if mod and hasattr(mod, "SETTINGS_PATH"):
        return mod.SETTINGS_PATH
    return cli_dir() / "settings.json"


def tool_home() -> Path:
    mod = sys.modules.get("cli.agy_provider") or sys.modules.get("agy_provider")
    if mod and hasattr(mod, "TOOL_HOME"):
        return mod.TOOL_HOME
    return home() / ".gemini" / "agy-provider"


def data_dir() -> Path:
    mod = sys.modules.get("cli.agy_provider") or sys.modules.get("agy_provider")
    if mod and hasattr(mod, "DATA_DIR"):
        return mod.DATA_DIR
    return tool_home()


def state_dir() -> Path:
    mod = sys.modules.get("cli.agy_provider") or sys.modules.get("agy_provider")
    if mod and hasattr(mod, "STATE_DIR"):
        return mod.STATE_DIR
    return tool_home() / "state"


def auth_path() -> Path:
    mod = sys.modules.get("cli.agy_provider") or sys.modules.get("agy_provider")
    if mod and hasattr(mod, "AUTH_PATH"):
        return mod.AUTH_PATH
    return tool_home() / "auth.json"


def state_path() -> Path:
    mod = sys.modules.get("cli.agy_provider") or sys.modules.get("agy_provider")
    if mod and hasattr(mod, "STATE_PATH"):
        return mod.STATE_PATH
    return state_dir() / "state.json"


def recent_path() -> Path:
    mod = sys.modules.get("cli.agy_provider") or sys.modules.get("agy_provider")
    if mod and hasattr(mod, "RECENT_PATH"):
        return mod.RECENT_PATH
    return state_dir() / "recent.json"


def lock_path() -> Path:
    mod = sys.modules.get("cli.agy_provider") or sys.modules.get("agy_provider")
    if mod and hasattr(mod, "LOCK_PATH"):
        return mod.LOCK_PATH
    return state_dir() / "agy-provider.lock"


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
    token_data: dict[str, Any]


@dataclass(frozen=True)
class StoreState:
    current: str
    accounts: dict[str, AccountState]


def extract_account_info(token_data: dict[str, Any]) -> tuple[str, str, str]:
    email = ""
    name = ""
    auth_method = str(token_data.get("auth_method", ""))

    id_token = token_data.get("id_token")
    if isinstance(id_token, str) and id_token.count(".") == 2:
        try:
            import base64

            payload_b64 = id_token.split(".")[1]
            padding = 4 - (len(payload_b64) % 4)
            if padding != 4:
                payload_b64 += "=" * padding
            decoded = base64.urlsafe_b64decode(payload_b64).decode("utf-8")
            payload = json.loads(decoded)
            if isinstance(payload, dict):
                email = str(payload.get("email", ""))
                name = str(payload.get("name", ""))
        except Exception:
            pass

    return email, name, auth_method


def load_store() -> StoreState:
    state_file = state_path()
    if not state_file.exists():
        return StoreState(current="", accounts={})
    try:
        raw = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SwitchError(f"invalid agy state JSON: {state_file}: {exc}") from exc

    if not isinstance(raw, dict):
        raise SwitchError(f"agy state file must contain an object: {state_file}")

    current = str(raw.get("current", ""))
    accounts_raw = raw.get("accounts", {})
    if not isinstance(accounts_raw, dict):
        accounts_raw = {}

    accounts: dict[str, AccountState] = {}
    for acc_name, acc_info in accounts_raw.items():
        if isinstance(acc_info, dict):
            token_data = acc_info.get("token_data", {})
            email, display_name, auth_method = extract_account_info(token_data)
            accounts[acc_name] = AccountState(
                name=acc_name,
                email=acc_info.get("email") or email,
                display_name=acc_info.get("display_name") or display_name,
                auth_method=acc_info.get("auth_method") or auth_method,
                token_data=token_data,
            )

    return StoreState(current=current, accounts=accounts)


def write_wincred_token(token_data: dict[str, Any]) -> None:
    if os.name != "nt":
        return
    try:
        import ctypes
        import ctypes.wintypes as wt

        class CREDENTIAL(ctypes.Structure):
            _fields_ = [
                ("Flags", wt.DWORD),
                ("Type", wt.DWORD),
                ("TargetName", wt.LPWSTR),
                ("Comment", wt.LPWSTR),
                ("LastWritten", wt.FILETIME),
                ("CredentialBlobSize", wt.DWORD),
                ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
                ("Persist", wt.DWORD),
                ("AttributeCount", wt.DWORD),
                ("Attributes", ctypes.c_void_p),
                ("TargetAlias", wt.LPWSTR),
                ("UserName", wt.LPWSTR),
            ]

        blob = json.dumps(token_data, indent=2).encode("utf-8")
        blob_buf = ctypes.create_string_buffer(blob, len(blob))

        cred = CREDENTIAL()
        cred.Type = 1
        cred.TargetName = WINCRED_TARGET
        cred.UserName = WINCRED_USER
        cred.CredentialBlobSize = len(blob)
        cred.CredentialBlob = ctypes.cast(blob_buf, ctypes.POINTER(ctypes.c_byte))
        cred.Persist = 2

        advapi32 = ctypes.windll.advapi32
        if not advapi32.CredWriteW(ctypes.byref(cred), 0):
            with suppress(OSError):
                raise SwitchError(
                    f"CredWrite failed: error {ctypes.get_last_error()}"
                )
    except SwitchError:
        raise
    except Exception:
        pass
