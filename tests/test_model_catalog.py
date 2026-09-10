from __future__ import annotations

import json
from pathlib import Path

import pytest

import lib.common.model_catalog as catalog


def _payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "catalog_version": "test",
        "models": {
            "gpt-test": {
                "display_name": "GPT Test",
                "context_window": 128000,
                "max_output_tokens": 8192,
                "input_modalities": ["text", "image"],
            }
        },
        "aliases": {"openai/gpt-test": "gpt-test"},
    }


def test_model_catalog_remote_result_is_cached_and_aliases_resolve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog._MEMORY_CACHE.clear()
    catalog._REMOTE_CACHE.clear()
    monkeypatch.setattr(
        catalog,
        "_fetch_remote",
        lambda url: catalog._parse_catalog(_payload(), "GitHub"),
    )

    cache_path = tmp_path / "model-catalog-cache.json"
    result = catalog.load_model_catalog(cache_path)

    assert result.source == "remote"
    assert result.metadata_for("gpt-test")["context_window"] == 128000
    assert result.metadata_for("openai/gpt-test")["max_output_tokens"] == 8192
    cached_payload = json.loads(cache_path.read_text(encoding="utf-8"))
    assert cached_payload["catalog_version"] == "test"


def test_model_catalog_falls_back_to_cache_when_remote_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog._MEMORY_CACHE.clear()
    catalog._REMOTE_CACHE.clear()
    cache_path = tmp_path / "model-catalog-cache.json"
    cache_path.write_text(json.dumps(_payload()), encoding="utf-8")

    def fail(url: str) -> catalog.CatalogResult:
        raise catalog.SwitchError("offline")

    monkeypatch.setattr(catalog, "_fetch_remote", fail)

    result = catalog.load_model_catalog(cache_path)

    assert result.source == "cache"
    assert result.warning == "offline; using cached model metadata"
    assert result.metadata_for("gpt-test")["max_output_tokens"] == 8192


def test_model_catalog_failure_without_cache_is_non_fatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog._MEMORY_CACHE.clear()
    catalog._REMOTE_CACHE.clear()

    def fail(url: str) -> catalog.CatalogResult:
        raise catalog.SwitchError("offline")

    monkeypatch.setattr(catalog, "_fetch_remote", fail)

    result = catalog.load_model_catalog(tmp_path / "missing.json")

    assert result.source == "none"
    assert result.entries == {}
    assert result.warning == "offline"
