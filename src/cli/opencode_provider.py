#!/usr/bin/env python3
from __future__ import annotations

import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

import lib.opencode.backend as op_be
import lib.opencode.commands as op_cmd
import lib.opencode.ping as op_ping
from lib.common.network import run_models_test as net_run_models_test
from lib.common.platform import run_editor
from lib.common.recent import load_recent_providers
from lib.opencode.admin import (
    doctor_command as doctor,
)
from lib.opencode.admin import (
    edit_auth,
    edit_config,
    show_auth,
    show_config,
)
from lib.opencode.backend import (
    build_parser,
    main,
)
from lib.opencode.edit import (
    add_provider,
    delete_provider,
    rename_provider,
)
from lib.opencode.models import (
    add_models_parser,
    models_command,
)
from lib.opencode.patch import (
    patch_add_provider,
    patch_default_model,
    patch_delete_provider,
    patch_provider_models,
    patch_rename_provider,
)

CONFIG_DIR = Path.home() / ".config" / "opencode"
DATA_DIR = Path.home() / ".local" / "share" / "opencode"
STATE_DIR = Path.home() / ".local" / "state" / "opencode"
AUTH_PATH = DATA_DIR / "auth.json"
MODEL_STATE_PATH = STATE_DIR / "model.json"
LOCK_PATH = STATE_DIR / "opencode-provider.lock"
RECENT_PATH = STATE_DIR / "opencode-provider-recent.json"

_lock_depth = 0
_lock_file = None

read_api_key = op_be.read_api_key
run_models_test = net_run_models_test
ping_provider = op_ping.ping_provider
switch_provider = op_cmd.switch_provider

__all__ = [
    "AUTH_PATH",
    "CONFIG_DIR",
    "DATA_DIR",
    "LOCK_PATH",
    "MODEL_STATE_PATH",
    "RECENT_PATH",
    "_lock_depth",
    "_lock_file",
    "add_models_parser",
    "add_provider",
    "build_parser",
    "delete_provider",
    "doctor",
    "edit_auth",
    "edit_config",
    "load_recent_providers",
    "main",
    "models_command",
    "patch_add_provider",
    "patch_default_model",
    "patch_delete_provider",
    "patch_provider_models",
    "patch_rename_provider",
    "ping_provider",
    "read_api_key",
    "rename_provider",
    "run_editor",
    "run_models_test",
    "shutil",
    "show_auth",
    "show_config",
    "subprocess",
    "switch_provider",
    "urllib",
]

if __name__ == "__main__":
    sys.exit(main())
