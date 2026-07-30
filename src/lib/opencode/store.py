from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import json5

from lib.common.common_store import FileLockManager
from lib.common.errors import SwitchError

CONFIG_NAMES = (
    "opencode.json",
    "opencode.jsonc",
    "opencode.json5",
    "opencode.config.json",
    "opencode.config.jsonc",
    "opencode.config.json5",
)

PROVIDER_PATTERN = re.compile(r"^[a-z0-9_-]+$")


def config_dir() -> Path:
    mod = sys.modules.get("cli.opencode_provider") or sys.modules.get(
        "opencode_provider"
    )
    if mod and hasattr(mod, "CONFIG_DIR"):
        return mod.CONFIG_DIR
    return Path.home() / ".config" / "opencode"


def data_dir() -> Path:
    mod = sys.modules.get("cli.opencode_provider") or sys.modules.get(
        "opencode_provider"
    )
    if mod and hasattr(mod, "DATA_DIR"):
        return mod.DATA_DIR
    return Path.home() / ".local" / "share" / "opencode"


def state_dir() -> Path:
    mod = sys.modules.get("cli.opencode_provider") or sys.modules.get(
        "opencode_provider"
    )
    if mod and hasattr(mod, "STATE_DIR"):
        return mod.STATE_DIR
    return Path.home() / ".local" / "state" / "opencode"


def auth_path() -> Path:
    mod = sys.modules.get("cli.opencode_provider") or sys.modules.get(
        "opencode_provider"
    )
    if mod and hasattr(mod, "AUTH_PATH"):
        return mod.AUTH_PATH
    return data_dir() / "auth.json"


def model_state_path() -> Path:
    mod = sys.modules.get("cli.opencode_provider") or sys.modules.get(
        "opencode_provider"
    )
    if mod and hasattr(mod, "MODEL_STATE_PATH"):
        return mod.MODEL_STATE_PATH
    return state_dir() / "model.json"


def lock_path() -> Path:
    mod = sys.modules.get("cli.opencode_provider") or sys.modules.get(
        "opencode_provider"
    )
    if mod and hasattr(mod, "LOCK_PATH"):
        return mod.LOCK_PATH
    return state_dir() / "opencode-provider.lock"


def recent_path() -> Path:
    mod = sys.modules.get("cli.opencode_provider") or sys.modules.get(
        "opencode_provider"
    )
    if mod and hasattr(mod, "RECENT_PATH"):
        return mod.RECENT_PATH
    return state_dir() / "opencode-provider-recent.json"


lock_mgr = FileLockManager(lock_path())


def acquire_lock() -> None:
    lock_mgr.lock_path = lock_path()
    lock_mgr.acquire()


def release_lock() -> None:
    lock_mgr.release()


@dataclass(frozen=True)
class Token:
    kind: str
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class ConfigState:
    path: Path
    text: str
    data: dict[str, Any]
    providers: dict[str, dict[str, Any]]
    current_provider: str | None
    current_model: str | None
    model_source: str


def config_path(*, create: bool = True) -> Path:
    cdir = config_dir()
    for name in CONFIG_NAMES:
        candidate = cdir / name
        if candidate.exists():
            return candidate
    if create:
        cdir.mkdir(parents=True, exist_ok=True)
        default = cdir / "opencode.json"
        if not default.exists():
            default.write_text("{}\n", encoding="utf-8")
        return default
    return cdir / "opencode.json"


def read_jsonc(path: Path) -> tuple[str, dict[str, Any]]:
    if not path.exists():
        raise SwitchError(f"OpenCode config not found: {path}")
    try:
        text = path.read_text(encoding="utf-8")
        data = json5.loads(text)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise SwitchError(f"invalid OpenCode config JSON: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SwitchError(f"OpenCode config must contain an object: {path}")
    return text, data


def split_model(
    configured_model: str | None,
) -> tuple[str | None, str | None]:
    if not configured_model or "/" not in configured_model:
        return None, None
    provider, model = configured_model.split("/", 1)
    return provider or None, model or None


def provider_models(state: ConfigState, provider: str) -> dict[str, dict[str, Any]]:
    config = state.providers.get(provider, {})
    raw_models = config.get("models")
    if not isinstance(raw_models, dict):
        return {}
    return {
        name: model
        for name, model in raw_models.items()
        if isinstance(name, str) and isinstance(model, dict)
    }


def provider_is_enabled(
    state: ConfigState, provider: str, config: dict[str, Any]
) -> bool:
    disabled = state.data.get("disabled_providers")
    if isinstance(disabled, list) and provider in disabled:
        return False
    enabled = state.data.get("enabled_providers")
    if isinstance(enabled, list) and provider not in enabled:
        return False
    return config.get("enabled") is not False


def load_auth_provider_ids() -> set[str]:
    apath = auth_path()
    if not apath.exists():
        return set()
    try:
        data = json.loads(apath.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SwitchError(f"invalid OpenCode auth JSON: {apath}: {exc}") from exc
    if not isinstance(data, dict):
        raise SwitchError(f"OpenCode auth file must contain an object: {apath}")
    return set(data.keys())


def load_auth_keys() -> dict[str, list[str]]:
    keys: dict[str, list[str]] = {}
    apath = auth_path()
    if apath.exists():
        try:
            data = json.loads(apath.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for provider, entry in data.items():
                    if isinstance(entry, dict):
                        key = entry.get("key")
                        if isinstance(key, str) and key:
                            keys.setdefault(provider, []).append(key)
        except Exception as exc:
            raise SwitchError(f"invalid OpenCode auth JSON: {apath}: {exc}") from exc

    try:
        state = load_state()
        for provider, pconfig in state.providers.items():
            if provider not in keys:
                options = pconfig.get("options")
                if isinstance(options, dict):
                    api_key = options.get("apiKey")
                    if isinstance(api_key, str) and api_key:
                        keys.setdefault(provider, []).append(api_key)
    except Exception:
        pass

    return keys


def provider_has_auth(
    provider: str, config: dict[str, Any], auth_provider_ids: set[str]
) -> str:
    if provider in auth_provider_ids:
        return "yes"
    options = config.get("options")
    if isinstance(options, dict) and isinstance(options.get("apiKey"), str):
        return "yes"
    return "no"


def load_state() -> ConfigState:
    path = config_path()
    text, data = read_jsonc(path)
    raw_providers = data.get("provider")
    providers: dict[str, dict[str, Any]] = {}
    if isinstance(raw_providers, dict):
        for name, config in raw_providers.items():
            if isinstance(name, str) and isinstance(config, dict):
                providers[name] = config

    configured_model = data.get("model")
    current_provider, current_model = split_model(
        configured_model if isinstance(configured_model, str) else None
    )
    source = "config"
    mpath = model_state_path()
    if not current_provider and mpath.exists():
        try:
            mdata = json.loads(mpath.read_text(encoding="utf-8"))
            if isinstance(mdata, dict):
                state_model = mdata.get("model")
                if isinstance(state_model, str):
                    sp, sm = split_model(state_model)
                    if sp:
                        current_provider, current_model = sp, sm
                        source = "recent model"
                elif isinstance(mdata.get("recent"), list):
                    for item in mdata["recent"]:
                        if isinstance(item, dict):
                            pid = item.get("providerID")
                            mid = item.get("modelID")
                            if pid in providers:
                                current_provider = pid
                                current_model = mid
                                source = "recent model"
                                break
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            pass

    return ConfigState(
        path=path,
        text=text,
        data=data,
        providers=providers,
        current_provider=current_provider,
        current_model=current_model,
        model_source=source,
    )
