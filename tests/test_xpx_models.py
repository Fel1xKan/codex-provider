from __future__ import annotations

import io
import json
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from lib.common.errors import SwitchError
from lib.xpx.models.catalog import (
    enrich_model_metadata,
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
