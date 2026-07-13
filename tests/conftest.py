from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

import codex_provider as cp


@dataclass(frozen=True)
class IsolatedPaths:
    home: Path
    tool_home: Path
    tool_config: Path
    auth_store: Path
    codex_dir: Path


@pytest.fixture
def isolated_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> IsolatedPaths:
    tool_home = tmp_path / ".codex-provider"
    codex_dir = tmp_path / ".codex"
    paths = IsolatedPaths(
        home=tmp_path,
        tool_home=tool_home,
        tool_config=tool_home / "config.toml",
        auth_store=tool_home / "auth",
        codex_dir=codex_dir,
    )
    monkeypatch.setattr(cp, "TOOL_HOME", paths.tool_home)
    monkeypatch.setattr(cp, "TOOL_CONFIG_PATH", paths.tool_config)
    monkeypatch.setattr(cp, "AUTH_STORE_DIR", paths.auth_store)
    monkeypatch.setattr(cp, "DEFAULT_CODEX_DIR", paths.codex_dir)
    monkeypatch.setattr(cp, "_lock_depth", 0)
    monkeypatch.setattr(cp, "_lock_file", None)
    return paths


@pytest.fixture
def initialized_registry(isolated_paths: IsolatedPaths) -> IsolatedPaths:
    cp.add_provider(
        provider="alpha",
        base_url="https://alpha.example.com",
        api_key="placeholder-alpha-key",
        display_name="Alpha",
        wire_api="responses",
        supports_websockets=False,
        dry_run=False,
    )
    cp.add_provider(
        provider="beta",
        base_url="https://beta.example.com",
        api_key="placeholder-beta-key",
        display_name="Beta",
        wire_api="responses",
        supports_websockets=True,
        dry_run=False,
    )
    cp.switch_provider("alpha", dry_run=False)
    return isolated_paths
