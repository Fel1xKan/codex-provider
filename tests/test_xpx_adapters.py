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
    assert doc["model_catalog_json"] == str(codex_home / "models.json")
    pv_entry = doc["model_providers"]["deepseek"]
    assert pv_entry["base_url"] == "https://api.deepseek.com/v1"
    assert pv_entry["wire_api"] == "chat"
    assert pv_entry["http_headers"]["x-user"] == "dev1"

    # Verify models.json
    assert (codex_home / "models.json").is_file()
    models_data = json.loads((codex_home / "models.json").read_text(encoding="utf-8"))
    assert "models" in models_data
    slugs = {m["slug"] for m in models_data["models"]}
    assert "deepseek-reasoner" in slugs

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
    assert "model_catalog_json" not in cleared_doc
    assert not (codex_home / "models.json").is_file()


def test_codex_catalog_retention_and_refresh(tmp_path: Path) -> None:
    codex_home = tmp_path / ".codex"
    codex_home.mkdir(parents=True)
    # Pre-existing config with previous session model
    (codex_home / "config.toml").write_text(
        'model = "gpt-5.6-luna"\nmodel_provider = "openai"\n', encoding="utf-8"
    )

    adapter = CodexAdapter(home=codex_home)
    spec = MergedProviderSpec(
        name="cistern",
        base_url="http://127.0.0.1:4000/v1",
        api_key="sk-test",
        protocol="openai",
        model="deepseek-v4-flash",
    )
    adapter.apply(spec)

    # Both previous session model and applied model must exist in models.json
    assert (codex_home / "models.json").is_file()
    models_data = json.loads((codex_home / "models.json").read_text(encoding="utf-8"))
    slugs = {m["slug"] for m in models_data["models"]}
    assert "deepseek-v4-flash" in slugs
    assert "gpt-5.6-luna" in slugs

    # Verify refresh_catalog
    assert adapter.refresh_catalog("cistern") is True
    assert adapter.refresh_catalog("other_provider") is False


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
    assert "anthropic/claude-3.7-sonnet" in prov["models"]

    # Verify models.json
    assert (cfg_dir / "models.json").is_file()
    models_json = json.loads((cfg_dir / "models.json").read_text(encoding="utf-8"))
    assert models_json["provider"] == "openrouter"
    model_ids = {m["id"] for m in models_json["models"]}
    assert "anthropic/claude-3.7-sonnet" in model_ids

    adapter.clear()
    cleared_cfg = json.loads((cfg_dir / "opencode.json").read_text(encoding="utf-8"))
    assert "model" not in cleared_cfg
    assert not (cfg_dir / "models.json").is_file()


