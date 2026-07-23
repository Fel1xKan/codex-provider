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
        f"codex_dir = {cp.format_toml_value(str(isolated_paths.codex_dir))}\n\n"
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


def test_existing_registry_migrates_to_stable_runtime_provider(
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
    cp.add_provider(
        provider="beta",
        base_url="https://beta.example.com",
        api_key="placeholder-beta",
        display_name="Beta",
        wire_api="responses",
        supports_websockets=None,
        dry_run=False,
    )
    isolated_paths.codex_dir.mkdir(parents=True)
    runtime_config = isolated_paths.codex_dir / "config.toml"
    runtime_config.write_text(
        'model_provider = "alpha"\n\n'
        "[model_providers.alpha]\n"
        'base_url = "https://alpha.example.com/v1"\n'
        'name = "Alpha"\n'
        "requires_openai_auth = true\n"
        'wire_api = "responses"\n',
        encoding="utf-8",
    )
    tool_text = isolated_paths.tool_config.read_text(encoding="utf-8")
    codex_dir_line = (
        f"codex_dir = {cp.format_toml_value(str(isolated_paths.codex_dir))}"
    )
    isolated_paths.tool_config.write_text(
        tool_text.replace(
            codex_dir_line,
            f'{codex_dir_line}\nlegacy_provider_ids = ["alpha", "beta"]',
        ),
        encoding="utf-8",
    )

    state = cp.ensure_provider_state()

    assert state.active_provider == "alpha"
    tool_data = tomllib.loads(isolated_paths.tool_config.read_text(encoding="utf-8"))
    assert tool_data["active_provider"] == "alpha"
    assert "legacy_provider_ids" not in tool_data
    runtime_data = tomllib.loads(runtime_config.read_text(encoding="utf-8"))
    assert runtime_data["model_provider"] == cp.RUNTIME_PROVIDER_ID
    assert set(runtime_data["model_providers"]) == {cp.RUNTIME_PROVIDER_ID}
    assert (
        runtime_data["model_providers"][cp.RUNTIME_PROVIDER_ID]
        == state.providers["alpha"]
    )


def test_switch_keeps_only_stable_runtime_provider_on_active_config(
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
    cp.add_provider(
        provider="beta",
        base_url="https://beta.example.com",
        api_key="placeholder-beta",
        display_name="Beta",
        wire_api="responses",
        supports_websockets=None,
        dry_run=False,
    )
    isolated_paths.codex_dir.mkdir(parents=True)
    (isolated_paths.codex_dir / "config.toml").write_text(
        'model_provider = "alpha"\n\n'
        "[model_providers.alpha]\n"
        'base_url = "https://alpha.example.com/v1"\n'
        'name = "Alpha"\n'
        "requires_openai_auth = true\n"
        'wire_api = "responses"\n',
        encoding="utf-8",
    )
    cp.ensure_provider_state()
    runtime_config = isolated_paths.codex_dir / "config.toml"
    runtime_text = runtime_config.read_text(encoding="utf-8")
    runtime_config.write_text(
        runtime_text + "\n[model_providers.alpha]\n"
        'base_url = "https://alpha.example.com/v1"\n'
        'name = "Alpha"\n'
        "requires_openai_auth = true\n"
        'wire_api = "responses"\n' + "\n[model_providers.beta]\n"
        'base_url = "https://alpha.example.com/v1"\n'
        'name = "Alpha"\n'
        "requires_openai_auth = true\n"
        'wire_api = "responses"\n',
        encoding="utf-8",
    )

    assert cp.switch_provider("beta", dry_run=False) == 0

    state = cp.load_provider_state()
    assert state.active_provider == "beta"
    runtime_provider, runtime_data, _ = cp.load_runtime_config()
    assert runtime_provider == cp.RUNTIME_PROVIDER_ID
    assert set(runtime_data["model_providers"]) == {cp.RUNTIME_PROVIDER_ID}
    assert (
        runtime_data["model_providers"][cp.RUNTIME_PROVIDER_ID]
        == state.providers["beta"]
    )


def test_fresh_switches_keep_single_stable_runtime_provider(
    initialized_registry: IsolatedPaths,
) -> None:
    assert cp.load_provider_state().active_provider == "alpha"

    assert cp.switch_provider("beta", dry_run=False) == 0
    first_runtime, first_data, _ = cp.load_runtime_config()
    assert first_runtime == cp.RUNTIME_PROVIDER_ID
    assert set(first_data["model_providers"]) == {cp.RUNTIME_PROVIDER_ID}
    assert cp.load_provider_state().active_provider == "beta"

    assert cp.switch_provider("alpha", dry_run=False) == 0
    second_runtime, second_data, _ = cp.load_runtime_config()
    assert second_runtime == cp.RUNTIME_PROVIDER_ID
    assert set(second_data["model_providers"]) == {cp.RUNTIME_PROVIDER_ID}
    assert cp.load_provider_state().active_provider == "alpha"


def test_switch_current_provider_repairs_config_without_replacing_runtime_auth(
    initialized_registry: IsolatedPaths,
) -> None:
    runtime_auth = initialized_registry.codex_dir / "auth.json"
    runtime_auth.write_text(
        json.dumps({"OPENAI_API_KEY": "refreshed-runtime-key"}),
        encoding="utf-8",
    )
    tool_text = initialized_registry.tool_config.read_text(encoding="utf-8")
    initialized_registry.tool_config.write_text(
        tool_text.replace(
            'base_url = "https://alpha.example.com/v1"',
            'base_url = "https://alpha-new.example.com/v1"',
        ),
        encoding="utf-8",
    )

    assert cp.switch_provider("alpha", dry_run=False) == 0

    _, runtime_data, _ = cp.load_runtime_config()
    assert runtime_data["model_providers"][cp.RUNTIME_PROVIDER_ID]["base_url"] == (
        "https://alpha-new.example.com/v1"
    )
    assert cp.load_auth_json(runtime_auth)["OPENAI_API_KEY"] == (
        "refreshed-runtime-key"
    )
    assert (
        cp.load_auth_json(initialized_registry.auth_store / "alpha.json")[
            "OPENAI_API_KEY"
        ]
        == "placeholder-alpha-key"
    )


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
        {
            "base_url": "https://beta.example.com/v1",
            "name": "line one\nline two",
            "extra_headers": {"x-team": "infra"},
        },
    )
    data = tomllib.loads(rendered)
    assert data["model_provider"] == cp.RUNTIME_PROVIDER_ID
    assert set(data["model_providers"]) == {cp.RUNTIME_PROVIDER_ID}
    assert data["model_providers"][cp.RUNTIME_PROVIDER_ID]["name"] == (
        "line one\nline two"
    )
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
        initialized_registry.tool_config: initialized_registry.tool_config.read_bytes(),
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
        if path == initialized_registry.tool_config and not failed:
            failed = True
            original_atomic_write(path, payload, secret=secret, mode=mode)
            raise cp.SwitchError("injected tool config failure")
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
    assert current == cp.RUNTIME_PROVIDER_ID
    assert set(runtime_data["model_providers"]) == {cp.RUNTIME_PROVIDER_ID}
    state = cp.load_provider_state()
    assert state.active_provider == "omega"
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


def test_delete_full_removes_orphaned_auth_profile(
    initialized_registry: IsolatedPaths,
) -> None:
    cp.delete_provider("beta", delete_auth=False, dry_run=False)
    profile = initialized_registry.auth_store / "beta.json"
    assert profile.exists()

    assert cp.delete_provider("beta", delete_auth=True, dry_run=False) == 0
    assert not profile.exists()


def test_add_replaces_orphaned_auth_profile(
    isolated_paths: IsolatedPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    cp.ensure_tool_config()
    profile = cp.auth_profile_path("sub")
    profile.write_text('{"OPENAI_API_KEY": "old-key"}\n', encoding="utf-8")

    assert (
        cp.add_provider(
            provider="sub",
            base_url="https://sub.yxxb.eu.cc/",
            api_key="new-key",
            display_name=None,
            wire_api="responses",
            supports_websockets=None,
            dry_run=False,
        )
        == 0
    )

    assert json.loads(profile.read_text())["OPENAI_API_KEY"] == "new-key"
    assert "replaced auth profile:" in capsys.readouterr().out


def test_auth_edit_can_update_orphaned_auth_profile(
    isolated_paths: IsolatedPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    cp.ensure_tool_config()
    profile = cp.auth_profile_path("sub")
    profile.write_text('{"OPENAI_API_KEY": "old-key"}\n', encoding="utf-8")

    def update_key(path: Path) -> None:
        path.write_text('{"OPENAI_API_KEY": "new-key"}\n', encoding="utf-8")

    monkeypatch.setattr(cp, "run_editor", update_key)

    assert cp.main(["auth", "edit", "sub"]) == 0
    assert json.loads(profile.read_text())["OPENAI_API_KEY"] == "new-key"


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
    assert data["model_provider"] == cp.RUNTIME_PROVIDER_ID
    assert set(data["model_providers"]) == {cp.RUNTIME_PROVIDER_ID}
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
        runtime_provider, runtime_data, _ = cp.load_runtime_config()
        assert runtime_provider == cp.RUNTIME_PROVIDER_ID
        assert (
            runtime_data["model_providers"][cp.RUNTIME_PROVIDER_ID]["base_url"]
            == "https://beta.example.com/v1"
        )
        assert (
            runtime_auth.read_bytes()
            == (initialized_registry.auth_store / "beta.json").read_bytes()
        )
        raise RuntimeError("injected ping failure")

    assert runtime_config.read_bytes() == original_config
    assert runtime_auth.read_bytes() == original_auth
