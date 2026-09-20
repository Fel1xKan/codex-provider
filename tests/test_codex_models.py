from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

import cli.codex_provider as cp
import lib.codex.models as models
from lib.common.model_catalog import CatalogResult
from lib.common.network import ProviderModelList
from lib.common.toml_config import MODEL_CATALOG_FIELD


@pytest.fixture
def codex_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    tool_home = tmp_path / ".codex-provider"
    codex_dir = tmp_path / ".codex"
    paths = {
        "tool_home": tool_home,
        "tool_config": tool_home / "config.toml",
        "codex_dir": codex_dir,
    }
    monkeypatch.setattr(cp, "TOOL_HOME", tool_home)
    monkeypatch.setattr(cp, "TOOL_CONFIG_PATH", paths["tool_config"])
    monkeypatch.setattr(cp, "AUTH_STORE_DIR", tool_home / "auth")
    monkeypatch.setattr(cp, "RECENT_PATH", tool_home / "recent.json")
    monkeypatch.setattr(cp, "DEFAULT_CODEX_DIR", codex_dir)
    return paths


def _add_provider(
    name: str = "alpha", base_url: str = "https://alpha.example.com"
) -> None:
    cp.add_provider(
        provider=name,
        base_url=base_url,
        api_key="placeholder-key",
        display_name=name.capitalize(),
        wire_api="responses",
        supports_websockets=False,
        dry_run=False,
    )
    cp.switch_provider(name, dry_run=False)


def _fake_fetch(model_ids: list[str]):
    def _fetch(base_url, api_key, protocol, models_url_override=None):
        return list(model_ids)

    return _fetch


