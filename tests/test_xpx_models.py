from __future__ import annotations

import io
import json
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from lib.common.errors import SwitchError
from lib.xpx.models.catalog import (
    add_model_to_catalog,
    enrich_model_metadata,
    get_consolidated_provider_models,
    resolve_model_effort,
    update_model_preference,
)
from lib.xpx.models.sync import fetch_remote_models, sync_provider_models
from lib.xpx.store.catalog_store import CatalogStore
from lib.xpx.store.provider_store import ProviderSpec, ProviderStore


class MockResponse:
    def __init__(self, data: dict[str, Any] | list[Any]) -> None:
        self.payload = json.dumps(data).encode("utf-8")
        self.fp = io.BytesIO(self.payload)

    def read(self, limit: int = -1) -> bytes:
        return self.fp.read(limit)

    def __enter__(self) -> MockResponse:
        return self

    def __exit__(self, *args: Any) -> None:
        pass


@pytest.fixture
def xpx_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".xpx"
    monkeypatch.setenv("XPX_HOME", str(home))
    return home


def test_enrich_model_metadata() -> None:
    # Model in shared catalog
    meta = enrich_model_metadata("deepseek-reasoner")
    assert meta.id == "deepseek-reasoner"
    lower_name = meta.display_name.lower()
    assert "deepseek" in lower_name or "reasoner" in lower_name
    assert meta.context_window > 0

    # Custom unknown model
    custom = enrich_model_metadata("my-custom-model")
    assert custom.id == "my-custom-model"
    assert custom.display_name == "my-custom-model"
    assert custom.context_window == 128000
    assert custom.max_output_tokens == 8192


def test_fetch_remote_models(monkeypatch: pytest.MonkeyPatch) -> None:
    def mock_urlopen(req: urllib.request.Request, timeout: int = 15) -> MockResponse:
        assert req.get_header("Authorization") == "Bearer sk-test"
        return MockResponse({"data": [{"id": "model-b"}, {"id": "model-a"}]})

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    models = fetch_remote_models("https://api.example.com/v1", "sk-test")
    assert models == ["model-a", "model-b"]


