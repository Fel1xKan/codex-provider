#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

from lib.cursor.backend import (
    build_parser,
    main,
)
from lib.cursor.commands import (
    add_account,
    delete_account,
    print_list,
    print_status,
    rename_account,
    switch_account,
)
from lib.cursor.store import (
    ACCOUNT_PATTERN,
    AccountState,
    StoreState,
    acquire_lock,
    extract_account_info,
    load_store,
    release_lock,
)

HOME = Path.home()
CURSOR_DIR = (
    HOME / "AppData" / "Roaming" / "Cursor"
    if sys.platform == "win32"
    else HOME / "Library" / "Application Support" / "Cursor"
    if sys.platform == "darwin"
    else HOME / ".config" / "Cursor"
)
DB_PATH = CURSOR_DIR / "User" / "globalStorage" / "state.vscdb"

TOOL_HOME = HOME / ".cursor-provider"
DATA_DIR = TOOL_HOME
STATE_DIR = TOOL_HOME / "state"
AUTH_PATH = TOOL_HOME / "auth.json"
STATE_PATH = STATE_DIR / "state.json"
RECENT_PATH = STATE_DIR / "recent.json"
LOCK_PATH = STATE_DIR / "cursor-provider.lock"

__all__ = [
    "ACCOUNT_PATTERN",
    "AUTH_PATH",
    "AccountState",
    "CURSOR_DIR",
    "DATA_DIR",
    "DB_PATH",
    "HOME",
    "LOCK_PATH",
    "RECENT_PATH",
    "STATE_DIR",
    "STATE_PATH",
    "StoreState",
    "TOOL_HOME",
    "acquire_lock",
    "add_account",
    "build_parser",
    "delete_account",
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
