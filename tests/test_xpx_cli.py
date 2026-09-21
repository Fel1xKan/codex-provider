from __future__ import annotations

import io
import json
import urllib.request
from pathlib import Path
from typing import Any

import pytest

import cli.xpx as xpx_cli
from lib.common.constants import VERSION
from lib.xpx.adapters.codex import CodexAdapter
from lib.xpx.store.account_store import AccountStore
from lib.xpx.store.provider_store import ProviderSpec, ProviderStore
from lib.xpx.store.state_store import StateStore


class MockResponse:
    def __init__(self, data: dict[str, Any] | list[Any], status: int = 200) -> None:
        self.payload = json.dumps(data).encode("utf-8")
        self.status = status
        self.fp = io.BytesIO(self.payload)

    def read(self, limit: int = -1) -> bytes:
        return self.fp.read(limit)

    def __enter__(self) -> MockResponse:
        return self

    def __exit__(self, *args: Any) -> None:
        pass


@pytest.fixture
def xpx_isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    fake_home = tmp_path / "userhome"
    fake_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.setenv("HOME", str(fake_home))

    home = fake_home / ".xpx"
    codex_home = fake_home / ".codex"
    opencode_cfg = fake_home / ".config" / "opencode"
    opencode_data = fake_home / ".local" / "share" / "opencode"
    claude_settings = fake_home / ".claude" / "settings.json"
    pi_config = fake_home / ".pi" / "config.yaml"
    cursor_db = (
        fake_home / ".config" / "Cursor" / "User" / "globalStorage" / "state.vscdb"
    )
    agy_dir = fake_home / ".gemini" / "antigravity-cli"

    monkeypatch.setenv("XPX_HOME", str(home))
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setenv("OPENCODE_CONFIG_DIR", str(opencode_cfg))
    monkeypatch.setenv("OPENCODE_DATA_DIR", str(opencode_data))
    monkeypatch.setenv("CLAUDE_SETTINGS_PATH", str(claude_settings))
    monkeypatch.setenv("PI_CONFIG_PATH", str(pi_config))
    monkeypatch.setenv("CURSOR_DB_PATH", str(cursor_db))
    monkeypatch.setenv("AGY_CLI_DIR", str(agy_dir))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setattr("shutil.which", lambda _: None)

    home.mkdir(parents=True, exist_ok=True)
    (home / ".migrated").touch()

    return home