def test_sync_provider_models(xpx_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pv_store = ProviderStore()
    pv_store.save(
        ProviderSpec(
            name="testpv",
            base_url="https://api.test.com/v1",
            api_key="sk-test",
        )
    )

    def mock_urlopen(req: urllib.request.Request, timeout: int = 15) -> MockResponse:
        return MockResponse(
            {
                "data": [
                    {"id": "deepseek-reasoner"},
                    {"id": "unknown-model"},
                ]
            }
        )

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    catalog = sync_provider_models("testpv")
    assert catalog.provider == "testpv"
    assert "deepseek-reasoner" in catalog.models
    assert "unknown-model" in catalog.models

    loaded = CatalogStore().get("testpv")
    assert loaded is not None
    assert "deepseek-reasoner" in loaded.models

    # Default model was auto-assigned because none was set
    pv = pv_store.require("testpv")
    assert pv.default_model in {"deepseek-reasoner", "unknown-model"}


def test_update_model_preference(xpx_env: Path) -> None:
    pv_store = ProviderStore()
    pv_store.save(
        ProviderSpec(
            name="myprovider",
            base_url="https://api.my.com/v1",
            api_key="sk-test",
        )
    )

    meta = update_model_preference(
        "myprovider",
        "deepseek-reasoner",
        is_default=True,
        context=64000,
        max_output=4096,
    )
    assert meta.context_window == 64000
    assert meta.max_output_tokens == 4096

    pv = pv_store.require("myprovider")
    assert pv.default_model == "deepseek-reasoner"

    with pytest.raises(SwitchError):
        update_model_preference("myprovider", "deepseek-reasoner", context=-1)


def test_refresh_active_adapters_opencode(
    xpx_env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pv_store = ProviderStore()
    pv_store.save(
        ProviderSpec(
            name="openpv",
            base_url="https://api.open.com/v1",
            api_key="sk-test",
        )
    )

    opencode_cfg = tmp_path / "opencode_conf"
    opencode_cfg.mkdir(parents=True)
    monkeypatch.setenv("OPENCODE_CONFIG_DIR", str(opencode_cfg))

    (opencode_cfg / "opencode.json").write_text(
        json.dumps(
            {
                "provider": {
                    "openpv": {
                        "options": {"baseURL": "https://api.open.com/v1"},
                    }
                },
                "model": "openpv/initial-model",
            }
        ),
        encoding="utf-8",
    )

    def mock_urlopen(req: urllib.request.Request, timeout: int = 15) -> MockResponse:
        return MockResponse({"data": [{"id": "synced-model-1"}]})

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    sync_provider_models("openpv")

    # Verify that opencode config was refreshed with synced-model-1
    cfg_data = json.loads((opencode_cfg / "opencode.json").read_text(encoding="utf-8"))
    models = cfg_data["provider"]["openpv"]["models"]
    assert "synced-model-1" in models
    assert (opencode_cfg / "models.json").is_file()

    # Update model preference and verify opencode reflects it
    update_model_preference("openpv", "synced-model-1", context=32000)
    refreshed_data = json.loads(
        (opencode_cfg / "opencode.json").read_text(encoding="utf-8")
    )
    assert (
        refreshed_data["provider"]["openpv"]["models"]["synced-model-1"]["limit"][
            "context"
        ]
        == 32000
    )


def test_resolve_model_effort(xpx_env: Path) -> None:
    # 1. Explicit effort overrides everything
    assert resolve_model_effort("pv", "any-model", explicit_effort="low") == "low"
    assert resolve_model_effort("pv", "any-model", explicit_effort="  max  ") == "max"

    # 2. None model
    assert resolve_model_effort("pv", None) is None

    # 3. Model from shared catalog with reasoning default
    effort = resolve_model_effort("pv", "deepseek-reasoner")
    assert effort in {"high", "default", "medium", "low"}

    # 4. Model with provider prefix stripped
    effort_prefixed = resolve_model_effort("my-pv", "my-pv/deepseek-reasoner")
    assert effort_prefixed == effort

    # 5. Model with provider-specific custom catalog override
    pv_store = ProviderStore()
    pv_store.save(
        ProviderSpec(
            name="my-pv",
            base_url="https://api.test.com/v1",
            api_key="sk-test",
        )
    )
    update_model_preference(
        "my-pv",
        "custom-model",
        effort="medium",
    )
    # Give it reasoning levels
    cat_store = CatalogStore()
    cat = cat_store.get("my-pv")
    assert cat is not None
    cat.models["custom-model"].supported_reasoning_levels = ["low", "medium", "high"]
    cat.models["custom-model"].default_reasoning_level = "medium"
    cat_store.save(cat)

    assert resolve_model_effort("my-pv", "custom-model") == "medium"


def test_get_consolidated_provider_models(xpx_env: Path) -> None:
    pv_store = ProviderStore()
    pv_store.save(
        ProviderSpec(
            name="consolidated-pv",
            base_url="https://api.test.com/v1",
            api_key="sk-test",
            default_model="consolidated-pv/deepseek-chat",
        )
    )

    models = get_consolidated_provider_models(
        provider_name="consolidated-pv",
        applied_model="consolidated-pv/deepseek-reasoner",
        previous_model="previous-model",
        extra_models=["extra-model-1"],
    )

    # All models stripped of provider prefix
    assert "deepseek-reasoner" in models
    assert "deepseek-chat" in models
    assert "previous-model" in models
    assert "extra-model-1" in models

    # Metadata enrichment occurred
    assert models["deepseek-reasoner"].supported_reasoning_levels
    assert models["deepseek-chat"].context_window > 0
    assert models["extra-model-1"].context_window == 128000


def test_add_model_to_catalog(xpx_env: Path) -> None:
    pv_store = ProviderStore()
    pv_store.save(
        ProviderSpec(
            name="test-provider",
            base_url="https://api.test.com/v1",
            api_key="sk-test",
        )
    )

    # 1. Add model with auto enrichment
    meta, is_created = add_model_to_catalog("test-provider", "deepseek-reasoner")
    assert is_created is True
    assert meta.id == "deepseek-reasoner"
    lower_name = meta.display_name.lower()
    assert "deepseek" in lower_name or "reasoner" in lower_name
    assert meta.context_window > 0
    assert "high" in meta.supported_reasoning_levels

    # 2. Add custom model with all explicit options
    c_meta, c_created = add_model_to_catalog(
        "test-provider",
        "custom-special",
        display_name="Custom Special Model",
        context=200000,
        max_output=16384,
        effort="high",
        modalities=["text", "image"],
        is_default=True,
    )
    assert c_created is True
    assert c_meta.display_name == "Custom Special Model"
    assert c_meta.context_window == 200000
    assert c_meta.max_output_tokens == 16384
    assert c_meta.supported_reasoning_levels == ["high"]
    assert c_meta.default_reasoning_level == "high"
    assert c_meta.input_modalities == ["text", "image"]

    # Verify multi-level comma-separated effort
    m_meta, _ = add_model_to_catalog(
        "test-provider",
        "custom-multi",
        effort="low, medium, high",
    )
    assert m_meta.supported_reasoning_levels == ["low", "medium", "high"]
    assert m_meta.default_reasoning_level == "high"

    # Verify disabled effort
    d_meta, _ = add_model_to_catalog(
        "test-provider",
        "custom-disabled",
        effort="none",
    )
    assert d_meta.supported_reasoning_levels == ["none"]
    assert d_meta.default_reasoning_level is None

    # Verify provider default_model updated
    pv = pv_store.require("test-provider")
    assert pv.default_model == "custom-special"

    # 3. Update existing model without overwrite
    u_meta, u_created = add_model_to_catalog(
        "test-provider",
        "custom-special",
        context=250000,
    )
    assert u_created is False
    assert u_meta.context_window == 250000
    # display name and modalities preserved
    assert u_meta.display_name == "Custom Special Model"
    assert u_meta.input_modalities == ["text", "image"]

    # 4. Overwrite existing model
    o_meta, o_created = add_model_to_catalog(
        "test-provider",
        "custom-special",
        overwrite=True,
    )
    assert o_created is False
    # Defaults restored from enrichment
    assert o_meta.context_window == 128000

    # 5. Prefix strip
    p_meta, _ = add_model_to_catalog(
        "test-provider",
        "test-provider/prefixed-model",
    )
    assert p_meta.id == "prefixed-model"

    # 6. Errors
    with pytest.raises(SwitchError, match="unknown provider"):
        add_model_to_catalog("non-existent", "m1")

    with pytest.raises(SwitchError, match="cannot be empty"):
        add_model_to_catalog("test-provider", "   ")

    with pytest.raises(SwitchError, match="positive integer"):
        add_model_to_catalog("test-provider", "m1", context=-5)
