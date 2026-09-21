from __future__ import annotations

from lib.common.errors import SwitchError
from lib.xpx.adapters.agy import AgyAdapter
from lib.xpx.adapters.base import TargetAdapter
from lib.xpx.adapters.claude import ClaudeAdapter
from lib.xpx.adapters.codex import CodexAdapter
from lib.xpx.adapters.cursor import CursorAdapter
from lib.xpx.adapters.opencode import OpenCodeAdapter
from lib.xpx.adapters.pi import PiAdapter

_ADAPTERS: dict[str, TargetAdapter] = {
    "codex": CodexAdapter(),
    "opencode": OpenCodeAdapter(),
    "cursor": CursorAdapter(),
    "claude": ClaudeAdapter(),
    "agy": AgyAdapter(),
    "pi": PiAdapter(),
}


def get_adapter(name: str) -> TargetAdapter:
    normalized = name.strip().lower()
    if normalized not in _ADAPTERS:
        available = ", ".join(sorted(_ADAPTERS.keys()))
        raise SwitchError(
            f"unknown target client: '{name}'. Supported targets: {available}."
        )
    return _ADAPTERS[normalized]


def get_all_adapters() -> dict[str, TargetAdapter]:
    return dict(_ADAPTERS)


def detect_installed_adapters() -> dict[str, TargetAdapter]:
    return {name: adp for name, adp in _ADAPTERS.items() if adp.detect()}
