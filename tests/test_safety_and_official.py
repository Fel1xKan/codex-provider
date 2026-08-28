from __future__ import annotations

import json
import os
import tomllib
from pathlib import Path

import pytest
from conftest import IsolatedPaths

import cli.codex_provider as cp
from lib.common import self_upgrade
from lib.common.common_store import FileLockManager, inspect_file_lock
from lib.common.errors import SwitchError
from lib.common.toml_config import parse_provider_section


def test_switch_creates_importable_snapshot(
    initialized_registry: IsolatedPaths,
) -> None:
    backups = initialized_registry.tool_home / "backups"

    assert cp.main(["switch", "beta"]) == 0
    snapshot_file = next(
        path
        for path in backups.glob("*.json")
        if json.loads(path.read_text(encoding="utf-8"))["codex_provider_backup"][
            "provider"
        ]
        == "beta"
    )
    payload = json.loads(snapshot_file.read_text(encoding="utf-8"))
    assert payload["type"] == "codex-provider"
    assert payload["active_provider"] == "alpha"
    assert set(payload["providers"]) == {"alpha", "beta"}
    metadata = payload["codex_provider_backup"]
    assert metadata["action"] == "switch"
    assert metadata["provider"] == "beta"
    if os.name == "posix":
        assert (backups.stat().st_mode & 0o777) == 0o700
        assert (snapshot_file.stat().st_mode & 0o777) == 0o600

    assert cp.main(["switch", "alpha"]) == 0
    assert cp.main(["delete", "beta", "--full"]) == 0
    data = tomllib.loads(initialized_registry.tool_config.read_text(encoding="utf-8"))
    assert "beta" not in data["model_providers"]
    assert not (initialized_registry.auth_store / "beta.json").exists()

    assert cp.main(["import", str(snapshot_file)]) == 0
    data = tomllib.loads(initialized_registry.tool_config.read_text(encoding="utf-8"))
    assert set(data["model_providers"]) == {"alpha", "beta"}
    assert data["active_provider"] == "alpha"
    assert (initialized_registry.auth_store / "beta.json").exists()


