from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
import tomlkit
import yaml

from lib.common.errors import SwitchError
from lib.xpx.adapters.agy import AgyAdapter
from lib.xpx.adapters.base import MergedProviderSpec
from lib.xpx.adapters.claude import ClaudeAdapter
from lib.xpx.adapters.codex import CodexAdapter
from lib.xpx.adapters.cursor import CursorAdapter
from lib.xpx.adapters.opencode import OpenCodeAdapter
from lib.xpx.adapters.pi import PiAdapter
from lib.xpx.adapters.registry import get_adapter, get_all_adapters
from lib.xpx.store.account_store import AccountSpec


def test_codex_adapter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    codex_home = tmp_path / ".codex"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    monkeypatch.setattr("shutil.which", lambda _: None)
    adapter = CodexAdapter(home=codex_home)
    assert adapter.name == "codex"
    assert not adapter.detect()

    spec = MergedProviderSpec(
        name="deepseek",
        base_url="https://api.deepseek.com/v1",
        api_key="sk-codex-test",
        protocol="openai",
        model="deepseek-reasoner",
        headers={"x-user": "dev1"},
        fast=True,
        wire_api="chat",
        web_search=True,
    )
    adapter.apply(spec)

    assert adapter.detect()
    status = adapter.get_status()
    assert status.installed is True
    assert status.active_type == "provider"
    assert status.active_name == "deepseek"
    assert status.active_model == "deepseek-reasoner"
    assert status.extra_summary == "fast"

    # Verify TOML content
    doc = tomlkit.parse((codex_home / "config.toml").read_text(encoding="utf-8"))
    assert doc["model_provider"] == "deepseek"
    assert doc["model"] == "deepseek-reasoner"
    assert doc["service_tier"] == "priority"
    assert doc["web_search"] == "live"
    pv_entry = doc["model_providers"]["deepseek"]
    assert pv_entry["base_url"] == "https://api.deepseek.com/v1"
    assert pv_entry["wire_api"] == "chat"
    assert pv_entry["http_headers"]["x-user"] == "dev1"

    # Verify auth
    auth = json.loads((codex_home / "auth.json").read_text(encoding="utf-8"))
    assert auth["OPENAI_API_KEY"] == "sk-codex-test"

    # Reset
    adapter.clear()
    cleared_doc = tomlkit.parse(
        (codex_home / "config.toml").read_text(encoding="utf-8")
    )
    assert cleared_doc["model_provider"] == "openai"
    assert "service_tier" not in cleared_doc


def test_opencode_adapter(tmp_path: Path) -> None:
    cfg_dir = tmp_path / "config" / "opencode"
    data_dir = tmp_path / "data" / "opencode"
    adapter = OpenCodeAdapter(config_dir=cfg_dir, data_dir=data_dir)
    assert adapter.name == "opencode"

    spec = MergedProviderSpec(
        name="openrouter",
        base_url="https://openrouter.ai/api/v1",
        api_key="sk-or-test",
        protocol="openai",
        model="anthropic/claude-3.7-sonnet",
        headers={"HTTP-Referer": "https://example.com"},
    )
    adapter.apply(spec)

    status = adapter.get_status()
    assert status.installed is True
    assert status.active_type == "provider"
    assert status.active_name == "openrouter"
    assert status.active_model == "anthropic/claude-3.7-sonnet"

    cfg_data = json.loads((cfg_dir / "opencode.json").read_text(encoding="utf-8"))
    assert "openrouter" in cfg_data["provider"]
    prov = cfg_data["provider"]["openrouter"]
    assert prov["options"]["baseURL"] == "https://openrouter.ai/api/v1"
    assert prov["options"]["apiKey"] == "sk-or-test"
    assert cfg_data["model"] == "openrouter/anthropic/claude-3.7-sonnet"

    adapter.clear()
    cleared_cfg = json.loads((cfg_dir / "opencode.json").read_text(encoding="utf-8"))
    assert "model" not in cleared_cfg


def test_cursor_adapter(tmp_path: Path) -> None:
    db_file = tmp_path / "state.vscdb"
    adapter = CursorAdapter(db_path_override=db_file)
    assert adapter.name == "cursor"

    spec = MergedProviderSpec(
        name="deepseek",
        base_url="https://api.deepseek.com/v1",
        api_key="sk-cursor-test",
        protocol="openai",
        model="deepseek-chat",
    )
    adapter.apply(spec)

    assert db_file.is_file()
    con = sqlite3.connect(str(db_file))
    try:
        rows = dict(con.execute("SELECT key, value FROM ItemTable").fetchall())
    finally:
        con.close()

    assert "applicationUser" in rows
    app_user = json.loads(rows["applicationUser"])
    assert app_user["openAIBaseUrl"] == "https://api.deepseek.com/v1"
    assert "secret://cursorAuth/openAIKey" in rows

    status = adapter.get_status()
    assert status.installed is True
    assert status.active_type == "provider"

    adapter.clear()
    con = sqlite3.connect(str(db_file))
    try:
        rows = dict(con.execute("SELECT key, value FROM ItemTable").fetchall())
    finally:
        con.close()
    app_user = json.loads(rows["applicationUser"])
    assert "openAIBaseUrl" not in app_user
    assert "secret://cursorAuth/openAIKey" not in rows


