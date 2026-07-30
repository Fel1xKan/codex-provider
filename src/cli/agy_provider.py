#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

from lib.agy.admin import (
    auth_detail,
    auth_edit,
    config_detail,
    config_edit,
    doctor_command,
)
from lib.agy.backend import (
    build_parser,
    main,
)
from lib.agy.commands import (
    add_account,
    delete_account,
    print_list,
    print_status,
    rename_account,
    switch_account,
)
from lib.agy.store import (
    ACCOUNT_PATTERN,
    AccountState,
    StoreState,
    acquire_lock,
    extract_account_info,
    load_store,
    release_lock,
)

HOME = Path.home()
GEMINI_DIR = HOME / ".gemini"
CLI_DIR = GEMINI_DIR / "antigravity-cli"
CONFIG_DIR = GEMINI_DIR / "config"
OAUTH_TOKEN_PATH = CLI_DIR / "antigravity-oauth-token"
CONFIG_PATH = CONFIG_DIR / "config.json"
SETTINGS_PATH = CLI_DIR / "settings.json"

TOOL_HOME = GEMINI_DIR / "agy-provider"
DATA_DIR = TOOL_HOME
STATE_DIR = TOOL_HOME / "state"
AUTH_PATH = TOOL_HOME / "auth.json"
STATE_PATH = STATE_DIR / "state.json"
RECENT_PATH = STATE_DIR / "recent.json"
LOCK_PATH = STATE_DIR / "agy-provider.lock"

_lock_depth = 0
_lock_file = None

__all__ = [
    "ACCOUNT_PATTERN",
    "AUTH_PATH",
    "AccountState",
    "CLI_DIR",
    "CONFIG_DIR",
    "CONFIG_PATH",
    "DATA_DIR",
    "GEMINI_DIR",
    "HOME",
    "LOCK_PATH",
    "OAUTH_TOKEN_PATH",
    "RECENT_PATH",
    "SETTINGS_PATH",
    "STATE_DIR",
    "STATE_PATH",
    "StoreState",
    "TOOL_HOME",
    "_lock_depth",
    "_lock_file",
    "acquire_lock",
    "add_account",
    "auth_detail",
    "auth_edit",
    "build_parser",
    "config_detail",
    "config_edit",
    "delete_account",
    "doctor_command",
    "extract_account_info",
    "load_store",
    "main",
    "print_list",
    "print_status",
    "release_lock",
    "rename_account",
    "switch_account",
]

if __name__ == "__main__":
    sys.exit(main())
