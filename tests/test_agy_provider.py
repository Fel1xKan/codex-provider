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
