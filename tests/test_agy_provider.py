from __future__ import annotations

import json
from pathlib import Path

import pytest

import cli.agy_provider as agy


@pytest.fixture
def agy_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    tool_home = tmp_path / ".agy-provider"
    gemini_dir = tmp_path / ".gemini"
    cli_dir = gemini_dir / "antigravity-cli"
    config_dir = gemini_dir / "config"

    monkeypatch.setattr(agy, "HOME", tmp_path)
    monkeypatch.setattr(agy, "GEMINI_DIR", gemini_dir)
    monkeypatch.setattr(agy, "CLI_DIR", cli_dir)
    monkeypatch.setattr(agy, "CONFIG_DIR", config_dir)

    monkeypatch.setattr(agy, "OAUTH_TOKEN_PATH", cli_dir / "antigravity-oauth-token")
    monkeypatch.setattr(agy, "CONFIG_PATH", config_dir / "config.json")
    monkeypatch.setattr(agy, "SETTINGS_PATH", cli_dir / "settings.json")

    monkeypatch.setattr(agy, "TOOL_HOME", tool_home)
    monkeypatch.setattr(agy, "DATA_DIR", tool_home)
    monkeypatch.setattr(agy, "STATE_DIR", tool_home / "state")
    monkeypatch.setattr(agy, "AUTH_PATH", tool_home / "auth.json")
    monkeypatch.setattr(agy, "STATE_PATH", tool_home / "state" / "state.json")
    monkeypatch.setattr(agy, "RECENT_PATH", tool_home / "state" / "recent.json")
    monkeypatch.setattr(agy, "LOCK_PATH", tool_home / "state" / "agy-provider.lock")
    monkeypatch.setattr(agy, "_lock_depth", 0)
    monkeypatch.setattr(agy, "_lock_file", None)

    return tmp_path


