from __future__ import annotations

from pathlib import Path

from codex_provider_lib.recent import (
    forget_recent_provider,
    load_recent_providers,
    record_recent_provider,
    rename_recent_provider,
    sort_providers_by_recent,
)


def test_record_and_sort_recent_providers(tmp_path: Path) -> None:
    path = tmp_path / "recent.json"
    record_recent_provider(path, "alpha")
    record_recent_provider(path, "beta")
    record_recent_provider(path, "alpha")
    assert load_recent_providers(path) == ["alpha", "beta"]
    assert sort_providers_by_recent(
        ["gamma", "beta", "alpha"], load_recent_providers(path)
    ) == [
        "alpha",
        "beta",
        "gamma",
    ]
    rename_recent_provider(path, "alpha", "omega")
    assert load_recent_providers(path) == ["omega", "beta"]
    forget_recent_provider(path, "beta")
    assert load_recent_providers(path) == ["omega"]