def test_opencode_catalog_retention_and_refresh(tmp_path: Path) -> None:
    cfg_dir = tmp_path / "config" / "opencode"
    data_dir = tmp_path / "data" / "opencode"
    cfg_dir.mkdir(parents=True)
    # Pre-existing config with previous session model
    (cfg_dir / "opencode.json").write_text(
        json.dumps(
            {
                "provider": {
                    "cistern": {
                        "options": {"baseURL": "http://127.0.0.1:4000/v1"},
                    }
                },
                "model": "cistern/gpt-5.6-luna",
            }
        ),
        encoding="utf-8",
    )

    adapter = OpenCodeAdapter(config_dir=cfg_dir, data_dir=data_dir)
    spec = MergedProviderSpec(
        name="cistern",
        base_url="http://127.0.0.1:4000/v1",
        api_key="sk-test",
        protocol="openai",
        model="deepseek-v4-flash",
    )
    adapter.apply(spec)

    # Both previous session model and applied model must exist in models
    cfg_data = json.loads((cfg_dir / "opencode.json").read_text(encoding="utf-8"))
    models_dict = cfg_data["provider"]["cistern"]["models"]
    assert "deepseek-v4-flash" in models_dict
    assert "gpt-5.6-luna" in models_dict

    assert (cfg_dir / "models.json").is_file()
    models_json = json.loads((cfg_dir / "models.json").read_text(encoding="utf-8"))
    slugs = {m["id"] for m in models_json["models"]}
    assert "deepseek-v4-flash" in slugs
    assert "gpt-5.6-luna" in slugs

    # Verify refresh_catalog
    assert adapter.refresh_catalog("cistern") is True
    assert adapter.refresh_catalog("other_provider") is False


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
    assert app_user["xpxProviderName"] == "deepseek"
    assert "secret://cursorAuth/openAIKey" in rows

    # Verify catalog models emitted into availableDefaultModels2
    catalog = app_user.get("availableDefaultModels2", [])
    catalog_names = {m.get("serverModelName") for m in catalog}
    assert "deepseek-chat" in catalog_names

    # Verify multi-surface model config
    composer = app_user["aiSettings"]["modelConfig"]["composer"]
    assert composer["modelName"] == "deepseek-chat"
    cmdk = app_user["aiSettings"]["modelConfig"]["cmd-k"]
    assert cmdk["modelName"] == "deepseek-chat"

    status = adapter.get_status()
    assert status.installed is True
    assert status.active_type == "provider"
    assert status.active_name == "deepseek"

    # Verify refresh_catalog
    assert adapter.refresh_catalog("deepseek") is True
    assert adapter.refresh_catalog("other_provider") is False

    adapter.clear()
    con = sqlite3.connect(str(db_file))
    try:
        rows = dict(con.execute("SELECT key, value FROM ItemTable").fetchall())
    finally:
        con.close()
    app_user = json.loads(rows["applicationUser"])
    assert "openAIBaseUrl" not in app_user
    assert "xpxProviderName" not in app_user
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
    assert data["env"]["XPX_PROVIDER_NAME"] == "claude-custom"
    assert data["env"]["ANTHROPIC_MODEL"] == "claude-3-7-sonnet-20250219"
    assert data["env"]["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "claude-3-7-sonnet-20250219"

    status = adapter.get_status()
    assert status.installed is True
    assert status.active_type == "provider"
    assert status.active_name == "claude-custom"

    # Verify refresh_catalog
    assert adapter.refresh_catalog("other_provider") is False

    adapter.clear()
    cleared = json.loads(settings_file.read_text(encoding="utf-8"))
    assert "ANTHROPIC_BASE_URL" not in cleared["env"]
    assert "XPX_PROVIDER_NAME" not in cleared["env"]


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

    # Verify settings.json and auth.json in ~/.pi/agent/
    settings_file = tmp_path / ".pi" / "agent" / "settings.json"
    auth_file = tmp_path / ".pi" / "agent" / "auth.json"
    assert settings_file.is_file()
    assert auth_file.is_file()
    st_data = json.loads(settings_file.read_text(encoding="utf-8"))
    assert st_data["defaultProvider"] == "siliconflow"
    assert st_data["defaultModel"] == "Qwen/Qwen2.5-Coder-32B-Instruct"
    auth_data = json.loads(auth_file.read_text(encoding="utf-8"))
    assert auth_data["siliconflow"]["type"] == "api_key"
    assert auth_data["siliconflow"]["key"] == "sk-pi-test"

    # Verify models.json in ~/.pi/agent/
    models_file = tmp_path / ".pi" / "agent" / "models.json"
    assert models_file.is_file()
    models_data = json.loads(models_file.read_text(encoding="utf-8"))
    assert "siliconflow" in models_data["providers"]
    prov_models = models_data["providers"]["siliconflow"]["models"]
    m_ids = {m["id"] for m in prov_models}
    assert "Qwen/Qwen2.5-Coder-32B-Instruct" in m_ids

    # Verify applying without pinning thinking level
    spec_applied = MergedProviderSpec(
        name="siliconflow",
        base_url="https://api.siliconflow.cn/v1",
        api_key="sk-pi-test",
        protocol="openai",
        model="Qwen/Qwen2.5-Coder-32B-Instruct",
    )
    adapter.apply(spec_applied)
    st_data_eff = json.loads(settings_file.read_text(encoding="utf-8"))
    assert "defaultThinkingLevel" not in st_data_eff
    assert "modelThinkingLevels" not in st_data_eff
    status_eff = adapter.get_status()
    assert status_eff.extra_summary == ""

    # Verify refresh_catalog
    assert adapter.refresh_catalog("siliconflow") is True
    assert adapter.refresh_catalog("other") is False

    adapter.clear()
    cleared = yaml.safe_load(cfg_file.read_text(encoding="utf-8"))
    assert "model_provider" not in cleared
    if models_file.is_file():
        cleared_models = json.loads(models_file.read_text(encoding="utf-8"))
        assert "siliconflow" not in cleared_models.get("providers", {})
    if settings_file.is_file():
        cleared_st = json.loads(settings_file.read_text(encoding="utf-8"))
        assert "defaultProvider" not in cleared_st
        assert "defaultModel" not in cleared_st
        assert "defaultThinkingLevel" not in cleared_st
    if auth_file.is_file():
        cleared_auth = json.loads(auth_file.read_text(encoding="utf-8"))
        assert "siliconflow" not in cleared_auth


def test_pi_thinking_support_and_anthropic_protocol(tmp_path: Path) -> None:
    from lib.xpx.adapters.pi import _build_pi_model_entry, _resolve_model_effort
    from lib.xpx.store.catalog_store import ModelMetadata

    # Test _resolve_model_effort from catalog and aliases
    assert _resolve_model_effort("deepseek", "deepseek-v4-flash") == "high"
    assert _resolve_model_effort("deepseek", "deepseek-chat") == "high"
    assert _resolve_model_effort("deepseek", "deepseek-reasoner") == "high"
    assert _resolve_model_effort("unknown", "random-text-model") is None

    # Test _build_pi_model_entry with catalog reasoning levels
    meta_reasoning = ModelMetadata(
        id="deepseek-v4-flash",
        display_name="DeepSeek V4 Flash",
        context_window=1000000,
        max_output_tokens=384000,
        supported_reasoning_levels=["none", "low", "high", "max"],
        default_reasoning_level="high",
    )
    entry_reasoning = _build_pi_model_entry(meta_reasoning)
    assert entry_reasoning["reasoning"] is True
    assert "thinkingLevelMap" in entry_reasoning
    t_map = entry_reasoning["thinkingLevelMap"]
    assert "off" not in t_map or t_map["off"] is not None
    assert t_map.get("high") == "high"
    assert t_map.get("low") == "low"

    # Explicit applied effort enables reasoning even on uncataloged models
    meta_custom = ModelMetadata(
        id="custom-uncataloged-model",
        display_name="Custom Uncataloged",
        context_window=128000,
        max_output_tokens=8192,
        supported_reasoning_levels=[],
        default_reasoning_level=None,
    )
    entry_custom_no_eff = _build_pi_model_entry(meta_custom)
    assert entry_custom_no_eff["reasoning"] is False

    entry_custom_eff = _build_pi_model_entry(meta_custom, applied_effort="high")
    assert entry_custom_eff["reasoning"] is True

    # Explicitly disabled model
    meta_disabled = ModelMetadata(
        id="dumb-model",
        display_name="Dumb Model",
        context_window=128000,
        max_output_tokens=8192,
        supported_reasoning_levels=["none"],
        default_reasoning_level=None,
    )
    entry_disabled = _build_pi_model_entry(meta_disabled)
    assert entry_disabled["reasoning"] is False

    # Test PiAdapter with anthropic protocol
    cfg_file = tmp_path / ".pi" / "config.yaml"
    adapter = PiAdapter(config_path=cfg_file)
    assert "anthropic" in adapter.supported_protocols
    assert "openai" in adapter.supported_protocols

    spec_anthropic = MergedProviderSpec(
        name="deepseek",
        base_url="https://api.deepseek.com/anthropic",
        api_key="sk-test-deepseek",
        protocol="anthropic",
        model="deepseek-v4-flash",
    )
    adapter.apply(spec_anthropic)

    models_file = tmp_path / ".pi" / "agent" / "models.json"
    settings_file = tmp_path / ".pi" / "agent" / "settings.json"
    assert models_file.is_file()
    assert settings_file.is_file()

    models_data = json.loads(models_file.read_text(encoding="utf-8"))
    prov = models_data["providers"]["deepseek"]
    assert prov["api"] == "anthropic-messages"
    assert prov["baseUrl"] == "https://api.deepseek.com/anthropic"
    assert prov["apiKey"] == "sk-test-deepseek"

    applied_m = next(m for m in prov["models"] if m["id"] == "deepseek-v4-flash")
    assert applied_m["reasoning"] is True
    m_tmap = applied_m["thinkingLevelMap"]
    assert "off" not in m_tmap or m_tmap["off"] is not None

    st_data = json.loads(settings_file.read_text(encoding="utf-8"))
    assert st_data["defaultProvider"] == "deepseek"
    assert st_data["defaultModel"] == "deepseek-v4-flash"
    assert "defaultThinkingLevel" not in st_data
    # Should not force "off" into modelThinkingLevels
    model_th = st_data.get("modelThinkingLevels", {})
    assert model_th.get("deepseek/deepseek-v4-flash") != "off"


def test_pi_adapter_base_url_normalization(tmp_path: Path) -> None:
    cfg_file = tmp_path / ".pi" / "config.yaml"
    adapter = PiAdapter(config_path=cfg_file)
    models_file = tmp_path / ".pi" / "agent" / "models.json"

    # Anthropic protocol should strip trailing /v1 because Anthropic SDK
    # appends /v1/messages
    spec_anthropic = MergedProviderSpec(
        name="cistern-anthropic",
        base_url="http://127.0.0.1:4000/v1",
        api_key="sk-test",
        protocol="anthropic",
        model="claude-3-7-sonnet",
    )
    adapter.apply(spec_anthropic)

    data = yaml.safe_load(cfg_file.read_text(encoding="utf-8"))
    assert data["model_provider"]["api_base"] == "http://127.0.0.1:4000"

    models_data = json.loads(models_file.read_text(encoding="utf-8"))
    prov = models_data["providers"]["cistern-anthropic"]
    assert prov["baseUrl"] == "http://127.0.0.1:4000"
    assert prov["api"] == "anthropic-messages"

    # OpenAI protocol should retain /v1 because OpenAI SDK appends /chat/completions
    spec_openai = MergedProviderSpec(
        name="cistern-openai",
        base_url="http://127.0.0.1:4000/v1",
        api_key="sk-test",
        protocol="openai",
        model="gpt-4o",
    )
    adapter.apply(spec_openai)

    data = yaml.safe_load(cfg_file.read_text(encoding="utf-8"))
    assert data["model_provider"]["api_base"] == "http://127.0.0.1:4000/v1"

    models_data = json.loads(models_file.read_text(encoding="utf-8"))
    prov_oa = models_data["providers"]["cistern-openai"]
    assert prov_oa["baseUrl"] == "http://127.0.0.1:4000/v1"
    assert prov_oa["api"] == "openai-completions"


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


def test_count_active_cli_instances(monkeypatch: pytest.MonkeyPatch) -> None:
    from lib.xpx.adapters.base import count_active_cli_instances

    class DummyProc:
        def __init__(self, stdout: str):
            self.stdout = stdout

    mock_ps = (
        "  PID ARGS\n"
        " 1001 /usr/bin/codex\n"
        " 1002 /home/user/.nvm/versions/node/v24/bin/codex\n"
        " 1003 /home/user/.codex/bin/codex app-server daemon pid-update-loop\n"
        " 1004 node /path/to/opencode\n"
        " 1005 opencode serve --port 4096\n"
    )
    monkeypatch.setattr("subprocess.run", lambda *a, **k: DummyProc(stdout=mock_ps))

    # Codex should count 1001 and 1002, but exclude 1003 (daemon pattern)
    c_codex = count_active_cli_instances("codex", ["app-server", "pid-update-loop"])
    assert c_codex == 2

    # OpenCode should count 1004, but exclude 1005 (serve pattern)
    c_opencode = count_active_cli_instances("opencode", ["serve", "web"])
    assert c_opencode == 1


def test_codex_refresh_daemon(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    codex_home = tmp_path / ".codex"
    adapter = CodexAdapter(home=codex_home)
    monkeypatch.setattr(adapter, "get_binary_path", lambda: "/usr/bin/codex")

    # 1. Neither socket nor pid exists -> no-op
    refreshed, note = adapter.refresh_daemon()
    assert refreshed is False
    assert note == ""

    # Create dummy daemon socket
    sock_dir = codex_home / "app-server-control"
    sock_dir.mkdir(parents=True)
    (sock_dir / "app-server-control.sock").touch()

    # 2. Active CLI instances running -> protected, kept intact
    monkeypatch.setattr(
        "lib.xpx.adapters.codex.count_active_cli_instances",
        lambda *a, **k: 3,
    )
    refreshed, note = adapter.refresh_daemon(force=False)
    assert refreshed is False
    assert "Detected 3 active codex instance(s)" in note
    assert "kept existing sessions intact" in note

    # 3. Force=True or 0 active instances -> restart executed
    executed_cmds = []

    class DummyResult:
        returncode = 0

    def mock_run(cmd, *a, **k):
        executed_cmds.append(cmd)
        return DummyResult()

    monkeypatch.setattr("subprocess.run", mock_run)
    refreshed, note = adapter.refresh_daemon(force=True)
    assert refreshed is True
    assert "Refreshed codex background daemon" in note
    assert ["/usr/bin/codex", "app-server", "daemon", "restart"] in executed_cmds


def test_opencode_refresh_daemon(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = OpenCodeAdapter()
    monkeypatch.setattr(adapter, "get_binary_path", lambda: "/usr/bin/opencode")
    state_dir = tmp_path / "opencode_state"
    state_dir.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    # 1. No daemon files and no systemd -> no-op
    monkeypatch.setattr("shutil.which", lambda _: None)
    refreshed, note = adapter.refresh_daemon()
    assert refreshed is False
    assert note == ""

    # Create opencode 2.0 service.json
    real_state = tmp_path / ".local" / "state" / "opencode"
    real_state.mkdir(parents=True)
    (real_state / "service.json").write_text("{}", encoding="utf-8")

    # 2. Active instances running -> protected
    monkeypatch.setattr(
        "lib.xpx.adapters.opencode.count_active_cli_instances",
        lambda *a, **k: 2,
    )
    refreshed, note = adapter.refresh_daemon(force=False)
    assert refreshed is False
    assert "Detected 2 active opencode instance(s)" in note

    # 3. Force=True -> restarts opencode 2.0 service daemon
    executed_cmds = []

    class DummyResult:
        returncode = 0

    def mock_run(cmd, *a, **k):
        executed_cmds.append(cmd)
        return DummyResult()

    monkeypatch.setattr("subprocess.run", mock_run)
    refreshed, note = adapter.refresh_daemon(force=True)
    assert refreshed is True
    assert "opencode 2.0 service daemon" in note
    assert ["/usr/bin/opencode", "service", "restart"] in executed_cmds


def test_claude_refresh_daemon(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = ClaudeAdapter()
    monkeypatch.setattr(adapter, "get_binary_path", lambda: "/usr/bin/claude")

    # 1. No background agents -> no-op
    class DummyEmptyResult:
        returncode = 0
        stdout = "[]"

    monkeypatch.setattr("subprocess.run", lambda *a, **k: DummyEmptyResult())
    refreshed, note = adapter.refresh_daemon()
    assert refreshed is False
    assert note == ""

    # 2. Active agents running & force=False -> protected
    class DummyActiveResult:
        returncode = 0
        stdout = json.dumps([{"id": "agent-1"}, {"id": "agent-2"}])

    monkeypatch.setattr("subprocess.run", lambda *a, **k: DummyActiveResult())
    refreshed, note = adapter.refresh_daemon(force=False)
    assert refreshed is False
    assert "Detected 2 active claude background session(s)" in note

    # 3. Force=True -> respawn executed
    executed_cmds = []

    def mock_run(cmd, *a, **k):
        executed_cmds.append(cmd)
        if "agents" in cmd:
            return DummyActiveResult()
        res = DummyActiveResult()
        res.returncode = 0
        return res

    monkeypatch.setattr("subprocess.run", mock_run)
    refreshed, note = adapter.refresh_daemon(force=True)
    assert refreshed is True
    assert "Respawned 2 claude background session(s)" in note