def test_cli_version_and_help(
    xpx_isolated_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        xpx_cli.main(["--version"])
    assert excinfo.value.code == 0
    assert VERSION in capsys.readouterr().out

    assert xpx_cli.main([]) == 0
    assert "Unified AI Agent Provider Control Plane" in capsys.readouterr().out


def test_provider_crud_cli(
    xpx_isolated_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # 1. add
    rc = xpx_cli.main(
        [
            "add",
            "deepseek",
            "https://api.deepseek.com/v1",
            "--key",
            "sk-1234567890abcdef",
            "--default-model",
            "deepseek-reasoner",
            "--protocol",
            "openai",
        ]
    )
    assert rc == 0
    assert "Added provider 'deepseek'" in capsys.readouterr().out

    # 2. list
    rc = xpx_cli.main(["list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "deepseek" in out
    assert "deepseek-reasoner" in out

    # 3. list --json
    rc = xpx_cli.main(["list", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert len(data) == 1
    assert data[0]["name"] == "deepseek"

    # 4. show
    rc = xpx_cli.main(["show", "deepseek"])
    assert rc == 0
    show_out = capsys.readouterr().out
    assert "https://api.deepseek.com/v1" in show_out
    assert "sk-1...cdef" in show_out

    # 5. rename
    rc = xpx_cli.main(["rename", "deepseek", "deepseek-ai"])
    assert rc == 0
    assert ProviderStore().exists("deepseek-ai")
    assert not ProviderStore().exists("deepseek")

    # 6. delete
    rc = xpx_cli.main(["delete", "deepseek-ai", "--dry-run"])
    assert rc == 0
    assert "would delete" in capsys.readouterr().out
    assert ProviderStore().exists("deepseek-ai")

    rc = xpx_cli.main(["delete", "deepseek-ai"])
    assert rc == 0
    assert not ProviderStore().exists("deepseek-ai")


def test_auth_commands(
    xpx_isolated_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = ProviderStore()
    store.save(
        ProviderSpec(
            name="openai",
            base_url="https://api.openai.com/v1",
            api_key="sk-old1234567890",
        )
    )

    # auth show
    assert xpx_cli.main(["auth", "show", "openai"]) == 0
    assert "sk-o...7890" in capsys.readouterr().out

    # auth set
    assert xpx_cli.main(["auth", "set", "openai", "--key", "sk-new9876543210"]) == 0
    assert "Updated API Key for 'openai'" in capsys.readouterr().out
    assert store.require("openai").api_key == "sk-new9876543210"


def test_config_commands(
    xpx_isolated_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = ProviderStore()
    store.save(
        ProviderSpec(
            name="deepseek",
            base_url="https://api.deepseek.com/v1",
            api_key="sk-test",
        )
    )

    # Universal config set
    assert (
        xpx_cli.main(["config", "set", "deepseek", "--default-model", "deepseek-chat"])
        == 0
    )
    assert store.require("deepseek").default_model == "deepseek-chat"

    # Target-specific config set
    assert (
        xpx_cli.main(
            [
                "config",
                "set",
                "deepseek",
                "codex",
                "--fast",
                "--wire-api",
                "chat",
                "--header",
                "x-env=test",
            ]
        )
        == 0
    )
    overrides = store.require("deepseek").targets["codex"]
    assert overrides.fast is True
    assert overrides.wire_api == "chat"
    assert overrides.headers == {"x-env": "test"}

    # Config show
    assert xpx_cli.main(["config", "show", "deepseek", "codex"]) == 0
    out = capsys.readouterr().out
    assert "Fast Mode:     True" in out
    assert "Wire API:      chat" in out


def test_apply_and_memory_persistence(
    xpx_isolated_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = ProviderStore()
    store.save(
        ProviderSpec(
            name="deepseek",
            base_url="https://api.deepseek.com/v1",
            api_key="sk-secret-key",
            default_model="deepseek-reasoner",
        )
    )

    # Apply with ad-hoc overrides: fast mode and custom header
    rc = xpx_cli.main(
        [
            "apply",
            "codex",
            "deepseek",
            "--fast",
            "--header",
            "x-tenant=dev",
        ]
    )
    assert rc == 0
    assert "Applied 'deepseek/deepseek-reasoner' to codex" in capsys.readouterr().out

    # Verify native file was written
    codex_status = CodexAdapter().get_status()
    assert codex_status.installed is True
    assert codex_status.active_type == "provider"
    assert codex_status.active_name == "deepseek"
    assert codex_status.extra_summary == "fast"

    # Verify state store was updated
    state = StateStore().load()
    assert state.targets["codex"].active_name == "deepseek"
    assert state.targets["codex"].active_model == "deepseek-reasoner"

    # Verify automatic memory persistence:
    # deepseek profile in store now remembers fast & header!
    saved_overrides = store.require("deepseek").targets["codex"]
    assert saved_overrides.fast is True
    assert saved_overrides.headers.get("x-tenant") == "dev"

    # Model-only switch: :deepseek-chat
    rc = xpx_cli.main(["apply", "codex", ":deepseek-chat"])
    assert rc == 0
    assert StateStore().load().targets["codex"].active_model == "deepseek-chat"

    # Clear / reset
    rc = xpx_cli.main(["apply", "codex", "--clear"])
    assert rc == 0
    assert "Reset 'codex' to official/default state" in capsys.readouterr().out


def test_auth_set_linkage_reapply(
    xpx_isolated_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = ProviderStore()
    store.save(
        ProviderSpec(
            name="deepseek",
            base_url="https://api.deepseek.com/v1",
            api_key="sk-old-key",
            default_model="deepseek-reasoner",
        )
    )

    # 1. Apply to codex
    assert xpx_cli.main(["apply", "codex", "deepseek"]) == 0
    capsys.readouterr()

    # 2. Update API key via auth set
    assert xpx_cli.main(["auth", "set", "deepseek", "--key", "sk-brand-new-key"]) == 0
    out = capsys.readouterr().out
    assert "Re-applied to active targets: codex" in out

    # Verify codex auth file has new key
    auth_file = Path(CodexAdapter().auth_path)
    auth_data = json.loads(auth_file.read_text(encoding="utf-8"))
    assert auth_data["OPENAI_API_KEY"] == "sk-brand-new-key"


def test_models_cli(
    xpx_isolated_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = ProviderStore()
    store.save(
        ProviderSpec(
            name="openrouter",
            base_url="https://openrouter.ai/api/v1",
            api_key="sk-or",
        )
    )

    def mock_urlopen(req: urllib.request.Request, timeout: int = 15) -> MockResponse:
        return MockResponse({"data": [{"id": "deepseek-reasoner"}, {"id": "gpt-4o"}]})

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    assert xpx_cli.main(["models", "sync", "openrouter"]) == 0
    assert "Synced 2 models" in capsys.readouterr().out

    assert xpx_cli.main(["models", "list", "openrouter"]) == 0
    assert "deepseek-reasoner" in capsys.readouterr().out

    assert (
        xpx_cli.main(["models", "set", "deepseek-reasoner", "openrouter", "--default"])
        == 0
    )
    assert store.require("openrouter").default_model == "deepseek-reasoner"


def test_import_and_export_cli(
    xpx_isolated_env: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = ProviderStore()
    store.save(
        ProviderSpec(
            name="deepseek",
            base_url="https://api.deepseek.com/v1",
            api_key="sk-test",
        )
    )

    export_file = tmp_path / "backup.json"
    assert xpx_cli.main(["export", str(export_file)]) == 0
    assert export_file.is_file()

    # Clear store
    store.delete("deepseek")
    assert not store.exists("deepseek")

    # Import
    assert xpx_cli.main(["import", str(export_file)]) == 0
    assert store.exists("deepseek")


def test_doctor_cli(xpx_isolated_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from lib.xpx.store import ensure_xpx_dirs

    ensure_xpx_dirs()

    # Clean state
    assert xpx_cli.main(["doctor"]) == 0
    assert "Everything is healthy" in capsys.readouterr().out

    # Introduce an issue: point state to non-existent provider
    StateStore().set_target_state("codex", "provider", "ghost-provider")
    assert xpx_cli.main(["doctor"]) == 1
    assert "ghost-provider" in capsys.readouterr().out

    # Fix
    assert xpx_cli.main(["doctor", "--fix"]) == 0
    assert StateStore().get_target_state("codex") is None


def test_auto_migration_legacy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_home = tmp_path / "userhome"
    fake_home.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.setenv("HOME", str(fake_home))
    xpx_home = fake_home / ".xpx"
    monkeypatch.setenv("XPX_HOME", str(xpx_home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("OPENCODE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("OPENCODE_DATA_DIR", raising=False)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.delenv("AGY_CLI_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_SETTINGS_PATH", raising=False)
    monkeypatch.delenv("PI_CONFIG_PATH", raising=False)
    monkeypatch.delenv("CURSOR_DB_PATH", raising=False)
    monkeypatch.delenv("CURSOR_DIR", raising=False)
    monkeypatch.setattr("shutil.which", lambda _: None)

    # Setup legacy ~/.codex-provider
    codex_prov_dir = fake_home / ".codex-provider"
    codex_prov_dir.mkdir(parents=True)
    (codex_prov_dir / "config.toml").write_text(
        """
[model_providers.legacy_codex]
base_url = "https://legacy.codex.io/v1"
wire_api = "responses"
""",
        encoding="utf-8",
    )
    auth_dir = codex_prov_dir / "auth"
    auth_dir.mkdir()
    (auth_dir / "legacy_codex.json").write_text(
        '{"OPENAI_API_KEY": "sk-legacy-123"}', encoding="utf-8"
    )

    from lib.xpx.commands.cmd_import_export import auto_migrate_legacy_if_needed

    auto_migrate_legacy_if_needed()

    store = ProviderStore()
    assert store.exists("legacy_codex")
    spec = store.require("legacy_codex")
    assert spec.base_url == "https://legacy.codex.io/v1"
    assert spec.api_key == "sk-legacy-123"
    assert spec.targets["codex"].wire_api == "responses"
    assert (xpx_home / ".migrated").is_file()


def test_migrate_command_all_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_home = tmp_path / "userhome"
    fake_home.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.setenv("HOME", str(fake_home))
    xpx_home = fake_home / ".xpx"
    monkeypatch.setenv("XPX_HOME", str(xpx_home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("OPENCODE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("OPENCODE_DATA_DIR", raising=False)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.delenv("AGY_CLI_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_SETTINGS_PATH", raising=False)
    monkeypatch.delenv("PI_CONFIG_PATH", raising=False)
    monkeypatch.delenv("CURSOR_DB_PATH", raising=False)
    monkeypatch.delenv("CURSOR_DIR", raising=False)
    monkeypatch.setattr("shutil.which", lambda _: None)

    # 1. Codex (cpx)
    codex_prov_dir = fake_home / ".codex-provider"
    codex_prov_dir.mkdir(parents=True)
    (codex_prov_dir / "config.toml").write_text(
        """
[model_providers.leg_codex]
base_url = "https://api.codex.com/v1"
wire_api = "chat"
""",
        encoding="utf-8",
    )
    (codex_prov_dir / "auth").mkdir()
    (codex_prov_dir / "auth" / "leg_codex.json").write_text(
        '{"OPENAI_API_KEY": "sk-codex-1"}', encoding="utf-8"
    )

    # 2. OpenCode (opx)
    opencode_cfg = fake_home / ".config" / "opencode"
    opencode_cfg.mkdir(parents=True)
    (opencode_cfg / "opencode.json").write_text(
        json.dumps(
            {
                "provider": {
                    "leg_opencode": {
                        "options": {
                            "baseURL": "https://api.opencode.com/v1",
                            "apiKey": "sk-opencode-1",
                        },
                        "models": {"m1": {}},
                    }
                },
                "model": "leg_opencode/m1",
            }
        ),
        encoding="utf-8",
    )

    # 3. Claude (clpx)
    claude_prov_dir = fake_home / ".claude-provider"
    claude_prov_dir.mkdir(parents=True)
    (claude_prov_dir / "config.json").write_text(
        json.dumps(
            {
                "providers": {
                    "leg_claude": {
                        "base_url": "https://api.claude.com",
                        "model": "claude-3-7-sonnet",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    (claude_prov_dir / "auth").mkdir()
    (claude_prov_dir / "auth" / "leg_claude.json").write_text(
        '{"ANTHROPIC_API_KEY": "sk-ant-1"}', encoding="utf-8"
    )

    # 4. Cursor (cupx)
    cursor_dir = fake_home / ".cursor-provider" / "state"
    cursor_dir.mkdir(parents=True)
    (cursor_dir / "state.json").write_text(
        json.dumps(
            {
                "providers": {
                    "leg_cursor": {
                        "base_url": "https://api.cursor.com/v1",
                        "api_key": "sk-cur-1",
                    }
                },
                "accounts": {
                    "cur_user": {
                        "email": "cursor@test.com",
                        "display_name": "Cursor User",
                        "auth_data": {"token": "t-1"},
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    # 5. Antigravity (apx)
    agy_dir = fake_home / ".gemini" / "agy-provider" / "state"
    agy_dir.mkdir(parents=True)
    (agy_dir / "state.json").write_text(
        json.dumps(
            {
                "accounts": {
                    "agy_user": {
                        "email": "agy@test.com",
                        "display_name": "AGY User",
                        "token_data": {"access_token": "at-1"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    # First test dry-run
    ret_dry = xpx_cli.main(["migrate", "--dry-run"])
    assert ret_dry == 0
    out_dry = capsys.readouterr().out
    assert "Discovered legacy configurations (dry-run):" in out_dry
    assert "leg_codex" in out_dry
    assert "leg_opencode" in out_dry
    assert "leg_claude" in out_dry
    assert "leg_cursor" in out_dry
    assert "cur_user" in out_dry
    assert "agy_user" in out_dry
    assert "[dry-run]" in out_dry

    # Check store is still empty after dry-run
    p_store = ProviderStore()
    a_store = AccountStore()
    assert not p_store.list_all()
    assert not a_store.list_all()

    # Now run real migration
    ret_real = xpx_cli.main(["migrate"])
    assert ret_real == 0
    out_real = capsys.readouterr().out
    assert "Migration complete" in out_real

    # Verify all items stored
    assert p_store.exists("leg_codex")
    assert p_store.exists("leg_opencode")
    assert p_store.exists("leg_claude")
    assert p_store.exists("leg_cursor")
    assert p_store.require("leg_codex").api_key == "sk-codex-1"
    assert p_store.require("leg_opencode").default_model == "m1"
    assert p_store.require("leg_claude").protocol == "anthropic"

    assert a_store.exists("cursor", "cur_user")
    assert a_store.exists("agy", "agy_user")
    assert a_store.require("cursor", "cur_user").metadata["email"] == "cursor@test.com"
    assert a_store.require("agy", "agy_user").metadata["email"] == "agy@test.com"

    # Test import without args prints tip and runs smoothly
    ret_imp = xpx_cli.main(["import"])
    assert ret_imp == 0
    out_imp = capsys.readouterr().out
    assert "Tip: Run 'xpx migrate'" in out_imp


def test_apply_all_validation_and_positional_shift(
    xpx_isolated_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p_store = ProviderStore()
    p_store.save(
        ProviderSpec(
            name="deepseek",
            base_url="https://api.deepseek.com/v1",
            api_key="sk-test",
            default_model="deepseek-chat",
        )
    )

    # 1. agy directory and codex directory exist
    agy_dir = Path(monkeypatch.delenv("AGY_CLI_DIR", raising=False) or "")
    agy_dir = xpx_isolated_env.parent / "antigravity-cli"
    agy_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AGY_CLI_DIR", str(agy_dir))

    codex_home = xpx_isolated_env.parent / ".codex"
    codex_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    # 2. Test apply --all with no active configurations (onboarding guide)
    rc = xpx_cli.main(["apply", "--all"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "No active configurations found in xpx." in out
    assert "Getting Started:" in out

    # 3. Test apply agy directly without account
    rc = xpx_cli.main(["apply", "agy"])
    assert rc == 1
    err = capsys.readouterr().err
    assert (
        "Antigravity uses Google OAuth accounts. "
        "Use 'xpx apply agy --account <name>' instead." in err
    )

    # 4. Test apply --all deepseek (positional shift + agy skip)
    rc = xpx_cli.main(["apply", "--all", "deepseek"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "• Skipping 'agy' (uses Google OAuth accounts, not API providers)" in out
    assert "✔ Applied 'deepseek/deepseek-chat' to codex." in out

    # 5. Test apply --all deepseek/v3
    rc = xpx_cli.main(["apply", "--all", "deepseek/v3"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "• Skipping 'agy' (uses Google OAuth accounts, not API providers)" in out
    assert "✔ Applied 'deepseek/v3' to codex." in out

    # 6. Now codex has active state; apply --all syncs codex & skips agy
    rc = xpx_cli.main(["apply", "--all"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "✔ Applied provider 'deepseek/v3' to codex." in out
    assert "• Skipping 'agy' (no active configuration recorded)" in out


def test_native_cli_migration_and_global_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_home = tmp_path / "userhome"
    fake_home.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.setenv("HOME", str(fake_home))
    xpx_home = fake_home / ".xpx"
    monkeypatch.setenv("XPX_HOME", str(xpx_home))
    monkeypatch.setattr("shutil.which", lambda _: None)

    # 1. Native Codex config
    codex_home = fake_home / ".codex"
    codex_home.mkdir(parents=True)
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    (codex_home / "config.toml").write_text(
        """
model_provider = "nat_codex"
model = "m-codex-fast"

[model_providers.nat_codex]
base_url = "https://native.codex.com/v1"
wire_api = "responses"
""",
        encoding="utf-8",
    )

    # 2. Native OpenCode config
    opencode_cfg = fake_home / ".config" / "opencode"
    opencode_cfg.mkdir(parents=True)
    monkeypatch.setenv("OPENCODE_CONFIG_DIR", str(opencode_cfg))
    (opencode_cfg / "opencode.json").write_text(
        json.dumps(
            {
                "provider": {
                    "nat_opencode": {
                        "options": {"baseURL": "https://native.opencode.com/v1"},
                        "models": {"m-open": {}},
                    }
                },
                "model": "nat_opencode/m-open",
            }
        ),
        encoding="utf-8",
    )

    # 3. Native Claude config
    claude_settings = fake_home / ".claude" / "settings.json"
    claude_settings.parent.mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_SETTINGS_PATH", str(claude_settings))
    claude_settings.write_text(
        json.dumps(
            {
                "env": {
                    "ANTHROPIC_BASE_URL": "https://native.claude.com",
                    "ANTHROPIC_AUTH_TOKEN": "sk-nat-claude",
                    "ANTHROPIC_MODEL": "claude-native-model",
                }
            }
        ),
        encoding="utf-8",
    )

    # 4. Native Pi config
    pi_cfg = fake_home / ".pi" / "config.yaml"
    pi_cfg.parent.mkdir(parents=True)
    monkeypatch.setenv("PI_CONFIG_PATH", str(pi_cfg))
    pi_cfg.write_text(
        """
model_provider:
  name: nat_pi
  api_base: https://native.pi.com/v1
  api_key: sk-pi-key
  model: pi-fast
""",
        encoding="utf-8",
    )

    # Run migrate
    rc = xpx_cli.main(["migrate"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "nat_codex" in out
    assert "nat_opencode" in out
    assert "nat_pi" in out

    # Verify StateStore recorded active states
    state = StateStore().load()
    assert state.targets["codex"].active_name == "nat_codex"
    assert state.targets["codex"].active_model == "m-codex-fast"
    assert state.targets["opencode"].active_name == "nat_opencode"
    assert state.targets["opencode"].active_model == "m-open"
    assert state.targets["claude"].active_name == "claude-custom"
    assert state.targets["pi"].active_name == "nat_pi"

    # Run apply --all in global sync mode
    rc = xpx_cli.main(["apply", "--all"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "✔ Applied provider 'nat_codex/m-codex-fast' to codex." in out
    assert "✔ Applied provider 'nat_opencode/m-open' to opencode." in out
    assert "✔ Applied provider 'claude-custom/claude-native-model' to claude." in out
    assert "✔ Applied provider 'nat_pi/pi-fast' to pi." in out


def test_migrate_force_option(
    xpx_isolated_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake_home = xpx_isolated_env.parent
    codex_home = fake_home / ".codex"
    codex_home.mkdir(parents=True)
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    # Initial codex config
    (codex_home / "config.toml").write_text(
        """
model_provider = "my_codex"
model = "model-v1"

[model_providers.my_codex]
base_url = "https://codex.v1.com/v1"
""",
        encoding="utf-8",
    )

    # 1. First migration
    rc = xpx_cli.main(["migrate"])
    assert rc == 0
    capsys.readouterr()

    pv = ProviderStore().require("my_codex")
    assert pv.base_url == "https://codex.v1.com/v1"
    st = StateStore().load()
    assert st.targets["codex"].active_name == "my_codex"

    # Manually switch active state in xpx to something else
    StateStore().set_target_state("codex", "provider", "manual_provider")

    # Native config changes to v2
    (codex_home / "config.toml").write_text(
        """
model_provider = "my_codex"
model = "model-v2"

[model_providers.my_codex]
base_url = "https://codex.v2.com/v1"
""",
        encoding="utf-8",
    )

    # 2. Run migrate without --force: should keep manual_provider and existing base_url
    rc = xpx_cli.main(["migrate"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Skipped existing provider 'my_codex' (use --force to overwrite)" in out
    assert "Kept active state for codex" in out
    assert "use --force to overwrite" in out

    pv = ProviderStore().require("my_codex")
    assert pv.base_url == "https://codex.v1.com/v1"
    st = StateStore().load()
    assert st.targets["codex"].active_name == "manual_provider"

    # 3. Run migrate with --force: should overwrite provider and active state
    rc = xpx_cli.main(["migrate", "--force"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Overwrote provider 'my_codex'" in out
    assert "(--force)" in out

    pv = ProviderStore().require("my_codex")
    assert pv.base_url == "https://codex.v2.com/v1"
    st = StateStore().load()
    assert st.targets["codex"].active_name == "my_codex"
    assert st.targets["codex"].active_model == "model-v2"
