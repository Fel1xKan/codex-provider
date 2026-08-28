from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import json5

from lib.common.common_store import FileLockManager, atomic_write_bytes
from lib.common.errors import MissingConfigError, SwitchError
from lib.common.jsonc_utils import (
    object_matches,
    tokenize_jsonc,
)
from lib.common.toml_config import validate_provider_name


def _get_mod_attr(attr: str, default: Any) -> Any:
    mod = sys.modules.get("cli.claude_provider") or sys.modules.get("claude_provider")
    return getattr(mod, attr, default) if mod else default


def tool_home() -> Path:
    return _get_mod_attr("TOOL_HOME", Path.home() / ".claude-provider")


def tool_config_path() -> Path:
    return _get_mod_attr("TOOL_CONFIG_PATH", tool_home() / "config.json")


def auth_store_dir(*, create: bool = True) -> Path:
    d = _get_mod_attr("AUTH_STORE_DIR", tool_home() / "auth")
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def auth_profile_path(provider: str, *, create: bool = False) -> Path:
    return auth_store_dir(create=create) / f"{validate_provider_name(provider)}.json"


def recent_path() -> Path:
    return _get_mod_attr("RECENT_PATH", tool_home() / "recent.json")


def default_settings_path() -> Path:
    return _get_mod_attr(
        "DEFAULT_SETTINGS_PATH", Path.home() / ".claude" / "settings.json"
    )


_state_lock_mgr: FileLockManager | None = None


def get_state_lock_mgr() -> FileLockManager:
    global _state_lock_mgr
    lock_path = tool_home() / ".lock"
    if _state_lock_mgr is None:
        _state_lock_mgr = FileLockManager(lock_path)
    else:
        _state_lock_mgr.lock_path = lock_path
    return _state_lock_mgr


@contextmanager
def state_lock() -> Any:
    mgr = get_state_lock_mgr()
    mgr.acquire()
    try:
        yield
    finally:
        mgr.release()


@dataclass(frozen=True)
class ProviderState:
    path: Path
    settings_path: Path
    active_provider: str
    providers: dict[str, dict[str, Any]]


def parse_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise MissingConfigError(f"missing config file: {path}")
    try:
        data = json5.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json5.Json5DecodeError) as exc:
        raise SwitchError(f"invalid JSON: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SwitchError(f"JSON must contain an object: {path}")
    return data


def ensure_tool_config() -> dict[str, Any]:
    ensure_tool_home()
    cfg_path = tool_config_path()
    if cfg_path.exists():
        return read_tool_config()
    payload = (
        json.dumps(
            {
                "settings_path": str(default_settings_path()),
                "providers": {},
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")
    atomic_write_bytes(cfg_path, payload, secret=True, mode=0o600)
    return json.loads(payload.decode("utf-8"))


def read_tool_config() -> dict[str, Any]:
    data = parse_json(tool_config_path())
    if "settings_path" not in data:
        raise SwitchError(f"missing settings_path in tool config: {tool_config_path()}")
    return data


def resolve_settings_path(
    data: dict[str, Any] | None = None, *, create: bool = False
) -> Path:
    if data is None:
        data = ensure_tool_config() if create else {}
    configured = data.get("settings_path")
    if configured in (None, ""):
        settings_path = default_settings_path()
    elif isinstance(configured, str):
        settings_path = Path(configured).expanduser()
    else:
        raise SwitchError(f"invalid settings_path in config: {configured!r}")
    if create:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
    return settings_path


def settings_path(*, create: bool = False) -> Path:
    return resolve_settings_path(create=create)


def read_settings(*, create: bool = False) -> tuple[str, dict[str, Any]]:
    settings_file = settings_path(create=create)
    if not settings_file.exists():
        return "{}", {}
    text = settings_file.read_text(encoding="utf-8")
    try:
        data = json5.loads(text)
    except (OSError, UnicodeDecodeError, json5.Json5DecodeError) as exc:
        raise SwitchError(f"invalid settings JSON: {settings_file}: {exc}") from exc
    if not isinstance(data, dict):
        raise SwitchError(f"settings JSON must contain an object: {settings_file}")
    return text, data


def load_settings_data(*, create: bool = False) -> dict[str, Any]:
    _, data = read_settings(create=create)
    return data


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
    settings_file = resolve_settings_path(data, create=False)
    providers_raw = data.get("providers", {})
    if not isinstance(providers_raw, dict):
        raise SwitchError(f"invalid providers in config: {cfg_path}")
    providers: dict[str, dict[str, Any]] = {}
    for name, config in providers_raw.items():
        if isinstance(name, str) and isinstance(config, dict):
            validate_provider_name(name)
            providers[name] = config

    active = data.get("active_provider")
    if not isinstance(active, str):
        active = ""
    if active and active not in providers:
        active = ""
    return ProviderState(
        path=cfg_path,
        settings_path=settings_file,
        active_provider=active,
        providers=providers,
    )


def ensure_provider_state(*, read_only: bool = False) -> ProviderState:
    if read_only:
        return load_provider_state(read_only=True)
    with state_lock():
        return load_provider_state()


def ensure_tool_home() -> None:
    tool_home().mkdir(parents=True, exist_ok=True)
    auth_store_dir(create=False).mkdir(parents=True, exist_ok=True)


def render_settings_json(
    data: dict[str, Any],
    *,
    base_text: str | None = None,
) -> str:
    if not base_text or not base_text.strip():
        return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    try:
        tokens = tokenize_jsonc(base_text)
        if not tokens or tokens[0].kind != "{" or tokens[-1].kind != "}":
            return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        matches = object_matches(tokens)
        if matches.get(0) != len(tokens) - 1:
            return json.dumps(data, indent=2, ensure_ascii=False) + "\n"

        head = base_text[: tokens[0].start]
        tail = base_text[tokens[-1].end :]
        body = json.dumps(data, indent=2, ensure_ascii=False)[1:-1]
        return head + "{" + body + "}" + tail
    except Exception:
        return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def write_settings(data: dict[str, Any], *, secret: bool = False) -> Path:
    settings_file = settings_path(create=True)
    atomic_write_bytes(
        settings_file,
        json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8"),
        secret=secret,
    )
    return settings_file