def test_models_list_empty_catalog(
    codex_paths: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _add_provider()

    assert cp.main(["models", "list", "alpha"]) == 0
    out = capsys.readouterr().out
    assert "provider: alpha" in out
    assert "models (0):" in out


def test_models_sync_creates_catalog_and_pointer(
    codex_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _add_provider()
    monkeypatch.setattr(models, "fetch_provider_models", _fake_fetch(["m-b", "m-a"]))

    assert cp.main(["models", "sync", "alpha"]) == 0

    catalog = codex_paths["tool_home"] / "catalogs" / "alpha.json"
    assert catalog.exists()
    data = json.loads(catalog.read_text(encoding="utf-8"))
    assert [entry["slug"] for entry in data["models"]] == ["m-a", "m-b"]
    assert set(data["models"][0]) >= {"slug", "display_name", "context_window"}

    state = cp.ensure_provider_state(read_only=True)
    assert MODEL_CATALOG_FIELD in state.providers["alpha"]
    runtime = (codex_paths["codex_dir"] / "config.toml").read_text(encoding="utf-8")
    runtime_data = tomllib.loads(runtime)
    catalog_path = Path(runtime_data.get("model_catalog_json", ""))
    assert catalog_path.name == "alpha.json"
    assert catalog_path.parent.name == "catalogs"


def test_models_sync_preserves_existing_metadata(
    codex_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _add_provider()
    monkeypatch.setattr(models, "fetch_provider_models", _fake_fetch(["m-a"]))
    assert cp.main(["models", "sync", "alpha"]) == 0

    catalog = codex_paths["tool_home"] / "catalogs" / "alpha.json"
    data = json.loads(catalog.read_text(encoding="utf-8"))
    data["models"][0]["display_name"] = "Custom"
    catalog.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    monkeypatch.setattr(models, "fetch_provider_models", _fake_fetch(["m-a", "m-new"]))
    assert cp.main(["models", "sync", "alpha"]) == 0

    updated = json.loads(catalog.read_text(encoding="utf-8"))
    by_slug = {entry["slug"]: entry for entry in updated["models"]}
    assert by_slug["m-a"]["display_name"] == "Custom"
    assert by_slug["m-new"]["display_name"] == "m-new"


def test_models_sync_imports_explicit_remote_metadata(
    codex_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _add_provider()
    monkeypatch.setattr(
        models,
        "fetch_provider_models",
        lambda *args, **kwargs: ProviderModelList(
            [
                {
                    "id": "m-a",
                    "name": "Model A",
                    "context_length": 128000,
                    "top_provider": {"max_completion_tokens": 8192},
                    "architecture": {"input_modalities": ["text", "image"]},
                }
            ]
        ),
    )

    assert cp.main(["models", "sync", "alpha"]) == 0

    catalog = codex_paths["tool_home"] / "catalogs" / "alpha.json"
    entry = json.loads(catalog.read_text(encoding="utf-8"))["models"][0]
    assert entry["display_name"] == "Model A"
    assert entry["context_window"] == 128000
    assert entry["max_context_window"] == 128000
    assert entry["max_output_tokens"] == 8192
    assert entry["input_modalities"] == ["text", "image"]


def test_models_sync_narrows_input_modalities_for_codex(
    codex_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Codex rejects a catalog containing video/pdf modalities."""

    _add_provider()
    monkeypatch.setattr(
        models,
        "fetch_provider_models",
        lambda *args, **kwargs: ProviderModelList(
            [
                {
                    "id": "m-a",
                    "architecture": {
                        "input_modalities": ["text", "image", "video", "file"]
                    },
                },
                {
                    "id": "m-b",
                    "architecture": {"input_modalities": ["video", "file"]},
                },
            ]
        ),
    )

    assert cp.main(["models", "sync", "alpha"]) == 0

    catalog = codex_paths["tool_home"] / "catalogs" / "alpha.json"
    by_slug = {
        entry["slug"]: entry
        for entry in json.loads(catalog.read_text(encoding="utf-8"))["models"]
    }
    assert by_slug["m-a"]["input_modalities"] == ["text", "image"]
    # A model with no Codex-supported modality falls back to text only.
    assert by_slug["m-b"]["input_modalities"] == ["text"]


def test_models_sync_uses_github_catalog_for_id_only_response(
    codex_paths: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _add_provider()
    monkeypatch.setattr(models, "fetch_provider_models", _fake_fetch(["gpt-test"]))
    monkeypatch.setattr(
        models,
        "load_model_catalog",
        lambda path: CatalogResult(
            {
                "gpt-test": {
                    "display_name": "GPT Test",
                    "context_window": 128000,
                    "max_output_tokens": 8192,
                    "input_modalities": ["text", "image"],
                }
            },
            {},
            "test",
            "remote",
        ),
    )

    assert cp.main(["models", "sync", "alpha"]) == 0

    entry = json.loads(
        (codex_paths["tool_home"] / "catalogs" / "alpha.json").read_text(
            encoding="utf-8"
        )
    )["models"][0]
    assert entry["display_name"] == "GPT Test"
    assert entry["context_window"] == 128000
    assert entry["max_output_tokens"] == 8192
    assert entry["input_modalities"] == ["text", "image"]


def test_models_sync_reuses_existing_pointer(
    codex_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _add_provider()
    custom = codex_paths["tool_home"] / "custom.json"
    custom.write_text('{"models": []}\n', encoding="utf-8")
    assert (
        cp.main(
            ["config", "set", "alpha", "--provider-model-catalog-json", str(custom)]
        )
        == 0
    )
    monkeypatch.setattr(models, "fetch_provider_models", _fake_fetch(["m-a"]))

    assert cp.main(["models", "sync", "alpha"]) == 0

    assert not (codex_paths["tool_home"] / "catalogs" / "alpha.json").exists()
    data = json.loads(custom.read_text(encoding="utf-8"))
    assert [entry["slug"] for entry in data["models"]] == ["m-a"]


def test_models_sync_dry_run_writes_nothing(
    codex_paths: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _add_provider()
    monkeypatch.setattr(models, "fetch_provider_models", _fake_fetch(["m-a"]))
    before = codex_paths["tool_config"].read_bytes()

    assert cp.main(["models", "sync", "alpha", "--dry-run"]) == 0
    assert codex_paths["tool_config"].read_bytes() == before
    assert not (codex_paths["tool_home"] / "catalogs" / "alpha.json").exists()
    assert "would sync models" in capsys.readouterr().out


def test_models_sync_all(
    codex_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _add_provider("alpha")
    _add_provider("beta", "https://beta.example.com")
    monkeypatch.setattr(models, "fetch_provider_models", _fake_fetch(["m-a"]))

    assert cp.main(["models", "sync", "--all"]) == 0
    assert (codex_paths["tool_home"] / "catalogs" / "alpha.json").exists()
    assert (codex_paths["tool_home"] / "catalogs" / "beta.json").exists()


def test_models_sync_all_rejects_provider(
    codex_paths: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _add_provider()

    assert cp.main(["models", "sync", "alpha", "--all"]) == 1
    assert "--all cannot be combined" in capsys.readouterr().err


def test_models_set_updates_runtime_model(
    codex_paths: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _add_provider()
    monkeypatch.setattr(models, "fetch_provider_models", _fake_fetch(["m-a", "m-b"]))
    assert cp.main(["models", "sync", "alpha"]) == 0
    capsys.readouterr()

    assert cp.main(["models", "set", "m-b", "alpha"]) == 0
    runtime = (codex_paths["codex_dir"] / "config.toml").read_text(encoding="utf-8")
    assert 'model = "m-b"' in runtime
    assert "set model: alpha/m-b" in capsys.readouterr().out


def test_models_set_rejects_unknown_model(
    codex_paths: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _add_provider()
    monkeypatch.setattr(models, "fetch_provider_models", _fake_fetch(["m-a"]))
    assert cp.main(["models", "sync", "alpha"]) == 0
    capsys.readouterr()

    assert cp.main(["models", "set", "nope", "alpha"]) == 1
    assert "unknown model 'nope'" in capsys.readouterr().err


def test_models_set_rejects_provider_prefixed_id(
    codex_paths: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _add_provider()

    assert cp.main(["models", "set", "alpha/m-a", "alpha"]) == 1
    assert "bare model ID" in capsys.readouterr().err


def test_models_set_dry_run_writes_nothing(
    codex_paths: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _add_provider()
    monkeypatch.setattr(models, "fetch_provider_models", _fake_fetch(["m-a", "m-b"]))
    assert cp.main(["models", "sync", "alpha"]) == 0
    runtime = codex_paths["codex_dir"] / "config.toml"
    before = runtime.read_bytes()
    capsys.readouterr()

    assert cp.main(["models", "set", "m-a", "alpha", "--dry-run"]) == 0
    assert runtime.read_bytes() == before
    assert "would set model: alpha/m-a" in capsys.readouterr().out


def test_models_set_can_update_limits_while_selecting(
    codex_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _add_provider()
    monkeypatch.setattr(models, "fetch_provider_models", _fake_fetch(["m-a"]))
    assert cp.main(["models", "sync", "alpha"]) == 0

    assert (
        cp.main(
            [
                "models",
                "set",
                "m-a",
                "alpha",
                "--context-window",
                "128000",
                "--max-output-tokens",
                "8192",
            ]
        )
        == 0
    )

    catalog = codex_paths["tool_home"] / "catalogs" / "alpha.json"
    entry = json.loads(catalog.read_text(encoding="utf-8"))["models"][0]
    assert entry["context_window"] == 128000
    assert entry["max_context_window"] == 128000
    assert entry["max_output_tokens"] == 8192


def test_models_update_sets_scalar_and_bool_fields(
    codex_paths: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _add_provider()
    monkeypatch.setattr(models, "fetch_provider_models", _fake_fetch(["m-a"]))
    assert cp.main(["models", "sync", "alpha"]) == 0
    capsys.readouterr()

    assert (
        cp.main(
            [
                "models",
                "update",
                "m-a",
                "alpha",
                "--set",
                "display_name=My Model",
                "--set",
                "context_window=200000",
                "--set",
                "supports_search_tool=true",
            ]
        )
        == 0
    )
    catalog = codex_paths["tool_home"] / "catalogs" / "alpha.json"
    entry = json.loads(catalog.read_text(encoding="utf-8"))["models"][0]
    assert entry["display_name"] == "My Model"
    assert entry["context_window"] == 200000
    assert entry["supports_search_tool"] is True
    assert "updated model: alpha/m-a" in capsys.readouterr().out


def test_models_update_variants_from_csv(
    codex_paths: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _add_provider()
    monkeypatch.setattr(models, "fetch_provider_models", _fake_fetch(["m-a"]))
    assert cp.main(["models", "sync", "alpha"]) == 0

    assert (
        cp.main(["models", "update", "m-a", "alpha", "--set", "variants=low,high,max"])
        == 0
    )
    catalog = codex_paths["tool_home"] / "catalogs" / "alpha.json"
    entry = json.loads(catalog.read_text(encoding="utf-8"))["models"][0]
    assert entry["supported_reasoning_levels"] == models.reasoning_levels(
        ["low", "high", "max"]
    )
    assert "variants" not in entry


def test_models_sync_writes_default_reasoning_ladder(
    codex_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _add_provider()
    monkeypatch.setattr(models, "fetch_provider_models", _fake_fetch(["m-a"]))

    assert cp.main(["models", "sync", "alpha"]) == 0

    catalog = codex_paths["tool_home"] / "catalogs" / "alpha.json"
    entry = json.loads(catalog.read_text(encoding="utf-8"))["models"][0]
    assert [level["effort"] for level in entry["supported_reasoning_levels"]] == [
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    ]
    assert all(level["description"] for level in entry["supported_reasoning_levels"])
    assert entry["default_reasoning_level"] == "medium"
    # Codex ignores OpenCode's `variants` map, so catalog entries do not carry it.
    assert "variants" not in entry


def test_models_sync_applies_builtin_reasoning_ladder(
    codex_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _add_provider()
    monkeypatch.setattr(
        models,
        "fetch_provider_models",
        _fake_fetch(["deepseek-v4-pro", "gpt-5.4"]),
    )
    # Force the built-in catalog path; the network fetch is not available here.
    monkeypatch.setattr(
        models,
        "_catalog_metadata",
        lambda: {
            "deepseek-v4-pro": {
                "reasoning_levels": ["high", "max"],
                "reasoning_default": "high",
            },
            "gpt-5.4": {"reasoning_levels": ["low", "medium", "high", "xhigh"]},
        },
    )

    assert cp.main(["models", "sync", "alpha"]) == 0

    catalog = codex_paths["tool_home"] / "catalogs" / "alpha.json"
    by_slug = {
        entry["slug"]: entry
        for entry in json.loads(catalog.read_text(encoding="utf-8"))["models"]
    }
    assert [
        level["effort"]
        for level in by_slug["deepseek-v4-pro"]["supported_reasoning_levels"]
    ] == ["high", "max"]
    assert by_slug["deepseek-v4-pro"]["default_reasoning_level"] == "high"
    assert [
        level["effort"] for level in by_slug["gpt-5.4"]["supported_reasoning_levels"]
    ] == ["low", "medium", "high", "xhigh"]
    assert by_slug["gpt-5.4"]["default_reasoning_level"] == "medium"


def test_models_sync_upgrades_legacy_three_level_ladder(
    codex_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _add_provider()
    monkeypatch.setattr(models, "fetch_provider_models", _fake_fetch(["m-a"]))
    monkeypatch.setattr(
        models,
        "_catalog_metadata",
        lambda: {"m-a": {"reasoning_levels": ["low", "medium", "high", "xhigh"]}},
    )
    assert cp.main(["models", "sync", "alpha"]) == 0
    catalog = codex_paths["tool_home"] / "catalogs" / "alpha.json"
    data = json.loads(catalog.read_text(encoding="utf-8"))
    # Shape written by codex-provider before it knew model reasoning levels.
    data["models"][0]["supported_reasoning_levels"] = [
        {"effort": "low", "description": "Light reasoning"},
        {"effort": "high", "description": "Enhanced reasoning"},
        {"effort": "max", "description": "Deep reasoning"},
    ]
    data["models"][0]["variants"] = {"low": {"reasoningEffort": "low"}}
    catalog.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    assert cp.main(["models", "sync", "alpha"]) == 0

    entry = json.loads(catalog.read_text(encoding="utf-8"))["models"][0]
    assert [level["effort"] for level in entry["supported_reasoning_levels"]] == [
        "low",
        "medium",
        "high",
        "xhigh",
    ]
    assert entry["default_reasoning_level"] == "medium"
    assert "variants" not in entry


def test_models_sync_upgrades_legacy_ladder_for_unknown_models(
    codex_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Legacy `low,high,max` ladders are ours, so sync refreshes them."""

    _add_provider()
    monkeypatch.setattr(models, "fetch_provider_models", _fake_fetch(["m-a"]))
    monkeypatch.setattr(models, "_catalog_metadata", dict)
    assert cp.main(["models", "sync", "alpha"]) == 0
    catalog = codex_paths["tool_home"] / "catalogs" / "alpha.json"
    data = json.loads(catalog.read_text(encoding="utf-8"))
    data["models"][0]["supported_reasoning_levels"] = [
        {"effort": "low", "description": "Light reasoning"},
        {"effort": "high", "description": "Enhanced reasoning"},
        {"effort": "max", "description": "Deep reasoning"},
    ]
    catalog.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    assert cp.main(["models", "sync", "alpha"]) == 0

    entry = json.loads(catalog.read_text(encoding="utf-8"))["models"][0]
    assert [level["effort"] for level in entry["supported_reasoning_levels"]] == [
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    ]
    assert entry["default_reasoning_level"] == "medium"


def test_models_sync_migrates_retained_models(
    codex_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Models no longer served by the provider still get the catalog ladder."""

    _add_provider()
    monkeypatch.setattr(models, "fetch_provider_models", _fake_fetch(["m-a"]))
    monkeypatch.setattr(
        models,
        "_catalog_metadata",
        lambda: {"legacy-offer": {"reasoning_levels": ["high", "max"]}},
    )
    assert cp.main(["models", "sync", "alpha"]) == 0
    catalog = codex_paths["tool_home"] / "catalogs" / "alpha.json"
    data = json.loads(catalog.read_text(encoding="utf-8"))
    stale = dict(data["models"][0])
    stale["slug"] = "legacy-offer"
    stale["display_name"] = "legacy-offer"
    stale["supported_reasoning_levels"] = [
        {"effort": "low", "description": "Light reasoning"},
        {"effort": "high", "description": "Enhanced reasoning"},
        {"effort": "max", "description": "Deep reasoning"},
    ]
    data["models"].append(stale)
    catalog.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    assert cp.main(["models", "sync", "alpha"]) == 0

    by_slug = {
        entry["slug"]: entry
        for entry in json.loads(catalog.read_text(encoding="utf-8"))["models"]
    }
    assert "legacy-offer" in by_slug
    assert [
        level["effort"]
        for level in by_slug["legacy-offer"]["supported_reasoning_levels"]
    ] == ["high", "max"]
    assert by_slug["legacy-offer"]["default_reasoning_level"] == "high"


def test_models_update_supported_reasoning_levels(
    codex_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _add_provider()
    monkeypatch.setattr(models, "fetch_provider_models", _fake_fetch(["m-a"]))
    assert cp.main(["models", "sync", "alpha"]) == 0

    assert (
        cp.main(
            [
                "models",
                "update",
                "m-a",
                "alpha",
                "--set",
                "supported_reasoning_levels=low,medium,high",
            ]
        )
        == 0
    )
    catalog = codex_paths["tool_home"] / "catalogs" / "alpha.json"
    entry = json.loads(catalog.read_text(encoding="utf-8"))["models"][0]
    assert [level["effort"] for level in entry["supported_reasoning_levels"]] == [
        "low",
        "medium",
        "high",
    ]


def test_models_update_rejects_unknown_reasoning_levels(
    codex_paths: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _add_provider()
    monkeypatch.setattr(models, "fetch_provider_models", _fake_fetch(["m-a"]))
    assert cp.main(["models", "sync", "alpha"]) == 0
    catalog = codex_paths["tool_home"] / "catalogs" / "alpha.json"
    data = json.loads(catalog.read_text(encoding="utf-8"))
    data["models"][0]["supported_reasoning_levels"] = [
        {"effort": "high", "description": "High"},
        {"effort": "ultra", "description": "Ultra"},
    ]
    catalog.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    before = catalog.read_bytes()
    capsys.readouterr()

    assert cp.main(["models", "update", "m-a", "alpha", "--set", "variants=turbo"]) == 1
    err = capsys.readouterr().err
    assert "unknown reasoning level(s) turbo" in err
    assert "none, minimal, low, medium, high, xhigh, max, ultra" in err
    assert catalog.read_bytes() == before


def test_models_update_rejects_unknown_default_reasoning_level(
    codex_paths: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _add_provider()
    monkeypatch.setattr(models, "fetch_provider_models", _fake_fetch(["m-a"]))
    assert cp.main(["models", "sync", "alpha"]) == 0
    capsys.readouterr()

    assert (
        cp.main(
            [
                "models",
                "update",
                "m-a",
                "alpha",
                "--set",
                "default_reasoning_level=turbo",
            ]
        )
        == 1
    )
    assert "unknown reasoning level 'turbo'" in capsys.readouterr().err

    assert (
        cp.main(
            [
                "models",
                "update",
                "m-a",
                "alpha",
                "--set",
                "default_reasoning_level=high",
            ]
        )
        == 0
    )
    catalog = codex_paths["tool_home"] / "catalogs" / "alpha.json"
    entry = json.loads(catalog.read_text(encoding="utf-8"))["models"][0]
    assert entry["default_reasoning_level"] == "high"


def test_models_sync_accepts_ultra_and_none_levels(
    codex_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _add_provider()
    monkeypatch.setattr(models, "fetch_provider_models", _fake_fetch(["m-a"]))
    assert cp.main(["models", "sync", "alpha"]) == 0

    assert (
        cp.main(
            [
                "models",
                "update",
                "m-a",
                "alpha",
                "--set",
                "supported_reasoning_levels=low,high,max,ultra",
            ]
        )
        == 0
    )
    catalog = codex_paths["tool_home"] / "catalogs" / "alpha.json"
    entry = json.loads(catalog.read_text(encoding="utf-8"))["models"][0]
    assert [level["effort"] for level in entry["supported_reasoning_levels"]] == [
        "low",
        "high",
        "max",
        "ultra",
    ]


def test_models_sync_keeps_hand_edited_reasoning_levels(
    codex_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _add_provider()
    monkeypatch.setattr(models, "fetch_provider_models", _fake_fetch(["m-a"]))
    assert cp.main(["models", "sync", "alpha"]) == 0
    catalog = codex_paths["tool_home"] / "catalogs" / "alpha.json"
    data = json.loads(catalog.read_text(encoding="utf-8"))
    custom = [
        {"effort": "high", "description": "High"},
        {"effort": "ultra", "description": "Ultra"},
    ]
    data["models"][0]["supported_reasoning_levels"] = custom
    catalog.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    assert cp.main(["models", "sync", "alpha"]) == 0

    entry = json.loads(catalog.read_text(encoding="utf-8"))["models"][0]
    assert entry["supported_reasoning_levels"] == custom


def test_models_sync_keeps_hand_edited_default_reasoning_level(
    codex_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _add_provider()
    monkeypatch.setattr(models, "fetch_provider_models", _fake_fetch(["m-a"]))
    monkeypatch.setattr(
        models,
        "_catalog_metadata",
        lambda: {"m-a": {"reasoning_levels": ["low", "medium", "high", "xhigh"]}},
    )
    assert cp.main(["models", "sync", "alpha"]) == 0
    catalog = codex_paths["tool_home"] / "catalogs" / "alpha.json"
    assert (
        cp.main(
            [
                "models",
                "update",
                "m-a",
                "alpha",
                "--set",
                "default_reasoning_level=high",
            ]
        )
        == 0
    )

    assert cp.main(["models", "sync", "alpha"]) == 0

    entry = json.loads(catalog.read_text(encoding="utf-8"))["models"][0]
    assert [level["effort"] for level in entry["supported_reasoning_levels"]] == [
        "low",
        "medium",
        "high",
        "xhigh",
    ]
    assert entry["default_reasoning_level"] == "high"


def test_models_sync_force_resets_hand_edited_reasoning_levels(
    codex_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _add_provider()
    monkeypatch.setattr(models, "fetch_provider_models", _fake_fetch(["m-a"]))
    assert cp.main(["models", "sync", "alpha"]) == 0
    catalog = codex_paths["tool_home"] / "catalogs" / "alpha.json"
    data = json.loads(catalog.read_text(encoding="utf-8"))
    data["models"][0]["supported_reasoning_levels"] = [
        {"effort": "high", "description": "High"},
        {"effort": "ultra", "description": "Ultra"},
    ]
    catalog.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    assert cp.main(["models", "sync", "alpha", "--force"]) == 0

    entry = json.loads(catalog.read_text(encoding="utf-8"))["models"][0]
    assert [level["effort"] for level in entry["supported_reasoning_levels"]] == [
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    ]


def test_models_sync_force_refreshes_reasoning_levels(
    codex_paths: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _add_provider()
    monkeypatch.setattr(models, "fetch_provider_models", _fake_fetch(["m-a"]))
    assert cp.main(["models", "sync", "alpha"]) == 0
    catalog = codex_paths["tool_home"] / "catalogs" / "alpha.json"
    data = json.loads(catalog.read_text(encoding="utf-8"))
    data["models"][0]["display_name"] = "Custom"
    data["models"][0]["context_window"] = 200000
    data["models"][0]["supported_reasoning_levels"] = [
        {"effort": "low", "description": "Legacy"},
        {"effort": "high", "description": "Legacy"},
        {"effort": "max", "description": "Legacy"},
    ]
    data["models"][0]["variants"] = {"low": {"reasoningEffort": "low"}}
    catalog.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    capsys.readouterr()

    assert cp.main(["models", "sync", "alpha", "--force"]) == 0

    out = capsys.readouterr().out
    assert "refreshed reasoning levels for 1 models" in out
    entry = json.loads(catalog.read_text(encoding="utf-8"))["models"][0]
    assert [level["effort"] for level in entry["supported_reasoning_levels"]] == [
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    ]
    assert entry["display_name"] == "Custom"
    assert entry["context_window"] == 200000
    assert "variants" not in entry


def test_models_sync_force_dry_run_writes_nothing(
    codex_paths: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _add_provider()
    monkeypatch.setattr(models, "fetch_provider_models", _fake_fetch(["m-a"]))
    assert cp.main(["models", "sync", "alpha"]) == 0
    catalog = codex_paths["tool_home"] / "catalogs" / "alpha.json"
    data = json.loads(catalog.read_text(encoding="utf-8"))
    data["models"][0]["supported_reasoning_levels"] = [
        {"effort": "high", "description": "High"},
        {"effort": "ultra", "description": "Ultra"},
    ]
    catalog.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    before = catalog.read_bytes()
    capsys.readouterr()

    assert cp.main(["models", "sync", "alpha", "--force", "--dry-run"]) == 0

    out = capsys.readouterr().out
    assert "would refresh reasoning levels for 1 models" in out
    assert catalog.read_bytes() == before


def test_models_update_rejects_unknown_field(
    codex_paths: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _add_provider()
    monkeypatch.setattr(models, "fetch_provider_models", _fake_fetch(["m-a"]))
    assert cp.main(["models", "sync", "alpha"]) == 0

    assert cp.main(["models", "update", "m-a", "alpha", "--set", "nope=1"]) == 1
    assert "unknown field 'nope'" in capsys.readouterr().err


def test_models_update_rejects_unknown_model(
    codex_paths: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _add_provider()
    monkeypatch.setattr(models, "fetch_provider_models", _fake_fetch(["m-a"]))
    assert cp.main(["models", "sync", "alpha"]) == 0

    assert cp.main(["models", "update", "ghost", "alpha", "--set", "priority=1"]) == 1
    assert "unknown model 'ghost'" in capsys.readouterr().err


def test_models_update_dry_run_writes_nothing(
    codex_paths: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _add_provider()
    monkeypatch.setattr(models, "fetch_provider_models", _fake_fetch(["m-a"]))
    assert cp.main(["models", "sync", "alpha"]) == 0
    catalog = codex_paths["tool_home"] / "catalogs" / "alpha.json"
    before = catalog.read_bytes()
    capsys.readouterr()

    assert (
        cp.main(
            ["models", "update", "m-a", "alpha", "--set", "priority=5", "--dry-run"]
        )
        == 0
    )
    assert catalog.read_bytes() == before
    assert "would update model: alpha/m-a" in capsys.readouterr().out


def test_models_update_empty_string_clears_text_field(
    codex_paths: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _add_provider()
    monkeypatch.setattr(models, "fetch_provider_models", _fake_fetch(["m-a"]))
    assert cp.main(["models", "sync", "alpha"]) == 0
    assert (
        cp.main(["models", "update", "m-a", "alpha", "--set", "display_name=Custom"])
        == 0
    )

    assert cp.main(["models", "update", "m-a", "alpha", "--set", "display_name="]) == 0
    catalog = codex_paths["tool_home"] / "catalogs" / "alpha.json"
    entry = json.loads(catalog.read_text(encoding="utf-8"))["models"][0]
    assert "display_name" not in entry
