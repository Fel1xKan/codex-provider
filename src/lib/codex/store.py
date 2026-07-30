from __future__ import annotations

import sys
import tomllib
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lib.common.common_store import FileLockManager, atomic_write_bytes
from lib.common.constants import RUNTIME_PROVIDER_ID, SECRET_FILE_MODE
from lib.common.errors import MissingConfigError, SwitchError
from lib.common.toml_config import (
    format_toml_value,
    parse_provider_section,
    validate_provider_name,
)


def _get_mod_attr(attr: str, default: Any) -> Any:
    mod = sys.modules.get("cli.codex_provider") or sys.modules.get("codex_provider")
    return getattr(mod, attr, default) if mod else default


def tool_home() -> Path:
    return _get_mod_attr("TOOL_HOME", Path.home() / ".codex-provider")


def tool_config_path() -> Path:
    return _get_mod_attr("TOOL_CONFIG_PATH", tool_home() / "config.toml")


def auth_store_dir(*, create: bool = True) -> Path:
    d = _get_mod_attr("AUTH_STORE_DIR", tool_home() / "auth")
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def auth_profile_path(provider: str, *, create: bool = False) -> Path:
    return auth_store_dir(create=create) / f"{validate_provider_name(provider)}.json"


def recent_path() -> Path:
    return _get_mod_attr("RECENT_PATH", tool_home() / "recent.json")


def default_codex_dir() -> Path:
    return _get_mod_attr("DEFAULT_CODEX_DIR", Path.home() / ".codex")


_state_lock_mgr: FileLockManager | None = None


def get_state_lock_mgr() -> FileLockManager:
    global _state_lock_mgr
    lpath = tool_home() / ".lock"
    if _state_lock_mgr is None:
        _state_lock_mgr = FileLockManager(lpath)
    else:
        _state_lock_mgr.lock_path = lpath
    return _state_lock_mgr


@contextmanager
def state_lock() -> Iterator[None]:
    mgr = get_state_lock_mgr()
    mgr.acquire()
    try:
        yield
    finally:
        mgr.release()


@dataclass(frozen=True)
class ProviderState:
    path: Path
    codex_dir: Path
    active_provider: str
    providers: dict[str, dict[str, Any]]


def parse_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise MissingConfigError(f"missing config file: {path}")
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise SwitchError(f"invalid TOML: {path}: {exc}") from exc


def ensure_tool_home() -> None:
    tool_home().mkdir(parents=True, exist_ok=True)
    auth_store_dir(create=False).mkdir(parents=True, exist_ok=True)


def ensure_tool_config() -> dict[str, Any]:
    ensure_tool_home()
    cfg_path = tool_config_path()
    if cfg_path.exists():
        return read_tool_config()
    cdir = format_toml_value(str(default_codex_dir()))
    payload = f"# codex-provider tool config\ncodex_dir = {cdir}\n"
    atomic_write_bytes(
        cfg_path, payload.encode("utf-8"), secret=True, mode=SECRET_FILE_MODE
    )
    return {"codex_dir": str(default_codex_dir())}


def read_tool_config() -> dict[str, Any]:
    return parse_toml(tool_config_path())


def resolve_codex_dir(
    data: dict[str, Any] | None = None, *, create: bool = False
) -> Path:
    if data is None:
        data = ensure_tool_config() if create else {}
    configured = data.get("codex_dir")
    if configured in (None, ""):
        codex_dir = default_codex_dir()
    elif isinstance(configured, str):
        codex_dir = Path(configured).expanduser()
    else:
        raise SwitchError(f"invalid codex_dir in config: {configured!r}")
    if create:
        codex_dir.mkdir(parents=True, exist_ok=True)
    return codex_dir


get_codex_dir = resolve_codex_dir
get_tool_config = ensure_tool_config


def runtime_config_path(codex_dir: Path | None = None, *, create: bool = False) -> Path:
    cdir = resolve_codex_dir(create=create) if codex_dir is None else codex_dir
    return cdir / "config.toml"


def runtime_auth_path(codex_dir: Path | None = None, *, create: bool = False) -> Path:
    cdir = resolve_codex_dir(create=create) if codex_dir is None else codex_dir
    return cdir / "auth.json"


def load_runtime_config(
    codex_dir: Path | None = None,
) -> tuple[str, dict[str, Any], Path]:
    if codex_dir is None:
        codex_dir = resolve_codex_dir()
    r_config = runtime_config_path(codex_dir)
    if not r_config.exists():
        return "", {}, r_config
    data = parse_toml(r_config)
    current = data.get("model_provider")
    return current if isinstance(current, str) else "", data, r_config


def load_provider_registry(
    data: dict[str, Any] | None = None,
) -> tuple[Path, dict[str, dict[str, Any]]]:
    state = load_provider_state(data=data, read_only=True)
    return state.codex_dir, state.providers


def load_active_provider(
    codex_dir: Path | None = None,
    providers: dict[str, dict[str, Any]] | None = None,
    data: dict[str, Any] | None = None,
) -> str:
    if data is not None and isinstance(data.get("active_provider"), str):
        return data["active_provider"]
    r_config = runtime_config_path(codex_dir)
    if not r_config.exists():
        return ""
    try:
        runtime_data = parse_toml(r_config)
    except MissingConfigError:
        return ""

    configured = runtime_data.get("model_provider")
    if isinstance(configured, str) and configured and configured != RUNTIME_PROVIDER_ID:
        runtime_providers = parse_provider_section(runtime_data)
        if configured not in runtime_providers and (
            providers is None or configured not in providers
        ):
            raise SwitchError(
                f"current provider '{configured}' is missing from "
                "runtime provider blocks"
            )
        return configured
    return ""


def migrate_provider_registry(dry_run: bool = False) -> int:
    load_provider_state(read_only=dry_run)
    return 0


def load_provider_state(
    data: dict[str, Any] | None = None, *, read_only: bool = False
) -> ProviderState:
    cfg_path = tool_config_path()
    if data is None:
        if cfg_path.exists():
            data = read_tool_config()
        elif read_only:
            data = {}
        else:
            data = ensure_tool_config()
    codex_dir = resolve_codex_dir(data, create=False)
    providers = parse_provider_section(data)
    if not providers:
        r_config = runtime_config_path(codex_dir)
        if r_config.exists():
            with suppress(MissingConfigError):
                providers = parse_provider_section(parse_toml(r_config))

    active = load_active_provider(codex_dir, providers, data=data)
    if not read_only and active and active in providers:
        from lib.codex.switch import migrate_runtime_config

        migrate_runtime_config(cfg_path, codex_dir, active, providers)

    return ProviderState(
        path=cfg_path,
        codex_dir=codex_dir,
        active_provider=active,
        providers=providers,
    )


def ensure_provider_state(*, read_only: bool = False) -> ProviderState:
    if read_only:
        return load_provider_state(read_only=True)
    with state_lock():
        return load_provider_state()
