from __future__ import annotations

import os
from pathlib import Path

import pytest

from lib.common.errors import SwitchError
from lib.xpx.store.account_store import AccountSpec, AccountStore
from lib.xpx.store.catalog_store import CatalogStore, ModelMetadata, ProviderCatalog
from lib.xpx.store.provider_store import (
    ProviderSpec,
    ProviderStore,
    TargetOverrides,
)
from lib.xpx.store.state_store import StateStore


@pytest.fixture
def xpx_test_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".xpx"
    monkeypatch.setenv("XPX_HOME", str(home))
    return home


def test_provider_store_lifecycle(xpx_test_home: Path) -> None:
    store = ProviderStore()
    assert store.list_all() == []

    spec = ProviderSpec(
        name="deepseek",
        base_url="https://api.deepseek.com/v1",
        api_key="sk-test123456",
        protocol="openai",
        default_model="deepseek-reasoner",
        headers={"x-global": "1"},
        targets={
            "codex": TargetOverrides(
                fast=True,
                wire_api="chat",
                web_search=True,
                headers={"x-target": "2"},
                options={"foo": "bar"},
            )
        },
    )
    store.save(spec)

    loaded = store.require("deepseek")
    assert loaded.name == "deepseek"
    assert loaded.base_url == "https://api.deepseek.com/v1"
    assert loaded.api_key == "sk-test123456"
    assert loaded.default_model == "deepseek-reasoner"
    assert loaded.headers == {"x-global": "1"}
    assert "codex" in loaded.targets
    codex_target = loaded.targets["codex"]
    assert codex_target.fast is True
    assert codex_target.wire_api == "chat"
    assert codex_target.web_search is True
    assert codex_target.headers == {"x-target": "2"}
    assert codex_target.options == {"foo": "bar"}

    # File permissions check on POSIX
    if os.name == "posix":
        file_mode = store.provider_path("deepseek").stat().st_mode & 0o777
        assert file_mode == 0o600

    # Rename
    store.rename("deepseek", "deepseek-v2")
    assert store.get("deepseek") is None
    assert store.exists("deepseek-v2")
    renamed = store.require("deepseek-v2")
    assert renamed.name == "deepseek-v2"

    # Delete
    assert store.delete("deepseek-v2") is True
    assert store.delete("deepseek-v2") is False
    assert store.list_all() == []

    with pytest.raises(SwitchError):
        store.require("nonexistent")


def test_account_store_lifecycle(xpx_test_home: Path) -> None:
    store = AccountStore()
    assert store.list_all() == []

    acc = AccountSpec(
        target="agy",
        name="work",
        account_type="google-oauth",
        token_data={"access_token": "ya29.test", "expires_at": 1234567890},
        metadata={"email": "dev@work.com", "tier": "enterprise"},
    )
    store.save(acc)

    loaded = store.require("agy", "work")
    assert loaded.target == "agy"
    assert loaded.name == "work"
    assert loaded.account_type == "google-oauth"
    assert loaded.token_data["access_token"] == "ya29.test"
    assert loaded.metadata["email"] == "dev@work.com"

    if os.name == "posix":
        file_mode = store.account_path("agy", "work").stat().st_mode & 0o777
        assert file_mode == 0o600

    all_accs = store.list_all()
    assert len(all_accs) == 1
    assert all_accs[0].name == "work"

    by_target = store.list_by_target("agy")
    assert len(by_target) == 1

    assert store.delete("agy", "work") is True
    assert store.get("agy", "work") is None
    assert store.list_all() == []


def test_state_store_lifecycle(xpx_test_home: Path) -> None:
    store = StateStore()
    state = store.load()
    assert state.targets == {}

    store.set_target_state(
        "codex",
        active_type="provider",
        active_name="deepseek",
        active_model="deepseek-reasoner",
    )
    store.set_target_state(
        "agy",
        active_type="account",
        active_name="work",
        active_model="gemini-2.5-pro",
    )

    loaded = store.load()
    assert "codex" in loaded.targets
    assert loaded.targets["codex"].active_name == "deepseek"
    assert loaded.targets["codex"].active_model == "deepseek-reasoner"
    assert loaded.targets["codex"].active_type == "provider"

    assert "agy" in loaded.targets
    assert loaded.targets["agy"].active_name == "work"

    assert store.remove_target_state("codex") is True
    assert store.get_target_state("codex") is None
    assert store.get_target_state("agy") is not None


def test_catalog_store_lifecycle(xpx_test_home: Path) -> None:
    store = CatalogStore()
    cat = ProviderCatalog(
        provider="openrouter",
        updated_at="2026-09-20T16:00:00Z",
        models={
            "anthropic/claude-3.7-sonnet": ModelMetadata(
                id="anthropic/claude-3.7-sonnet",
                display_name="Claude 3.7 Sonnet",
                context_window=200000,
                max_output_tokens=8192,
                supported_reasoning_levels=["low", "medium", "high"],
                default_reasoning_level="medium",
            )
        },
    )
    store.save(cat)

    loaded = store.get("openrouter")
    assert loaded is not None
    assert loaded.provider == "openrouter"
    assert "anthropic/claude-3.7-sonnet" in loaded.models
    model = loaded.models["anthropic/claude-3.7-sonnet"]
    assert model.display_name == "Claude 3.7 Sonnet"
    assert model.context_window == 200000
    assert model.supported_reasoning_levels == ["low", "medium", "high"]

    assert store.delete("openrouter") is True
    assert store.get("openrouter") is None
