from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

import cli.claude_provider as cp
import lib.claude.store as cl_st


@pytest.fixture
def claude_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    tool_home = tmp_path / ".claude-provider"
    settings_file = tmp_path / ".claude" / "settings.json"
    tool_home.mkdir(parents=True)
    settings_file.parent.mkdir(parents=True)
    monkeypatch.setattr(cp, "TOOL_HOME", tool_home)
    monkeypatch.setattr(cp, "TOOL_CONFIG_PATH", tool_home / "config.json")
    monkeypatch.setattr(cp, "AUTH_STORE_DIR", tool_home / "auth")
    monkeypatch.setattr(cp, "RECENT_PATH", tool_home / "recent.json")
    monkeypatch.setattr(cp, "DEFAULT_SETTINGS_PATH", settings_file)
    return {
        "tool_home": tool_home,
        "settings": settings_file,
        "config": tool_home / "config.json",
        "auth": tool_home / "auth",
    }


def _add_provider(
    claude_paths: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
    *,
    name: str,
    base_url: str,
    key: str,
) -> None:
    monkeypatch.setattr(cp, "read_api_key", lambda from_stdin: key)
    assert (
        cp.main(
            [
                "add",
                base_url,
                "--provider",
                name,
                "--api-key-stdin",
            ]
        )
        == 0
    )


