from __future__ import annotations

import os
from pathlib import Path

from lib.common.common_store import FileLockManager, ensure_private_dir

_lock_managers: dict[Path, FileLockManager] = {}


def get_xpx_home() -> Path:
    """Return the root directory for xpx storage (~/.xpx or XPX_HOME)."""
    override = os.environ.get("XPX_HOME")
    if override:
        return Path(override)
    return Path.home() / ".xpx"


xpx_home = get_xpx_home


def ensure_xpx_dirs() -> Path:
    """Ensure all standard subdirectories exist with 0o700 permissions."""
    home = get_xpx_home()
    ensure_private_dir(home)
    ensure_private_dir(home / "providers")
    ensure_private_dir(home / "accounts")
    ensure_private_dir(home / "catalogs")
    ensure_private_dir(home / "backups")
    return home


def xpx_lock() -> FileLockManager:
    """Return a shared FileLockManager on ~/.xpx/.lock."""
    home = get_xpx_home()
    ensure_private_dir(home)
    lock_path = home / ".lock"
    if lock_path not in _lock_managers:
        _lock_managers[lock_path] = FileLockManager(lock_path)
    return _lock_managers[lock_path]
