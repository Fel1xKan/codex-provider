from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lib.common.constants import DEFAULT_FILE_MODE, SECRET_FILE_MODE
from lib.common.errors import SwitchError

try:
    import fcntl
except ImportError:
    fcntl = None

try:
    import msvcrt
except ImportError:
    msvcrt = None


def chmod_if_supported(path: Path, mode: int) -> None:
    if os.name == "posix":
        with suppress(OSError):
            path.chmod(mode)


def ensure_private_dir(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
        chmod_if_supported(path, 0o700)
    except OSError as exc:
        raise SwitchError(f"unable to create private directory {path}: {exc}") from exc


def fsync_directory(path: Path) -> None:
    if os.name != "posix":
        return
    try:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


@dataclass(frozen=True)
class FileSnapshot:
    exists: bool
    payload: bytes | None
    mode: int | None


@dataclass(frozen=True)
class FileChange:
    path: Path
    payload: bytes | None
    secret: bool = False


def snapshot_file(path: Path) -> FileSnapshot:
    try:
        if not path.exists():
            return FileSnapshot(False, None, None)
        return FileSnapshot(True, path.read_bytes(), path.stat().st_mode & 0o777)
    except OSError as exc:
        raise SwitchError(f"unable to snapshot {path}: {exc}") from exc


def restore_file_snapshot(path: Path, snapshot: FileSnapshot) -> None:
    if snapshot.exists:
        atomic_write_bytes(
            path,
            snapshot.payload or b"",
            mode=snapshot.mode,
            secret=path.name == "auth.json",
        )
        return
    try:
        path.unlink(missing_ok=True)
        if path.parent.exists():
            fsync_directory(path.parent)
    except OSError as exc:
        raise SwitchError(f"unable to remove {path} during rollback: {exc}") from exc


def apply_changes(changes: Sequence[FileChange]) -> None:
    snapshots = [(change, snapshot_file(change.path)) for change in changes]
    committed: list[tuple[Any, FileSnapshot]] = []

    for change, before in snapshots:
        committed.append((change.path, before))
        try:
            if change.payload is None:
                change.path.unlink(missing_ok=True)
                if change.path.parent.exists():
                    fsync_directory(change.path.parent)
            else:
                atomic_write_bytes(
                    change.path,
                    change.payload,
                    secret=change.secret,
                    mode=SECRET_FILE_MODE if change.secret else None,
                )
        except Exception as exc:
            for path, before in reversed(committed):
                restore_file_snapshot(path, before)
            raise SwitchError(f"unable to commit state changes: {exc}") from exc


def default_atomic_write_bytes(
    path: Path,
    data: bytes,
    *,
    secret: bool = False,
    mode: int | None = None,
) -> None:
    ensure_private_dir(path.parent)
    target_mode = mode or (SECRET_FILE_MODE if secret else DEFAULT_FILE_MODE)

    pid = os.getpid()
    tmp_path = None
    try:
        tmp_path = path.with_name(f".tmp.{path.name}.{pid}")

        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY

        fd = os.open(tmp_path, flags, target_mode)
        try:
            chmod_if_supported(tmp_path, target_mode)
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)

        chmod_if_supported(tmp_path, target_mode)
        os.replace(tmp_path, path)
        tmp_path = None
        if secret:
            chmod_if_supported(path, SECRET_FILE_MODE)
        fsync_directory(path.parent)
    except OSError as exc:
        raise SwitchError(f"unable to write {path}: {exc}") from exc
    finally:
        if tmp_path is not None:
            with suppress(OSError):
                tmp_path.unlink(missing_ok=True)


def atomic_write_bytes(
    path: Path,
    data: bytes,
    *,
    secret: bool = False,
    mode: int | None = None,
) -> None:
    mod = (
        sys.modules.get("cli.codex_provider")
        or sys.modules.get("codex_provider")
        or sys.modules.get("cli.opencode_provider")
        or sys.modules.get("opencode_provider")
    )
    if (
        mod
        and hasattr(mod, "atomic_write_bytes")
        and mod.atomic_write_bytes is not None
    ):
        func = mod.atomic_write_bytes
        if func is not atomic_write_bytes and not getattr(func, "_in_call", False):
            try:
                func._in_call = True
                return func(path, data, secret=secret, mode=mode)
            finally:
                func._in_call = False
    default_atomic_write_bytes(path, data, secret=secret, mode=mode)


class FileLockManager:
    def __init__(self, lock_path: Path) -> None:
        self.lock_path = lock_path
        self._lock_depth = 0
        self._lock_file: Any = None

    def acquire(self) -> None:
        if self._lock_depth > 0:
            self._lock_depth += 1
            return

        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_file = self.lock_path.open("a+b")
        try:
            if os.name == "nt" and msvcrt:
                lock_file.seek(0, os.SEEK_END)
                if lock_file.tell() == 0:
                    lock_file.write(b"0")
                    lock_file.flush()
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
            elif fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            else:
                raise SwitchError("file locking is not supported on this platform")
            self._lock_file = lock_file
            self._lock_depth = 1
        except OSError as exc:
            lock_file.close()
            raise SwitchError(f"unable to lock state: {exc}") from exc

    def release(self) -> None:
        if self._lock_depth > 1:
            self._lock_depth -= 1
            return

        if self._lock_depth == 1:
            self._lock_depth = 0
            if self._lock_file:
                try:
                    if os.name == "nt" and msvcrt:
                        self._lock_file.seek(0)
                        msvcrt.locking(self._lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                    elif fcntl is not None:
                        fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
                self._lock_file.close()
                self._lock_file = None

    def __enter__(self) -> FileLockManager:
        self.acquire()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.release()