def test_add_supports_web_search_and_model_catalog(
    initialized_registry: IsolatedPaths,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = initialized_registry.tool_home / "catalogs" / "custom.json"
    catalog.parent.mkdir(parents=True, exist_ok=True)
    catalog.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(cp, "read_api_key", lambda from_stdin: "placeholder-key")

    assert (
        cp.main(
            [
                "add",
                "https://delta.example.com",
                "--provider",
                "delta",
                "--supports-standalone-web-search",
                "true",
                "--provider-model-catalog-json",
                str(catalog),
            ]
        )
        == 0
    )
    assert cp.switch_provider("delta", dry_run=False) == 0
    data = tomllib.loads(initialized_registry.tool_config.read_text(encoding="utf-8"))
    delta = data["model_providers"]["delta"]
    assert delta["supports_standalone_web_search"] is True
    assert delta["provider_model_catalog_json"] == str(catalog)
    runtime = tomllib.loads(
        (initialized_registry.codex_dir / "config.toml").read_text(encoding="utf-8")
    )
    assert runtime["web_search"] == "live"
    assert runtime["model_catalog_json"] == str(catalog)


def test_add_supports_fast_flag(
    initialized_registry: IsolatedPaths,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cp, "read_api_key", lambda from_stdin: "placeholder-key")

    assert (
        cp.main(
            [
                "add",
                "https://delta.example.com",
                "--provider",
                "delta",
                "--fast",
            ]
        )
        == 0
    )
    data = tomllib.loads(initialized_registry.tool_config.read_text(encoding="utf-8"))
    assert data["model_providers"]["delta"]["fast_mode"] is True

    assert cp.switch_provider("delta", dry_run=False) == 0
    runtime = tomllib.loads(
        (initialized_registry.codex_dir / "config.toml").read_text(encoding="utf-8")
    )
    assert runtime["service_tier"] == "priority"


def test_add_apply_switches_to_new_provider(
    initialized_registry: IsolatedPaths,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cp, "read_api_key", lambda from_stdin: "placeholder-key")

    assert (
        cp.main(
            [
                "add",
                "https://delta.example.com",
                "--provider",
                "delta",
                "--fast",
                "--apply",
            ]
        )
        == 0
    )
    data = tomllib.loads(initialized_registry.tool_config.read_text(encoding="utf-8"))
    assert data["active_provider"] == "delta"
    runtime = tomllib.loads(
        (initialized_registry.codex_dir / "config.toml").read_text(encoding="utf-8")
    )
    assert runtime["service_tier"] == "priority"
    output = capsys.readouterr().out
    assert "switched default provider: delta" in output


def test_add_omits_no_fast_flag(
    initialized_registry: IsolatedPaths,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cp, "read_api_key", lambda from_stdin: "placeholder-key")

    assert (
        cp.main(
            [
                "add",
                "https://delta.example.com",
                "--provider",
                "delta",
                "--fast",
                "--no-fast",
            ]
        )
        == 2
    )
    assert "unrecognized arguments" in capsys.readouterr().err


def test_config_set_updates_provider_options_without_editor(
    initialized_registry: IsolatedPaths,
    capsys: pytest.CaptureFixture[str],
) -> None:
    catalog = initialized_registry.tool_home / "catalogs" / "custom.json"
    catalog.parent.mkdir(parents=True, exist_ok=True)
    catalog.write_text("{}", encoding="utf-8")
    backups = initialized_registry.tool_home / "backups"
    backup_count = len(list(backups.glob("*.json")))

    assert (
        cp.main(
            [
                "config",
                "set",
                "beta",
                "--supports-standalone-web-search",
                "true",
                "--provider-model-catalog-json",
                str(catalog),
            ]
        )
        == 0
    )
    data = tomllib.loads(initialized_registry.tool_config.read_text(encoding="utf-8"))
    beta = data["model_providers"]["beta"]
    assert beta["supports_standalone_web_search"] is True
    assert beta["provider_model_catalog_json"] == str(catalog)
    assert len(list(backups.glob("*.json"))) == backup_count + 1
    output = capsys.readouterr().out
    assert "set provider options: beta" in output
    assert "provider_model_catalog_json" in output

    assert (
        cp.main(
            [
                "config",
                "set",
                "beta",
                "--provider-model-catalog-json",
                "",
            ]
        )
        == 0
    )
    data = tomllib.loads(initialized_registry.tool_config.read_text(encoding="utf-8"))
    beta = data["model_providers"]["beta"]
    assert "provider_model_catalog_json" not in beta
    assert beta["supports_standalone_web_search"] is True


def test_config_set_validates_input(
    initialized_registry: IsolatedPaths,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cp.main(["config", "set", "beta"]) == 1
    output = capsys.readouterr()
    assert "nothing to set" in output.out + output.err

    capsys.readouterr()
    assert (
        cp.main(
            ["config", "set", "unknown", "--supports-standalone-web-search", "true"]
        )
        == 1
    )
    output = capsys.readouterr()
    assert "unknown provider 'unknown'" in output.out + output.err


def test_config_set_updates_full_provider_fields(
    initialized_registry: IsolatedPaths,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (
        cp.main(
            [
                "config",
                "set",
                "beta",
                "--name",
                "Beta Renamed",
                "--wire-api",
                "chat",
                "--supports-websockets",
                "false",
            ]
        )
        == 0
    )
    data = tomllib.loads(initialized_registry.tool_config.read_text(encoding="utf-8"))
    beta = data["model_providers"]["beta"]
    assert beta["name"] == "Beta Renamed"
    assert beta["wire_api"] == "chat"
    assert beta["supports_websockets"] is False
    output = capsys.readouterr().out
    assert "name = Beta Renamed" in output
    assert "wire_api = chat" in output


def test_config_set_reset_clears_extended_options(
    initialized_registry: IsolatedPaths,
) -> None:
    assert (
        cp.main(
            [
                "config",
                "set",
                "beta",
                "--fast",
                "--supports-standalone-web-search",
                "true",
            ]
        )
        == 0
    )
    assert (
        cp.main(
            [
                "config",
                "set",
                "beta",
                "--reset",
            ]
        )
        == 0
    )
    data = tomllib.loads(initialized_registry.tool_config.read_text(encoding="utf-8"))
    beta = data["model_providers"]["beta"]
    assert "fast_mode" not in beta
    assert "supports_standalone_web_search" not in beta
    assert "provider_model_catalog_json" not in beta
    assert beta["base_url"] == "https://beta.example.com/v1"
    assert beta["name"] == "Beta"


def test_config_set_fast_renders_priority_tier_on_switch(
    initialized_registry: IsolatedPaths,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (
        cp.main(
            [
                "config",
                "set",
                "beta",
                "--fast",
            ]
        )
        == 0
    )
    data = tomllib.loads(initialized_registry.tool_config.read_text(encoding="utf-8"))
    assert data["model_providers"]["beta"]["fast_mode"] is True

    assert cp.switch_provider("beta", dry_run=False) == 0
    runtime = tomllib.loads(
        (initialized_registry.codex_dir / "config.toml").read_text(encoding="utf-8")
    )
    assert runtime["service_tier"] == "priority"
    assert runtime["model_providers"]["codex-provider"].get("service_tier") is None

    assert (
        cp.main(
            [
                "config",
                "set",
                "beta",
                "--no-fast",
                "--apply",
            ]
        )
        == 0
    )
    data = tomllib.loads(initialized_registry.tool_config.read_text(encoding="utf-8"))
    assert "fast_mode" not in data["model_providers"]["beta"]
    runtime = tomllib.loads(
        (initialized_registry.codex_dir / "config.toml").read_text(encoding="utf-8")
    )
    assert "service_tier" not in runtime
    output = capsys.readouterr().out
    assert "rendered runtime config.toml" in output


def test_config_set_fast_and_no_fast_conflict(
    initialized_registry: IsolatedPaths,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (
        cp.main(
            [
                "config",
                "set",
                "beta",
                "--fast",
                "--no-fast",
            ]
        )
        == 1
    )
    output = capsys.readouterr()
    assert "cannot be combined" in output.err


def test_config_set_apply_requires_active_provider(
    initialized_registry: IsolatedPaths,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (
        cp.main(
            [
                "config",
                "set",
                "beta",
                "--fast",
                "--apply",
            ]
        )
        == 1
    )
    output = capsys.readouterr()
    assert "--apply targets the active provider" in output.out + output.err


def test_config_set_apply_dry_run_renders_runtime(
    initialized_registry: IsolatedPaths,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (
        cp.main(
            [
                "config",
                "set",
                "alpha",
                "--fast",
                "--apply",
                "--dry-run",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "would render runtime config.toml" in output
    runtime = tomllib.loads(
        (initialized_registry.codex_dir / "config.toml").read_text(encoding="utf-8")
    )
    assert "service_tier" not in runtime


def test_snapshot_pruning_keeps_recent_snapshots(
    initialized_registry: IsolatedPaths,
) -> None:
    for index in range(14):
        target = "alpha" if index % 2 == 0 else "beta"
        assert cp.switch_provider(target, dry_run=False) == 0

    files = list((initialized_registry.tool_home / "backups").glob("*.json"))
    assert len(files) == 10


def test_lock_owner_is_visible_and_stale_locks_are_reported(
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / "state" / ".lock"
    manager = FileLockManager(lock_path)

    with manager:
        inspection = inspect_file_lock(lock_path)
        assert inspection.state == "held"
        assert inspection.pid == os.getpid()
        assert inspection.started_at_ms is not None

    assert inspect_file_lock(lock_path).state == "free"

    # On Windows the owner payload starts after a placeholder byte at offset
    # 0, which is what msvcrt.locking() locks; mirror that layout here.
    owner_payload = '{"pid": 12345, "started_at_ms": 1}'
    if os.name == "nt":
        owner_payload = "0" + owner_payload
    lock_path.write_text(owner_payload, encoding="utf-8")
    stale = inspect_file_lock(lock_path)
    assert stale.state == "stale"
    assert stale.pid == 12345


def write_official_login(paths: IsolatedPaths) -> None:
    paths.codex_dir.mkdir(parents=True, exist_ok=True)
    (paths.codex_dir / "auth.json").write_text(
        json.dumps({"tokens": {"id_token": "placeholder-official-token"}}),
        encoding="utf-8",
    )


def add_and_switch_official(paths: IsolatedPaths) -> None:
    write_official_login(paths)
    assert cp.main(["official", "add", "--name", "Official ChatGPT"]) == 0
    assert cp.switch_provider("official", dry_run=False) == 0


def test_official_switch_removes_managed_runtime_entries(
    initialized_registry: IsolatedPaths,
) -> None:
    catalog = initialized_registry.tool_home / "catalog.json"
    catalog.write_text("{}", encoding="utf-8")
    assert (
        cp.add_provider(
            provider="gamma",
            base_url="https://gamma.example.com",
            api_key="placeholder-gamma-key",
            display_name="Gamma",
            wire_api="responses",
            supports_websockets=None,
            dry_run=False,
            model_catalog_json=str(catalog),
            supports_standalone_web_search=True,
        )
        == 0
    )
    assert cp.switch_provider("gamma", dry_run=False) == 0
    runtime = tomllib.loads(
        (initialized_registry.codex_dir / "config.toml").read_text(encoding="utf-8")
    )
    assert runtime["model_catalog_json"] == str(catalog)
    assert runtime["web_search"] == "live"
    assert "codex-provider" in runtime["model_providers"]

    add_and_switch_official(initialized_registry)
    runtime = tomllib.loads(
        (initialized_registry.codex_dir / "config.toml").read_text(encoding="utf-8")
    )
    assert runtime["model_provider"] == "openai"
    assert "codex-provider" not in runtime.get("model_providers", {})
    assert "model_catalog_json" not in runtime
    assert "web_search" not in runtime
    runtime_auth = json.loads(
        (initialized_registry.codex_dir / "auth.json").read_text(encoding="utf-8")
    )
    assert runtime_auth["tokens"]["id_token"] == "placeholder-official-token"
    assert cp.doctor(False) == 0


def test_doctor_reports_official_isolation_mismatch(
    initialized_registry: IsolatedPaths,
    capsys: pytest.CaptureFixture[str],
) -> None:
    add_and_switch_official(initialized_registry)
    runtime_config = initialized_registry.codex_dir / "config.toml"
    runtime_config.write_text(
        runtime_config.read_text(encoding="utf-8")
        + '\n[model_providers.codex-provider]\nbase_url = "https://alpha.example.com"\n',
        encoding="utf-8",
    )

    assert cp.doctor(False) == 1
    output = capsys.readouterr().out
    assert "official provider isolation mismatch" in output


def test_add_official_requires_existing_codex_login(
    initialized_registry: IsolatedPaths,
) -> None:
    (initialized_registry.codex_dir / "auth.json").unlink()
    with pytest.raises(SwitchError, match="official auth file not found"):
        cp.add_official_provider("official", "Official", False)


def test_official_provider_config_validation() -> None:
    providers = parse_provider_section(
        {"model_providers": {"official": {"mode": "official", "name": "Official"}}}
    )
    assert "official" in providers

    with pytest.raises(SwitchError, match="base_url is missing"):
        parse_provider_section({"model_providers": {"broken": {"name": "Broken"}}})
    with pytest.raises(SwitchError, match="invalid mode"):
        parse_provider_section(
            {"model_providers": {"broken": {"mode": "hybrid", "base_url": "https://x"}}}
        )
    with pytest.raises(SwitchError, match="must not set base_url"):
        parse_provider_section(
            {
                "model_providers": {
                    "broken": {"mode": "official", "base_url": "https://x"}
                }
            }
        )


def test_official_provider_is_excluded_from_http_tests(
    initialized_registry: IsolatedPaths,
) -> None:
    add_and_switch_official(initialized_registry)
    from lib.codex.backend import BACKEND

    targets = BACKEND.test_targets()
    assert "official" not in {target.name for target in targets}


def test_add_supports_http_headers(
    initialized_registry: IsolatedPaths,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cp, "read_api_key", lambda from_stdin: "placeholder-key")

    assert (
        cp.main(
            [
                "add",
                "https://sub2api.example.com",
                "--provider",
                "sub2api",
                "--header",
                "x-openai-actor-authorization=local-image-extension",
                "--header",
                "X-Custom=foo",
            ]
        )
        == 0
    )
    data = tomllib.loads(initialized_registry.tool_config.read_text(encoding="utf-8"))
    headers = data["model_providers"]["sub2api"]["http_headers"]
    assert headers == {
        "x-openai-actor-authorization": "local-image-extension",
        "X-Custom": "foo",
    }

    assert cp.switch_provider("sub2api", dry_run=False) == 0
    runtime = tomllib.loads(
        (initialized_registry.codex_dir / "config.toml").read_text(encoding="utf-8")
    )
    runtime_headers = runtime["model_providers"]["codex-provider"]["http_headers"]
    assert runtime_headers["x-openai-actor-authorization"] == "local-image-extension"
    assert runtime_headers["X-Custom"] == "foo"


def test_config_set_adds_and_removes_headers(
    initialized_registry: IsolatedPaths,
) -> None:
    assert (
        cp.main(
            [
                "config",
                "set",
                "beta",
                "--header",
                "x-openai-actor-authorization=local-image-extension",
            ]
        )
        == 0
    )
    data = tomllib.loads(initialized_registry.tool_config.read_text(encoding="utf-8"))
    assert data["model_providers"]["beta"]["http_headers"] == {
        "x-openai-actor-authorization": "local-image-extension"
    }

    assert (
        cp.main(
            [
                "config",
                "set",
                "beta",
                "--header",
                "x-openai-actor-authorization=",
            ]
        )
        == 0
    )
    data = tomllib.loads(initialized_registry.tool_config.read_text(encoding="utf-8"))
    assert "http_headers" not in data["model_providers"]["beta"]


def test_config_set_reset_clears_headers(
    initialized_registry: IsolatedPaths,
) -> None:
    assert (
        cp.main(
            [
                "config",
                "set",
                "beta",
                "--header",
                "x-openai-actor-authorization=local-image-extension",
            ]
        )
        == 0
    )
    assert cp.main(["config", "set", "beta", "--reset"]) == 0
    data = tomllib.loads(initialized_registry.tool_config.read_text(encoding="utf-8"))
    assert "http_headers" not in data["model_providers"]["beta"]


def test_header_requires_key_value_pair(
    initialized_registry: IsolatedPaths,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cp.main(["config", "set", "beta", "--header", "no-equals"]) == 1
    output = capsys.readouterr()
    assert "expected KEY=VALUE" in output.err


def _release_payload(
    tag: str,
    program: str = "codex-provider",
    asset_name: str | None = None,
) -> dict[str, object]:
    version = tag.lstrip("v")
    platform_key = self_upgrade._platform_key()
    suffix = ".exe" if os.name == "nt" else ""
    name = asset_name or f"{program}-{version}-{platform_key}{suffix}"
    return {
        "tag_name": tag,
        "html_url": f"https://github.com/Fel1xKan/codex-provider/releases/tag/{tag}",
        "assets": [
            {
                "name": name,
                "browser_download_url": (
                    f"https://github.com/Fel1xKan/codex-provider/releases/download/"
                    f"{tag}/{name}"
                ),
            }
        ],
    }


def test_upgrade_check_reports_up_to_date(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        self_upgrade,
        "fetch_latest_release",
        lambda repo: _release_payload("v1.1.0"),
    )

    assert cp.main(["upgrade", "--check"]) == 0
    output = capsys.readouterr().out
    assert "current: 1.4.0" in output
    assert "latest:  1.1.0" in output
    assert "up to date" in output


def test_upgrade_dry_run_reports_newer_version(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        self_upgrade,
        "fetch_latest_release",
        lambda repo: _release_payload("v1.5.0"),
    )

    assert cp.main(["upgrade", "--dry-run"]) == 0
    output = capsys.readouterr().out
    assert "current: 1.4.0" in output
    assert "latest:  1.5.0" in output
    assert "would upgrade" in output


def test_upgrade_downloads_verifies_and_replaces(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = tmp_path / "codex-provider"
    target.write_bytes(b"old-binary")
    plan = self_upgrade.UpgradePlan(
        current_version="1.1.0",
        latest_version="1.2.0",
        release_url="https://github.com/Fel1xKan/codex-provider/releases/tag/v1.2.0",
        asset_name="codex-provider-1.2.0-linux-x86_64",
        asset_url="https://example.com/codex-provider",
        sha256_url="https://example.com/codex-provider.sha256",
        update_available=True,
    )
    digest = self_upgrade._sha256_hex(target)

    monkeypatch.setattr(
        self_upgrade,
        "_download",
        lambda url, dest: dest.write_bytes(b"new-binary"),
    )
    monkeypatch.setattr(
        self_upgrade,
        "_sha256_expected_from_release",
        lambda url: f"{self_upgrade._sha256_hex(Path(tmp_path) / 'placeholder')}  name",
    )
    monkeypatch.setattr(
        self_upgrade,
        "_sha256_hex",
        lambda path: digest if path.name == "codex-provider" else digest,
    )

    assert self_upgrade.perform_upgrade(plan, target) == 0
    assert target.read_bytes() == b"new-binary"
    output = capsys.readouterr().out
    assert "upgraded codex-provider: 1.1.0 -> 1.2.0" in output


def test_upgrade_checksum_mismatch_aborts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "codex-provider"
    target.write_bytes(b"old-binary")
    plan = self_upgrade.UpgradePlan(
        current_version="1.1.0",
        latest_version="1.2.0",
        release_url="",
        asset_name="codex-provider-1.2.0-linux-x86_64",
        asset_url="https://example.com/codex-provider",
        sha256_url="https://example.com/codex-provider.sha256",
        update_available=True,
    )
    monkeypatch.setattr(
        self_upgrade,
        "_download",
        lambda url, dest: dest.write_bytes(b"new-binary"),
    )
    monkeypatch.setattr(
        self_upgrade,
        "_sha256_expected_from_release",
        lambda url: "0" * 64,
    )

    with pytest.raises(SwitchError, match="checksum mismatch"):
        self_upgrade.perform_upgrade(plan, target)
    assert target.read_bytes() == b"old-binary"


def test_build_upgrade_plan_selects_platform_asset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(self_upgrade, "_platform_key", lambda: "linux-x86_64")
    plan = self_upgrade.build_upgrade_plan(
        "Fel1xKan/codex-provider",
        "cpx",
        "1.1.0",
        _release_payload("v1.5.0", program="cpx"),
    )
    assert plan.update_available
    expected_suffix = ".exe" if os.name == "nt" else ""
    expected_name = f"cpx-1.5.0-{self_upgrade._platform_key()}{expected_suffix}"
    assert plan.asset_name == expected_name
    assert plan.sha256_url.endswith(".sha256")


def test_build_upgrade_plan_falls_back_to_legacy_asset_when_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(self_upgrade, "_platform_key", lambda: "linux-x86_64")
    plan = self_upgrade.build_upgrade_plan(
        "Fel1xKan/codex-provider",
        "cpx",
        "1.2.0",
        _release_payload("v1.3.0"),
        legacy_name="codex-provider",
    )
    assert plan.update_available
    expected_suffix = ".exe" if os.name == "nt" else ""
    assert plan.asset_name == (f"codex-provider-1.3.0-linux-x86_64{expected_suffix}")
