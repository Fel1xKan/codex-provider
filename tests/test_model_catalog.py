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


def test_reasoning_levels_are_normalized_and_unknown_names_dropped() -> None:
    entry = catalog._normalize_entry(
        {
            "context_window": 1000,
            "reasoning_levels": ["High", "bogus", "max", "high", "ultra"],
            "reasoning_default": "MAX",
        }
    )

    assert entry["reasoning_levels"] == [
        {"effort": "high"},
        {"effort": "max"},
        {"effort": "ultra"},
    ]
    assert entry["reasoning_default"] == "max"


def test_reasoning_level_descriptions_are_kept() -> None:
    """Vendors that expose a thinking switch supply their own wording."""

    entry = catalog._normalize_entry(
        {
            "reasoning_levels": [
                {"effort": "none", "description": "Thinking disabled"},
                {"effort": "high", "description": "Thinking enabled"},
            ],
            "reasoning_default": "high",
        }
    )

    assert entry["reasoning_levels"] == [
        {"effort": "none", "description": "Thinking disabled"},
        {"effort": "high", "description": "Thinking enabled"},
    ]
    assert entry["reasoning_default"] == "high"


def test_reasoning_default_outside_the_ladder_is_ignored() -> None:
    entry = catalog._normalize_entry(
        {
            "reasoning_levels": ["high", "max"],
            "reasoning_default": "medium",
        }
    )

    assert entry["reasoning_levels"] == [{"effort": "high"}, {"effort": "max"}]
    assert "reasoning_default" not in entry


def test_reasoning_fields_absent_leave_the_entry_unchanged() -> None:
    assert catalog._normalize_entry({"reasoning_default": "high"}) == {}


def test_shipped_catalog_declares_reasoning_ladders() -> None:
    path = Path(__file__).resolve().parent.parent / "data" / "model-catalog.json"
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["schema_version"] == catalog.CATALOG_SCHEMA_VERSION
    models = payload["models"]
    assert models
    for model_id, raw in models.items():
        entry = catalog._normalize_entry(raw)
        assert entry.get("reasoning_levels"), model_id
        assert entry.get("reasoning_default"), model_id
        names = [level["effort"] for level in entry["reasoning_levels"]]
        assert entry["reasoning_default"] in names, model_id
        # `max` and `ultra` burn usage limits, so they are never preselected
        # while a cheaper level is available.
        cheaper = [name for name in names if name not in ("max", "ultra")]
        if cheaper:
            assert entry["reasoning_default"] in cheaper, model_id


def test_shipped_catalog_thinking_toggles_are_labelled() -> None:
    """A ladder either carries wording for every level or for none of them."""

    path = Path(__file__).resolve().parent.parent / "data" / "model-catalog.json"
    models = json.loads(path.read_text(encoding="utf-8"))["models"]

    for model_id, raw in models.items():
        entry = catalog._normalize_entry(raw)
        described = [
            bool(level.get("description")) for level in entry["reasoning_levels"]
        ]
        assert len(set(described)) == 1, model_id

    # The vendor thinking switches name themselves, because `none` there means
    # "thinking off" rather than "this model has no reasoning levels".
    for model_id in ("qwen3-max", "qwen3.8-flash", "claude-haiku-4-5", "kimi-k2.6"):
        assert _is_thinking_toggle(catalog._normalize_entry(models[model_id])), model_id


def _is_thinking_toggle(entry: dict) -> bool:
    """True when the ladder is a vendor thinking switch rather than efforts."""

    descriptions = [level.get("description", "") for level in entry["reasoning_levels"]]
    return any("thinking" in text.lower() for text in descriptions)


