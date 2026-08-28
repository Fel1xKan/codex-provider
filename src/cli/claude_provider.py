#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

import lib.claude.backend as cl_be
import lib.claude.doctor as cl_doc
import lib.claude.edit as cl_ed
import lib.claude.store as cl_st
from lib.claude.backend import read_api_key
from lib.common.common_store import (
    FileChange,
    FileSnapshot,
    atomic_write_bytes,
    chmod_if_supported,
    ensure_private_dir,
    fsync_directory,
    restore_file_snapshot,
    snapshot_file,
)
from lib.common.network import run_models_test
from lib.common.platform import run_editor, select_provider_interactive

TOOL_HOME = Path.home() / ".claude-provider"
TOOL_CONFIG_PATH = TOOL_HOME / "config.json"
AUTH_STORE_DIR = TOOL_HOME / "auth"
RECENT_PATH = TOOL_HOME / "recent.json"
DEFAULT_SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
MODELS_DIR = TOOL_HOME / "models"

ProviderState = cl_st.ProviderState
add_provider = cl_ed.add_provider
build_parser = cl_be.build_parser
delete_provider = cl_ed.delete_provider
doctor = cl_doc.doctor
ensure_provider_state = cl_st.ensure_provider_state
ensure_tool_config = cl_st.ensure_tool_config
ensure_tool_home = cl_st.ensure_tool_home
get_settings_path = cl_st.settings_path
get_tool_config = cl_st.read_tool_config
load_auth_json = cl_doc.load_auth_json
load_provider_state = cl_st.load_provider_state
main = cl_be.main
read_tool_config = cl_st.read_tool_config
state_lock = cl_st.state_lock

__all__ = [
    "AUTH_STORE_DIR",
    "DEFAULT_SETTINGS_PATH",
    "FileChange",
    "FileSnapshot",
    "MODELS_DIR",
    "ProviderState",
    "RECENT_PATH",
    "TOOL_CONFIG_PATH",
    "TOOL_HOME",
    "add_provider",
    "atomic_write_bytes",
    "build_parser",
    "chmod_if_supported",
    "delete_provider",
    "doctor",
    "ensure_private_dir",
    "ensure_provider_state",
    "ensure_tool_config",
    "ensure_tool_home",
    "fsync_directory",
    "get_settings_path",
    "get_tool_config",
    "load_auth_json",
    "load_provider_state",
    "main",
    "read_api_key",
    "read_tool_config",
    "restore_file_snapshot",
    "run_editor",
    "run_models_test",
    "select_provider_interactive",
    "snapshot_file",
    "state_lock",
]


if __name__ == "__main__":
    import sys

    sys.exit(main())
