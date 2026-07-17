from __future__ import annotations

import json
import os
import tomllib
from pathlib import Path

import pytest
from conftest import IsolatedPaths

import codex_provider as cp


def test_auth_detail_never_prints_values(
    initialized_registry: IsolatedPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cp.show_auth(None) == 0
    output = capsys.readouterr().out
    assert "OPENAI_API_KEY: configured" in output
    assert "placeholder-alpha-key" not in output


def test_config_detail_redacts_sensitive_custom_values(
    initialized_registry: IsolatedPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    config = initialized_registry.tool_config.read_text(encoding="utf-8")
    initialized_registry.tool_config.write_text(
        config.replace(
            'name = "Alpha"',
            'name = "Alpha"\n'
            'extra_headers = { Authorization = "Bearer placeholder-secret" }\n'
            'access_token = "placeholder-token"',
        ),
        encoding="utf-8",
    )
    assert cp.show_provider_config("alpha") == 0
    output = capsys.readouterr().out
    assert "placeholder-secret" not in output
    assert "placeholder-token" not in output
    assert "[REDACTED]" in output


def test_auth_profile_path_rejects_traversal(isolated_paths: IsolatedPaths) -> None:
    with pytest.raises(cp.SwitchError, match="provider name"):
        cp.auth_profile_path("../../outside")


def test_registry_rejects_invalid_provider_from_toml(
    isolated_paths: IsolatedPaths,
) -> None:
    cp.ensure_tool_home()
    isolated_paths.tool_config.write_text(
        f'codex_dir = "{isolated_paths.codex_dir}"\n\n'
        '[model_providers."../../outside"]\n'
        'base_url = "https://example.com/v1"\n',
        encoding="utf-8",
    )
    with pytest.raises(cp.SwitchError, match="provider name"):
        cp.load_provider_registry()


def test_migration_reports_missing_current_provider(
    isolated_paths: IsolatedPaths,
) -> None:
    cp.ensure_tool_config()
    isolated_paths.codex_dir.mkdir(parents=True)
    (isolated_paths.codex_dir / "config.toml").write_text(
        'model_provider = "missing"\n\n'
        "[model_providers.known]\n"
        'base_url = "https://example.com/v1"\n',
        encoding="utf-8",
    )
    with pytest.raises(cp.SwitchError, match="missing from runtime provider blocks"):
        cp.migrate_provider_registry(dry_run=True)


def test_render_runtime_supports_valid_toml_and_preserves_comments() -> None:
    base = (
        "# keep this comment\n"
        "model_provider = 'alpha' # active provider\n\n"
        "[features]\n"
        "enabled = true\n\n"
        "[model_providers.alpha]\n"
        'base_url = "https://alpha.example.com/v1"\n'
    )
    rendered = cp.render_runtime_config(
        base,
        "beta",
        {
            "base_url": "https://beta.example.com/v1",
            "name": "line one\nline two",
            "extra_headers": {"x-team": "infra"},
        },
    )
    data = tomllib.loads(rendered)
    assert data["model_provider"] == "beta"
    assert list(data["model_providers"]) == ["beta"]
    assert data["model_providers"]["beta"]["name"] == "line one\nline two"
    assert data["features"]["enabled"] is True
    assert "# keep this comment" in rendered
    assert "# active provider" in rendered


def test_render_tool_config_preserves_unchanged_provider_comments() -> None:
    base = (
        "# registry comment\n"
        'codex_dir = "/tmp/codex"\n\n'
        "[model_providers.alpha]\n"
        'base_url = "https://alpha.example.com/v1" # keep provider comment\n'
        'name = "Alpha"\n'
    )
    rendered = cp.render_tool_config(
        Path("/tmp/codex"),
        {
            "alpha": {
                "base_url": "https://alpha.example.com/v1",
                "name": "Alpha",
            },
            "beta": {
                "base_url": "https://beta.example.com/v1",
                "name": "Beta",
            },
        },
        base,
    )
    data = tomllib.loads(rendered)
    assert set(data["model_providers"]) == {"alpha", "beta"}
    assert "# registry comment" in rendered
    assert "# keep provider comment" in rendered


def test_switch_rolls_back_every_file_when_commit_fails(
    initialized_registry: IsolatedPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_config = initialized_registry.codex_dir / "config.toml"
    runtime_auth = initialized_registry.codex_dir / "auth.json"
    alpha_auth = initialized_registry.auth_store / "alpha.json"
    before = {
        runtime_config: runtime_config.read_bytes(),
        runtime_auth: runtime_auth.read_bytes(),
        alpha_auth: alpha_auth.read_bytes(),
    }
    original_atomic_write = cp.atomic_write_bytes
    failed = False

    def flaky_atomic_write(
        path: Path,
        payload: bytes,
        *,
        secret: bool = False,
        mode: int | None = None,
    ) -> None:
        nonlocal failed
        if path == runtime_config and not failed:
            failed = True
            original_atomic_write(path, payload, secret=secret, mode=mode)
            raise cp.SwitchError("injected runtime config failure")
        original_atomic_write(path, payload, secret=secret, mode=mode)

    monkeypatch.setattr(cp, "atomic_write_bytes", flaky_atomic_write)
    with pytest.raises(cp.SwitchError, match="unable to commit state changes"):
        cp.switch_provider("beta", dry_run=False)

    for path, payload in before.items():
        assert path.read_bytes() == payload


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission semantics")
def test_private_permissions_and_doctor_fix(
    initialized_registry: IsolatedPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    runtime_auth = initialized_registry.codex_dir / "auth.json"
    alpha_auth = initialized_registry.auth_store / "alpha.json"
    initialized_registry.tool_home.chmod(0o755)
    initialized_registry.auth_store.chmod(0o755)
    runtime_auth.chmod(0o644)
    alpha_auth.chmod(0o644)

    assert cp.doctor(fix=False) == 1
    assert "insecure permissions" in capsys.readouterr().out
    assert cp.doctor(fix=True) == 0
    capsys.readouterr()

    assert initialized_registry.tool_home.stat().st_mode & 0o777 == 0o700
    assert initialized_registry.auth_store.stat().st_mode & 0o777 == 0o700
    assert runtime_auth.stat().st_mode & 0o777 == 0o600
    assert alpha_auth.stat().st_mode & 0o777 == 0o600


def test_atomic_write_cleans_temporary_file_on_replace_failure(
    isolated_paths: IsolatedPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = isolated_paths.home / "atomic" / "target.txt"
    target.parent.mkdir()
    before = set(target.parent.iterdir())

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError("injected replace failure")

    monkeypatch.setattr(cp.os, "replace", fail_replace)
    with pytest.raises(cp.SwitchError, match="unable to write"):
        cp.atomic_write_bytes(target, b"payload")
    assert set(target.parent.iterdir()) == before


def test_first_switch_does_not_create_empty_auth_profile(
    isolated_paths: IsolatedPaths,
) -> None:
    cp.add_provider(
        provider="alpha",
        base_url="https://alpha.example.com",
        api_key="placeholder-key",
        display_name=None,
        wire_api="responses",
        supports_websockets=None,
        dry_run=False,
    )
    isolated_paths.codex_dir.mkdir(parents=True, exist_ok=True)
    (isolated_paths.codex_dir / "auth.json").write_text(
        json.dumps({"OPENAI_API_KEY": "preexisting-placeholder"}),
        encoding="utf-8",
    )
    cp.switch_provider("alpha", dry_run=False)
    assert not (isolated_paths.auth_store / ".json").exists()


def test_add_dry_run_does_not_create_files(isolated_paths: IsolatedPaths) -> None:
    assert (
        cp.add_provider(
            provider="alpha",
            base_url="https://alpha.example.com",
            api_key="placeholder-key",
            display_name=None,
            wire_api="responses",
            supports_websockets=None,
            dry_run=True,
        )
        == 0
    )
    assert not isolated_paths.tool_home.exists()
    assert not isolated_paths.codex_dir.exists()


def test_rename_provider_updates_registry_and_auth_snapshot(
    initialized_registry: IsolatedPaths,
) -> None:
    assert cp.rename_provider("beta", "gamma", dry_run=False) == 0

    _, providers = cp.load_provider_registry()
    assert set(providers) == {"alpha", "gamma"}
    assert not (initialized_registry.auth_store / "beta.json").exists()
    gamma_auth = initialized_registry.auth_store / "gamma.json"
    assert gamma_auth.exists()
    assert cp.load_auth_json(gamma_auth)["OPENAI_API_KEY"] == "placeholder-beta-key"


def test_rename_current_provider_updates_runtime_config(
    initialized_registry: IsolatedPaths,
) -> None:
    assert cp.rename_provider("alpha", "omega", dry_run=False) == 0

    current, runtime_data, _ = cp.load_runtime_config()
    assert current == "omega"
    assert set(runtime_data["model_providers"]) == {"omega"}
    _, providers = cp.load_provider_registry()
    assert set(providers) == {"beta", "omega"}
    assert not (initialized_registry.auth_store / "alpha.json").exists()
    assert (initialized_registry.auth_store / "omega.json").exists()


def test_rename_dry_run_leaves_existing_state_unchanged(
    initialized_registry: IsolatedPaths,
) -> None:
    tracked_paths = [
        initialized_registry.tool_config,
        initialized_registry.auth_store / "alpha.json",
        initialized_registry.auth_store / "beta.json",
        initialized_registry.codex_dir / "config.toml",
        initialized_registry.codex_dir / "auth.json",
    ]
    before = {
        path: (path.read_bytes(), path.stat().st_mtime_ns) for path in tracked_paths
    }

    assert cp.rename_provider("beta", "gamma", dry_run=True) == 0

    for path, original in before.items():
        assert (path.read_bytes(), path.stat().st_mtime_ns) == original
    assert not (initialized_registry.auth_store / "gamma.json").exists()


def test_rename_rejects_existing_target_provider(
    initialized_registry: IsolatedPaths,
) -> None:
    with pytest.raises(cp.SwitchError, match="provider already exists: beta"):
        cp.rename_provider("alpha", "beta", dry_run=False)


def test_all_dry_run_commands_leave_existing_state_unchanged(
    initialized_registry: IsolatedPaths,
) -> None:
    tracked_paths = [
        initialized_registry.tool_config,
        initialized_registry.tool_home / ".lock",
        initialized_registry.auth_store / "alpha.json",
        initialized_registry.auth_store / "beta.json",
        initialized_registry.codex_dir / "config.toml",
        initialized_registry.codex_dir / "auth.json",
    ]
    before = {
        path: (path.read_bytes(), path.stat().st_mtime_ns) for path in tracked_paths
    }

    cp.add_provider(
        provider="gamma",
        base_url="https://gamma.example.com",
        api_key="placeholder-gamma",
        display_name=None,
        wire_api="responses",
        supports_websockets=None,
        dry_run=True,
    )
    cp.switch_provider("beta", dry_run=True)
    cp.delete_provider("beta", delete_auth=True, dry_run=True)

    after = {
        path: (path.read_bytes(), path.stat().st_mtime_ns) for path in tracked_paths
    }
    assert after == before
    assert not (initialized_registry.auth_store / "gamma.json").exists()


def test_add_rolls_back_registry_when_auth_write_fails(
    isolated_paths: IsolatedPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    cp.ensure_tool_config()
    original_config = isolated_paths.tool_config.read_bytes()
    original_atomic_write = cp.atomic_write_bytes

    def fail_auth_write(
        path: Path,
        payload: bytes,
        *,
        secret: bool = False,
        mode: int | None = None,
    ) -> None:
        if path.name == "alpha.json":
            raise cp.SwitchError("injected auth failure")
        original_atomic_write(path, payload, secret=secret, mode=mode)

    monkeypatch.setattr(cp, "atomic_write_bytes", fail_auth_write)
    with pytest.raises(cp.SwitchError, match="unable to commit state changes"):
        cp.add_provider(
            provider="alpha",
            base_url="https://alpha.example.com",
            api_key="placeholder-key",
            display_name=None,
            wire_api="responses",
            supports_websockets=None,
            dry_run=False,
        )
    assert isolated_paths.tool_config.read_bytes() == original_config
    assert not (isolated_paths.auth_store / "alpha.json").exists()


def test_invalid_runtime_config_is_not_silently_treated_as_empty(
    isolated_paths: IsolatedPaths,
) -> None:
    cp.ensure_tool_config()
    isolated_paths.codex_dir.mkdir(parents=True)
    (isolated_paths.codex_dir / "config.toml").write_text(
        "this is not valid TOML",
        encoding="utf-8",
    )
    with pytest.raises(cp.SwitchError, match="invalid TOML"):
        cp.ensure_registry_ready()


def test_actual_registry_updates_preserve_existing_comments(
    isolated_paths: IsolatedPaths,
) -> None:
    cp.add_provider(
        provider="alpha",
        base_url="https://alpha.example.com",
        api_key="placeholder-alpha",
        display_name="Alpha",
        wire_api="responses",
        supports_websockets=None,
        dry_run=False,
    )
    original = isolated_paths.tool_config.read_text(encoding="utf-8")
    isolated_paths.tool_config.write_text(
        original.replace(
            'base_url = "https://alpha.example.com/v1"',
            'base_url = "https://alpha.example.com/v1" # keep me',
        ),
        encoding="utf-8",
    )
    cp.add_provider(
        provider="beta",
        base_url="https://beta.example.com",
        api_key="placeholder-beta",
        display_name="Beta",
        wire_api="responses",
        supports_websockets=None,
        dry_run=False,
    )
    assert "# keep me" in isolated_paths.tool_config.read_text(encoding="utf-8")
    cp.delete_provider("beta", delete_auth=True, dry_run=False)
    assert "# keep me" in isolated_paths.tool_config.read_text(encoding="utf-8")


def test_first_provider_preserves_uninitialized_runtime_config(
    isolated_paths: IsolatedPaths,
) -> None:
    isolated_paths.codex_dir.mkdir(parents=True)
    runtime_config = isolated_paths.codex_dir / "config.toml"
    runtime_config.write_text(
        '# existing runtime settings\nmodel = "gpt-5"\n\n[features]\nenabled = true\n',
        encoding="utf-8",
    )
    cp.add_provider(
        provider="alpha",
        base_url="https://alpha.example.com",
        api_key="placeholder-key",
        display_name=None,
        wire_api="responses",
        supports_websockets=None,
        dry_run=False,
    )
    cp.switch_provider("alpha", dry_run=False)
    rendered = runtime_config.read_text(encoding="utf-8")
    data = tomllib.loads(rendered)
    assert data["model"] == "gpt-5"
    assert data["features"]["enabled"] is True
    assert data["model_provider"] == "alpha"
    assert "# existing runtime settings" in rendered


def test_temporary_provider_restores_state_after_failure(
    initialized_registry: IsolatedPaths,
) -> None:
    runtime_config = initialized_registry.codex_dir / "config.toml"
    runtime_auth = initialized_registry.codex_dir / "auth.json"
    original_config = runtime_config.read_bytes()
    original_auth = runtime_auth.read_bytes()

    with (
        pytest.raises(RuntimeError, match="injected ping failure"),
        cp.temporary_provider("beta"),
    ):
        assert cp.load_runtime_config()[0] == "beta"
        assert (
            runtime_auth.read_bytes()
            == (initialized_registry.auth_store / "beta.json").read_bytes()
        )
        raise RuntimeError("injected ping failure")

    assert runtime_config.read_bytes() == original_config
    assert runtime_auth.read_bytes() == original_auth
