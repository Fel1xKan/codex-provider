#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

import lib.codex.admin as cx_adm
import lib.codex.backend as cx_be
import lib.codex.doctor as cx_doc
import lib.codex.edit as cx_ed
import lib.codex.store as cx_st
import lib.codex.switch as cx_sw
from lib.codex.admin import temporary_provider
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
from lib.common.constants import RUNTIME_PROVIDER_ID
from lib.common.errors import SwitchError
from lib.common.network import (
    normalize_base_url,
)
from lib.common.network import (
    run_models_test as net_run_models_test,
)
from lib.common.platform import (
    run_editor,
    select_provider_interactive,
)
from lib.common.recent import load_recent_providers
from lib.common.toml_config import (
    format_toml_value,
    render_runtime_config,
    render_tool_config,
)

TOOL_HOME = Path.home() / ".codex-provider"
TOOL_CONFIG_PATH = TOOL_HOME / "config.toml"
AUTH_STORE_DIR = TOOL_HOME / "auth"
RECENT_PATH = TOOL_HOME / "recent.json"
DEFAULT_CODEX_DIR = Path.home() / ".codex"

_lock_depth = 0
_lock_file = None

run_models_test = net_run_models_test
run_codex_ping = cx_doc.run_codex_ping

ProviderState = cx_st.ProviderState
add_provider = cx_ed.add_provider
auth_profile_path = cx_st.auth_profile_path
auth_store_dir = cx_st.auth_store_dir
build_parser = cx_be.build_parser
commit_file_changes = cx_sw.commit_file_changes
delete_provider = cx_ed.delete_provider
doctor = cx_doc.doctor
edit_auth = cx_adm.edit_auth
edit_provider_config = cx_adm.edit_provider_config
ensure_provider_state = cx_st.ensure_provider_state
ensure_registry_ready = cx_adm.ensure_registry_ready
ensure_tool_config = cx_st.ensure_tool_config
ensure_tool_home = cx_st.ensure_tool_home
get_codex_dir = cx_st.get_codex_dir
get_tool_config = cx_st.get_tool_config
load_auth_json = cx_doc.load_auth_json
load_provider_registry = cx_st.load_provider_registry
load_provider_state = cx_st.load_provider_state
load_runtime_config = cx_st.load_runtime_config
main = cx_be.main
migrate_provider_registry = cx_st.migrate_provider_registry
parse_toml = cx_st.parse_toml
ping_provider = cx_be.ping_provider
print_list = cx_adm.print_list
print_status = cx_adm.print_status
read_api_key = cx_be.read_api_key
read_tool_config = cx_st.read_tool_config
rename_provider = cx_ed.rename_provider
resolve_provider = cx_adm.resolve_provider
runtime_auth_path = cx_st.runtime_auth_path
runtime_config_path = cx_st.runtime_config_path
show_auth = cx_adm.show_auth
show_provider_config = cx_adm.show_provider_config
state_lock = cx_st.state_lock
switch_provider = cx_sw.switch_provider
test_provider = cx_adm.test_provider

__all__ = [
    "AUTH_STORE_DIR",
    "DEFAULT_CODEX_DIR",
    "FileChange",
    "FileSnapshot",
    "ProviderState",
    "RECENT_PATH",
    "RUNTIME_PROVIDER_ID",
    "SwitchError",
    "TOOL_CONFIG_PATH",
    "TOOL_HOME",
    "_lock_depth",
    "_lock_file",
    "add_provider",
    "atomic_write_bytes",
    "auth_profile_path",
    "auth_store_dir",
    "build_parser",
    "chmod_if_supported",
    "commit_file_changes",
    "delete_provider",
    "doctor",
    "edit_auth",
    "edit_provider_config",
    "ensure_private_dir",
    "ensure_provider_state",
    "ensure_registry_ready",
    "ensure_tool_config",
    "ensure_tool_home",
    "format_toml_value",
    "fsync_directory",
    "get_codex_dir",
    "get_tool_config",
    "load_auth_json",
    "load_provider_registry",
    "load_provider_state",
    "load_recent_providers",
    "load_runtime_config",
    "main",
    "migrate_provider_registry",
    "normalize_base_url",
    "os",
    "parse_toml",
    "ping_provider",
    "print_list",
    "print_status",
    "read_api_key",
    "read_tool_config",
    "rename_provider",
    "render_runtime_config",
    "render_tool_config",
    "resolve_provider",
    "restore_file_snapshot",
    "run_codex_ping",
    "run_editor",
    "run_models_test",
    "runtime_auth_path",
    "runtime_config_path",
    "select_provider_interactive",
    "shutil",
    "show_auth",
    "show_provider_config",
    "snapshot_file",
    "state_lock",
    "subprocess",
    "switch_provider",
    "temporary_provider",
    "test_provider",
    "urllib",
]

if __name__ == "__main__":
    sys.exit(main())