def test_agy_add_from_dir_and_list(
    agy_paths: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source_dir = agy_paths / "temp_acc"
    token_dir = source_dir / ".gemini" / "antigravity-cli"
    token_dir.mkdir(parents=True)
    token_file = token_dir / "antigravity-oauth-token"
    # id_token with email a@example.com
    id_tok = "header.eyJlbWFpbCI6ICJhQGV4YW1wbGUuY29tIiwgIm5hbWUiOiAiQSJ9.sig"
    token_file.write_text(
        json.dumps(
            {
                "token": "token_a",
                "id_token": id_tok,
                "auth_method": "consumer",
            }
        ),
        encoding="utf-8",
    )

    assert agy.main(["add", "account_a", "--from-dir", str(source_dir)]) == 0

    capsys.readouterr()
    assert agy.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "* account_a (a@example.com)" in out


def test_agy_switch_and_status(
    agy_paths: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    token_a = {
        "token": "tok_a",
        "id_token": "h.eyJlbWFpbCI6ICJhQGV4YW1wbGUuY29tIn0=.s",
        "auth_method": "consumer",
    }
    agy.OAUTH_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    agy.OAUTH_TOKEN_PATH.write_text(json.dumps(token_a), encoding="utf-8")
    assert agy.main(["add", "acc_a", "--from-current"]) == 0

    token_b = {
        "token": "tok_b",
        "id_token": "h.eyJlbWFpbCI6ICJiQGV4YW1wbGUuY29tIn0=.s",
        "auth_method": "google",
    }
    agy.OAUTH_TOKEN_PATH.write_text(json.dumps(token_b), encoding="utf-8")
    assert agy.main(["add", "acc_b", "--from-current"]) == 0

    assert agy.main(["switch", "acc_a"]) == 0
    active = json.loads(agy.OAUTH_TOKEN_PATH.read_text(encoding="utf-8"))
    assert active["token"] == "tok_a"

    capsys.readouterr()
    assert agy.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "Current account: acc_a" in out
    assert "Active identity: a@example.com" in out


def test_agy_rename_and_delete(
    agy_paths: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    token_a = {
        "token": "tok_a",
        "id_token": "h.eyJlbWFpbCI6ICJhQGV4YW1wbGUuY29tIn0=.s",
    }
    agy.OAUTH_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    agy.OAUTH_TOKEN_PATH.write_text(json.dumps(token_a), encoding="utf-8")
    assert agy.main(["add", "old_name", "--from-current"]) == 0

    assert agy.main(["rename", "old_name", "new_name"]) == 0
    capsys.readouterr()
    assert agy.main(["list"]) == 0
    assert "new_name" in capsys.readouterr().out

    assert agy.main(["delete", "new_name"]) == 0
    capsys.readouterr()
    assert agy.main(["list"]) == 0
    assert "new_name" not in capsys.readouterr().out


def test_agy_auth_detail(agy_paths: Path, capsys: pytest.CaptureFixture[str]) -> None:
    id_tok = "h.eyJlbWFpbCI6ICJ1c2VyQGV4YW1wbGUuY29tIiwgIm5hbWUiOiAiVGVzdCBVc2VyIn0=.s"
    token_data = {
        "token": "tok_secret",
        "id_token": id_tok,
        "auth_method": "consumer",
    }
    agy.OAUTH_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    agy.OAUTH_TOKEN_PATH.write_text(json.dumps(token_data), encoding="utf-8")
    assert agy.main(["add", "my_acc", "--from-current"]) == 0

    capsys.readouterr()
    assert agy.main(["auth", "detail", "my_acc"]) == 0
    out = capsys.readouterr().out
    assert "Account: my_acc" in out
    assert "Email: user@example.com" in out
    assert "Name: Test User" in out
    assert "tok_secret" not in out


def test_agy_doctor(agy_paths: Path, capsys: pytest.CaptureFixture[str]) -> None:
    id_tok = "h.eyJlbWFpbCI6ICJ1c2VyQGV4YW1wbGUuY29tIiwgImV4cCI6IDIwMDAwMDAwMDB9.s"
    token_data = {
        "token": "tok_secret",
        "id_token": id_tok,
    }
    agy.OAUTH_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    agy.OAUTH_TOKEN_PATH.write_text(json.dumps(token_data), encoding="utf-8")

    capsys.readouterr()
    assert agy.main(["doctor"]) in (0, 1)
    out = capsys.readouterr().out
    assert "[OK] Token file exists" in out
    assert "user@example.com" in out


def test_agy_login_flow(
    agy_paths: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_run(cmd, env, check=False):
        home = Path(env["HOME"])
        t_dir = home / ".gemini" / "antigravity-cli"
        t_dir.mkdir(parents=True, exist_ok=True)
        id_tok = "h.eyJlbWFpbCI6ICJsb2dpbl91c2VyQGV4YW1wbGUuY29tIn0=.s"
        (t_dir / "antigravity-oauth-token").write_text(
            json.dumps({"token": "new_tok", "id_token": id_tok}), encoding="utf-8"
        )

        class Proc:
            returncode = 0

        return Proc()

    import shutil
    import subprocess

    monkeypatch.setattr(shutil, "which", lambda cmd: "/usr/bin/agy")
    monkeypatch.setattr(agy, "shutil", shutil)
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(agy, "subprocess", subprocess)

    assert agy.main(["login", "new_account"]) == 0
    active = json.loads(agy.OAUTH_TOKEN_PATH.read_text(encoding="utf-8"))
    assert active["token"] == "new_tok"

    capsys.readouterr()
    assert agy.main(["status"]) == 0
    assert "Active identity: login_user@example.com" in capsys.readouterr().out


def test_agy_export_and_import(
    agy_paths: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    token_a = {
        "token": "tok_a",
        "id_token": "h.eyJlbWFpbCI6ICJhQGV4YW1wbGUuY29tIn0=.s",
        "auth_method": "consumer",
    }
    agy.OAUTH_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    agy.OAUTH_TOKEN_PATH.write_text(json.dumps(token_a), encoding="utf-8")
    assert agy.main(["add", "acc_a", "--from-current"]) == 0

    token_b = {
        "token": "tok_b",
        "id_token": "h.eyJlbWFpbCI6ICJiQGV4YW1wbGUuY29tIn0=.s",
        "auth_method": "google",
    }
    agy.OAUTH_TOKEN_PATH.write_text(json.dumps(token_b), encoding="utf-8")
    assert agy.main(["add", "acc_b", "--from-current"]) == 0
    assert agy.main(["switch", "acc_b"]) == 0

    export_file = agy_paths / "export.json"
    assert agy.main(["export", str(export_file)]) == 0

    assert export_file.exists()
    exported = json.loads(export_file.read_text(encoding="utf-8"))
    assert exported["type"] == "agy-provider"
    assert exported["current"] == "acc_b"
    assert "acc_a" in exported["accounts"]
    assert "acc_b" in exported["accounts"]

    capsys.readouterr()
    assert agy.main(["export"]) == 0
    stdout_out = capsys.readouterr().out
    exported_stdout = json.loads(stdout_out)
    assert exported_stdout["type"] == "agy-provider"
    assert exported_stdout["current"] == "acc_b"

    assert agy.main(["delete", "acc_a"]) == 0
    assert agy.main(["delete", "acc_b"]) == 0

    capsys.readouterr()
    assert agy.main(["list"]) == 0
    assert "acc_a" not in capsys.readouterr().out

    capsys.readouterr()
    assert agy.main(["import", str(export_file), "--dry-run"]) == 0
    dry_run_out = capsys.readouterr().out
    assert "would add/update account: acc_a" in dry_run_out
    assert "would add/update account: acc_b" in dry_run_out
    assert "would switch account: acc_b" in dry_run_out

    capsys.readouterr()
    assert agy.main(["list"]) == 0
    assert "acc_a" not in capsys.readouterr().out

    assert agy.main(["import", str(export_file)]) == 0

    capsys.readouterr()
    assert agy.main(["status"]) == 0
    status_out = capsys.readouterr().out
    assert "* acc_b" in status_out
    assert "acc_a" in status_out
    assert "Current account: acc_b" in status_out