def test_claude_adapter(tmp_path: Path) -> None:
    settings_file = tmp_path / "claude" / "settings.json"
    adapter = ClaudeAdapter(settings_path=settings_file)
    assert adapter.name == "claude"

    spec = MergedProviderSpec(
        name="claude-custom",
        base_url="https://proxy.example.com/v1",
        api_key="sk-ant-test",
        protocol="anthropic",
        model="claude-3-7-sonnet-20250219",
    )
    adapter.apply(spec)

    assert settings_file.is_file()
    data = json.loads(settings_file.read_text(encoding="utf-8"))
    assert data["env"]["ANTHROPIC_BASE_URL"] == "https://proxy.example.com"
    assert data["env"]["ANTHROPIC_AUTH_TOKEN"] == "sk-ant-test"
    assert data["env"]["ANTHROPIC_API_KEY"] == "sk-ant-test"
    assert data["env"]["ANTHROPIC_MODEL"] == "claude-3-7-sonnet-20250219"
    assert data["env"]["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "claude-3-7-sonnet-20250219"

    status = adapter.get_status()
    assert status.installed is True
    assert status.active_type == "provider"

    adapter.clear()
    cleared = json.loads(settings_file.read_text(encoding="utf-8"))
    assert "ANTHROPIC_BASE_URL" not in cleared["env"]


def test_agy_adapter(tmp_path: Path) -> None:
    cli_dir = tmp_path / "antigravity-cli"
    adapter = AgyAdapter(cli_dir=cli_dir)
    assert adapter.name == "agy"

    # Generic apply must be rejected
    spec = MergedProviderSpec(
        name="openai",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
    )
    with pytest.raises(SwitchError) as excinfo:
        adapter.apply(spec)
    assert "Antigravity uses Google OAuth accounts" in str(excinfo.value)

    # Account apply
    acc = AccountSpec(
        target="agy",
        name="personal",
        account_type="google-oauth",
        token_data={"access_token": "ya29.secret-token"},
    )
    adapter.apply_account(acc)
    assert (cli_dir / "antigravity-oauth-token").is_file()
    token_json = json.loads(
        (cli_dir / "antigravity-oauth-token").read_text(encoding="utf-8")
    )
    assert token_json["access_token"] == "ya29.secret-token"

    status = adapter.get_status()
    assert status.installed is True
    assert status.active_type == "account"

    adapter.clear()
    assert not (cli_dir / "antigravity-oauth-token").exists()


def test_pi_adapter(tmp_path: Path) -> None:
    cfg_file = tmp_path / ".pi" / "config.yaml"
    adapter = PiAdapter(config_path=cfg_file)
    assert adapter.name == "pi"

    spec = MergedProviderSpec(
        name="siliconflow",
        base_url="https://api.siliconflow.cn/v1",
        api_key="sk-pi-test",
        protocol="openai",
        model="Qwen/Qwen2.5-Coder-32B-Instruct",
        options={"temperature": 0.2},
    )
    adapter.apply(spec)

    assert cfg_file.is_file()
    data = yaml.safe_load(cfg_file.read_text(encoding="utf-8"))
    assert data["model_provider"]["name"] == "siliconflow"
    assert data["model_provider"]["api_base"] == "https://api.siliconflow.cn/v1"
    assert data["model_provider"]["api_key"] == "sk-pi-test"
    assert data["model_provider"]["model"] == "Qwen/Qwen2.5-Coder-32B-Instruct"
    assert data["model_provider"]["options"] == {"temperature": 0.2}

    status = adapter.get_status()
    assert status.installed is True
    assert status.active_type == "provider"
    assert status.active_name == "siliconflow"

    adapter.clear()
    cleared = yaml.safe_load(cfg_file.read_text(encoding="utf-8"))
    assert "model_provider" not in cleared


def test_registry() -> None:
    all_adps = get_all_adapters()
    assert set(all_adps.keys()) == {
        "codex",
        "opencode",
        "cursor",
        "claude",
        "agy",
        "pi",
    }
    assert get_adapter("codex").name == "codex"
    assert get_adapter("PI").name == "pi"

    with pytest.raises(SwitchError) as excinfo:
        get_adapter("unknown-client")
    assert "unknown target client: 'unknown-client'" in str(excinfo.value)


def test_adapter_capabilities() -> None:
    codex = get_adapter("codex")
    assert codex.supports_fast is True
    assert codex.supports_web_search is True
    assert codex.supports_wire_api is True

    for name in ["claude", "opencode", "cursor", "agy", "pi"]:
        adp = get_adapter(name)
        assert adp.supports_fast is False
        assert adp.supports_web_search is False
        assert adp.supports_wire_api is False