def test_switch_writes_env_and_preserves_other_settings(
    claude_paths: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings_file = claude_paths["settings"]
    settings_file.write_text(
        json.dumps(
            {
                "model": "claude-3-5-sonnet",
                "permissions": {"allow": ["Bash"]},
            }
        ),
        encoding="utf-8",
    )
    _add_provider(
        claude_paths,
        monkeypatch,
        name="alpha",
        base_url="https://alpha.example.com/v1",
        key="placeholder-alpha-key",
    )

    assert cp.main(["switch", "alpha"]) == 0

    data = json.loads(settings_file.read_text(encoding="utf-8"))
    assert data["model"] == "claude-3-5-sonnet"
    assert data["permissions"] == {"allow": ["Bash"]}
    assert data["env"]["ANTHROPIC_BASE_URL"] == "https://alpha.example.com/v1"
    assert data["env"]["ANTHROPIC_AUTH_TOKEN"] == "placeholder-alpha-key"


def test_switch_dry_run_does_not_write(
    claude_paths: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings_file = claude_paths["settings"]
    settings_file.write_text('{"permissions": {"allow": ["Bash"]}}\n', encoding="utf-8")
    before = settings_file.read_bytes()
    _add_provider(
        claude_paths,
        monkeypatch,
        name="alpha",
        base_url="https://alpha.example.com/v1",
        key="placeholder-alpha-key",
    )

    assert cp.main(["switch", "alpha", "--dry-run"]) == 0

    assert settings_file.read_bytes() == before


def test_auth_show_never_prints_secret(
    claude_paths: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _add_provider(
        claude_paths,
        monkeypatch,
        name="alpha",
        base_url="https://alpha.example.com/v1",
        key="placeholder-alpha-key",
    )

    assert cp.main(["auth", "show", "alpha"]) == 0

    output = capsys.readouterr().out
    assert "placeholder-alpha-key" not in output
    assert "ANTHROPIC_AUTH_TOKEN: configured" in output


def test_parser_exposes_shared_registry_commands() -> None:
    parser = cp.build_parser()
    action = next(
        item for item in parser._actions if isinstance(item, argparse._SubParsersAction)
    )
    commands = set(action.choices)
    from lib.common.registry import COMMON_COMMANDS

    shared = {spec.name for spec in COMMON_COMMANDS if spec.capability is None}
    assert shared <= commands


def test_doctor_detects_missing_auth_profile(
    claude_paths: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _add_provider(
        claude_paths,
        monkeypatch,
        name="alpha",
        base_url="https://alpha.example.com/v1",
        key="placeholder-alpha-key",
    )
    (claude_paths["auth"] / "alpha.json").unlink()

    assert cp.doctor(fix=False) == 1
    assert "missing auth snapshot" in capsys.readouterr().out


def test_config_set_model_updates_tool_config(
    claude_paths: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _add_provider(
        claude_paths,
        monkeypatch,
        name="alpha",
        base_url="https://alpha.example.com/v1",
        key="placeholder-alpha-key",
    )

    assert cp.main(["config", "set", "alpha", "--model", "claude-4"]) == 0

    state = cl_st.load_provider_state()
    assert state.providers["alpha"]["model"] == "claude-4"


def test_rename_active_provider_updates_state(
    claude_paths: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _add_provider(
        claude_paths,
        monkeypatch,
        name="alpha",
        base_url="https://alpha.example.com/v1",
        key="placeholder-alpha-key",
    )
    assert cp.main(["switch", "alpha"]) == 0

    assert cp.main(["rename", "alpha", "alpha-new"]) == 0

    state = cl_st.load_provider_state()
    assert state.active_provider == "alpha-new"


def test_ping_reports_missing_claude_binary(
    claude_paths: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _add_provider(
        claude_paths,
        monkeypatch,
        name="alpha",
        base_url="https://alpha.example.com/v1",
        key="placeholder-alpha-key",
    )

    import lib.claude.ping as cl_ping

    def fake_which(_name: str) -> str | None:
        return None

    monkeypatch.setattr(cl_ping.shutil, "which", fake_which)

    assert cp.main(["ping", "alpha"]) == 1
    captured = capsys.readouterr()
    assert "'claude' binary not found on PATH" in captured.err


def test_add_from_settings_snapshots_env_and_model_overrides(
    claude_paths: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claude_paths["settings"].write_text(
        json.dumps(
            {
                "env": {
                    "ANTHROPIC_BASE_URL": "http://127.0.0.1:4000",
                    "ANTHROPIC_API_KEY": "cis-local",
                    "ANTHROPIC_MODEL": "deepseek-v4-flash",
                    "ANTHROPIC_DEFAULT_OPUS_MODEL": "deepseek-v4-pro[1m]",
                },
                "modelOverrides": {"deepseek-v4-flash": {"maxTokens": 200000}},
            }
        ),
        encoding="utf-8",
    )

    assert (
        cp.main(
            [
                "add",
                "--from-settings",
                "--provider",
                "cistern",
            ]
        )
        == 0
    )

    state = cl_st.load_provider_state()
    config = state.providers["cistern"]
    assert config["base_url"] == "http://127.0.0.1:4000"
    assert config["model_overrides"] == {"deepseek-v4-flash": {"maxTokens": 200000}}
    assert config["env"]["ANTHROPIC_MODEL"] == "deepseek-v4-flash"
    assert config["env"]["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "deepseek-v4-pro[1m]"

    auth = json.loads(
        (claude_paths["auth"] / "cistern.json").read_text(encoding="utf-8")
    )
    assert auth == {"ANTHROPIC_API_KEY": "cis-local"}


def test_switch_preserves_model_env_from_provider(
    claude_paths: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claude_paths["settings"].write_text(
        json.dumps({"env": {"EXISTING": "keep-me"}}), encoding="utf-8"
    )
    monkeypatch.setattr(cp, "read_api_key", lambda from_stdin: "sk-deepseek")
    assert (
        cp.main(
            [
                "add",
                "https://api.deepseek.com/anthropic",
                "--provider",
                "deepseek",
                "--model",
                "deepseek-v4-flash[1m]",
                "--env",
                "ANTHROPIC_DEFAULT_OPUS_MODEL=deepseek-v4-pro[1m]",
                "--api-key-stdin",
            ]
        )
        == 0
    )

    assert cp.main(["switch", "deepseek"]) == 0

    data = json.loads(claude_paths["settings"].read_text(encoding="utf-8"))
    assert data["env"]["EXISTING"] == "keep-me"
    assert data["env"]["ANTHROPIC_BASE_URL"] == "https://api.deepseek.com/anthropic"
    assert data["env"]["ANTHROPIC_AUTH_TOKEN"] == "sk-deepseek"
    assert data["env"]["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "deepseek-v4-pro[1m]"
    assert "ANTHROPIC_API_KEY" not in data["env"]


def test_switch_cleans_managed_env_and_model_overrides(
    claude_paths: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claude_paths["settings"].write_text(
        json.dumps(
            {
                "env": {
                    "ANTHROPIC_BASE_URL": "http://127.0.0.1:4000",
                    "ANTHROPIC_API_KEY": "cis-local",
                    "ANTHROPIC_MODEL": "deepseek-v4-flash",
                },
                "modelOverrides": {"deepseek-v4-flash": {"maxTokens": 200000}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cp, "read_api_key", lambda from_stdin: "sk-deepseek")
    assert (
        cp.main(
            [
                "add",
                "https://api.deepseek.com/anthropic",
                "--provider",
                "deepseek",
                "--env",
                "ANTHROPIC_DEFAULT_OPUS_MODEL=deepseek-v4-pro[1m]",
                "--api-key-stdin",
            ]
        )
        == 0
    )

    assert cp.main(["switch", "deepseek"]) == 0
    data = json.loads(claude_paths["settings"].read_text(encoding="utf-8"))
    assert "ANTHROPIC_API_KEY" not in data["env"]
    assert data["env"]["ANTHROPIC_AUTH_TOKEN"] == "sk-deepseek"
    assert "modelOverrides" not in data


def test_add_requires_api_key(
    claude_paths: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    assert cp.main(["add", "https://alpha.example.com/v1", "secret-key"]) == 1
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "secret-key" not in combined
    assert "must not be passed as a command argument" in combined


def test_models_sync_saves_provider_models(
    claude_paths: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _add_provider(
        claude_paths,
        monkeypatch,
        name="alpha",
        base_url="https://alpha.example.com/v1",
        key="placeholder-alpha-key",
    )
    import lib.claude.models as cl_models

    monkeypatch.setattr(
        cl_models,
        "fetch_provider_models",
        lambda base_url, api_key, protocol, models_url_override=None: [
            "model-a",
            "model-b",
        ],
    )

    assert cp.main(["models", "sync", "alpha"]) == 0

    models = cl_models.load_provider_models("alpha")
    assert models == ["model-a", "model-b"]


def test_models_set_updates_env_and_settings(
    claude_paths: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claude_paths["settings"].write_text(
        json.dumps({"env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:4000"}}),
        encoding="utf-8",
    )
    _add_provider(
        claude_paths,
        monkeypatch,
        name="alpha",
        base_url="http://127.0.0.1:4000",
        key="placeholder-alpha-key",
    )

    models_path = claude_paths["tool_home"] / "models" / "alpha.json"
    models_path.parent.mkdir(parents=True, exist_ok=True)
    models_path.write_text(
        json.dumps({"provider": "alpha", "models": ["model-a", "model-b"]}),
        encoding="utf-8",
    )

    assert cp.main(["models", "set", "model-b", "alpha"]) == 0

    data = json.loads(claude_paths["settings"].read_text(encoding="utf-8"))
    assert data["env"]["ANTHROPIC_MODEL"] == "model-b"
    assert data["env"]["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "model-b"
    state = cl_st.load_provider_state()
    assert state.providers["alpha"]["model"] == "model-b"