def test_shipped_catalog_reasoning_defaults_follow_the_ladder() -> None:
    """Spot-check ladders against what each vendor actually documents."""

    path = Path(__file__).resolve().parent.parent / "data" / "model-catalog.json"
    models = json.loads(path.read_text(encoding="utf-8"))["models"]

    expected = {
        # Codex CLI model metadata, including the Codex-side `ultra` level.
        "gpt-5.4": (["none", "low", "medium", "high", "xhigh"], "medium"),
        "gpt-5.6-luna": (
            ["none", "low", "medium", "high", "xhigh", "max"],
            "medium",
        ),
        "gpt-5.6-sol": (
            ["none", "low", "medium", "high", "xhigh", "max", "ultra"],
            "medium",
        ),
        "gpt-5": (["minimal", "low", "medium", "high"], "medium"),
        "gpt-4o": (["none"], "none"),
        # DeepSeek: none/low/high/max, default high, low+medium map to high.
        "deepseek-v4-pro": (["none", "low", "high", "max"], "high"),
        "deepseek-reasoner": (["none", "low", "high", "max"], "high"),
        # Kimi K3 documents low/high/max with a max default.
        "kimi-k3": (["low", "high", "max"], "high"),
        # Kimi K2.7 always thinks and takes no level parameter.
        "kimi-k2.7-code": (["high"], "high"),
        # xAI: low/medium/high, xhigh on 4.6+, default high.
        "grok-4.6": (["low", "medium", "high", "xhigh"], "high"),
        "grok-4.5": (["low", "medium", "high"], "high"),
        # GLM-5.3 is limited to low/high/max.
        "glm-5.3": (["low", "high", "max"], "high"),
        # GLM-5.2 maps low/medium to high and xhigh to max.
        "glm-5.2": (["none", "high", "max"], "high"),
        # GLM-4.7 thinks compulsorily and exposes no level.
        "glm-4.7": (["high"], "high"),
        # Claude: five levels on 5.x and Opus 4.7/4.8, `max` but no `xhigh` on
        # the 4.6 pair, and an effort-free thinking budget on 4.5/3.7.
        "claude-opus-5": (["low", "medium", "high", "xhigh", "max"], "high"),
        "claude-opus-4-7": (["low", "medium", "high", "xhigh", "max"], "high"),
        "claude-sonnet-4-6": (["low", "medium", "high", "max"], "high"),
        "claude-opus-4-5": (["low", "medium", "high"], "high"),
        "claude-sonnet-4-5": (["none", "high"], "high"),
        "claude-haiku-4-5": (["none", "high"], "high"),
        "claude-3-7-sonnet-latest": (["none", "high"], "high"),
        "claude-3-5-sonnet-latest": (["none"], "none"),
        # Gemini thinking levels.
        "gemini-3.8-flash": (["low", "medium", "high"], "medium"),
        "gemini-3.6-flash": (["minimal", "low", "medium", "high"], "medium"),
        "gemini-3.1-pro-preview": (["low", "medium", "high"], "high"),
        "gemini-3.1-flash-lite-image": (["minimal", "high"], "high"),
        "gemini-2.5-flash-lite": (["low", "medium", "high"], "low"),
        "gemini-2.5-pro": (["low", "medium", "high"], "medium"),
        # Qwen exposes a thinking switch, not an effort ladder.
        "qwen3-max": (["none", "high"], "high"),
        "qwen3.8-max": (["none", "high"], "high"),
        "qwen3-coder-plus": (["none"], "none"),
        "qwq-plus": (["high"], "high"),
        # Mistral: a thinking switch on the newest pair, native reasoning on
        # Magistral, and nothing to select elsewhere.
        "mistral-small-2603": (["none", "high"], "high"),
        "magistral-medium-latest": (["high"], "high"),
        "mistral-large-latest": (["none"], "none"),
        # xAI: `xhigh` needs grok-4.6+; grok-4.3 exposes no effort parameter.
        "grok-4.3": (["high"], "high"),
    }
    for model_id, (levels, default) in expected.items():
        entry = models[model_id]
        names = [
            level if isinstance(level, str) else level["effort"]
            for level in entry["reasoning_levels"]
        ]
        assert names == levels, model_id
        assert entry["reasoning_default"] == default, model_id


def test_shipped_catalog_records_reasoning_sources() -> None:
    path = Path(__file__).resolve().parent.parent / "data" / "model-catalog.json"
    payload = json.loads(path.read_text(encoding="utf-8"))

    for vendor in ("openai", "anthropic", "google", "deepseek", "xai"):
        assert payload["sources"][vendor]["reasoning"].startswith("https://")
