"""Legacy and native configuration discovery, one module per client."""

from __future__ import annotations

from pathlib import Path

from . import antigravity, claude, codex, cursor, opencode, pi
from .common import WELL_KNOWN_BASE_URLS, DiscoveredItem, StateMap

__all__ = [
    "DiscoveredItem",
    "StateMap",
    "WELL_KNOWN_BASE_URLS",
    "collect_legacy_items",
]

_COLLECTORS = (
    codex.collect,
    opencode.collect,
    claude.collect,
    cursor.collect,
    antigravity.collect,
    pi.collect,
)


def collect_legacy_items() -> tuple[list[DiscoveredItem], StateMap]:
    """Scan the local machine and collect configurations from all six clients."""
    items: list[DiscoveredItem] = []
    states: StateMap = {}
    home = Path.home()
    for collect in _COLLECTORS:
        collect(items, states, home)
    return items, states
