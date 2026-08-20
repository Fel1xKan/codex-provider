from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import pytest

import cli.agy_provider as agy
from lib.agy import usage as agy_usage


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = json.dumps(payload).encode("utf-8")
        self.status = 200

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def read(self, limit: int = -1) -> bytes:
        if limit < 0:
            return self.payload
        return self.payload[:limit]


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


def test_agy_usage_refreshes_selected_account_without_switching(
    agy_paths: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    audience = (
        "1071006060591-tmhssin2h21lcre235vtolojh4g403ep.apps.googleusercontent.com"
    )
    id_token = (
        "h.eyJhdWQiOiIxMDcxMDA2MDYwNTkxLXRtaHNzaW4yaDIxbGNyZTIzNXZ0b2xv"
        "amg0ZzQwM2VwLmFwcHMuZ29vZ2xldXNlcmNvbnRlbnQuY29tIiwiZW1haWwiOiJ1"
        "c2VyQGV4YW1wbGUuY29tIn0.s"
    )
    assert agy_usage.parse_jwt_claims(id_token)["aud"] == audience

    token_data = {
        "auth_method": "consumer",
        "id_token": id_token,
        "token": {
            "access_token": "expired-access",
            "refresh_token": "saved-refresh",
            "token_type": "Bearer",
            "expiry": "2000-01-01T00:00:00Z",
        },
    }
    agy.OAUTH_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    agy.OAUTH_TOKEN_PATH.write_text(json.dumps(token_data), encoding="utf-8")
    assert agy.main(["add", "work", "--from-current"]) == 0

    other_token = dict(token_data)
    other_token["id_token"] = "h.eyJlbWFpbCI6Im90aGVyQGV4YW1wbGUuY29tIn0.s"
    agy.OAUTH_TOKEN_PATH.write_text(json.dumps(other_token), encoding="utf-8")
    assert agy.main(["add", "other", "--from-current"]) == 0
    assert agy.main(["switch", "other"]) == 0

    state_before = agy.STATE_PATH.read_bytes()
    active_token_before = agy.OAUTH_TOKEN_PATH.read_bytes()
    request_urls: list[str] = []

    quota_response = {
        "groups": [
            {
                "displayName": "Gemini Models",
                "buckets": [
                    {
                        "bucketId": "gemini-weekly",
                        "window": "weekly",
                        "remainingFraction": 0.8556166,
                        "resetTime": "2026-08-06T01:26:50Z",
                    },
                    {
                        "bucketId": "gemini-5h",
                        "window": "5h",
                        "remainingFraction": 1,
                        "resetTime": "2026-07-30T18:30:53Z",
                    },
                ],
            },
            {
                "displayName": "Claude and GPT models",
                "buckets": [
                    {
                        "bucketId": "3p-weekly",
                        "window": "weekly",
                        "remainingFraction": 0.5,
                    },
                    {
                        "bucketId": "3p-5h",
                        "window": "5h",
                        "remainingFraction": 0.75,
                    },
                ],
            },
        ]
    }

    def fake_urlopen(request: Any, timeout: float) -> FakeResponse:
        assert timeout == agy_usage.REQUEST_TIMEOUT
        request_urls.append(request.full_url)
        if request.full_url == agy_usage.TOKEN_URL:
            form = parse_qs(request.data.decode("ascii"))
            assert form["client_id"] == [audience]
            assert form["refresh_token"] == ["saved-refresh"]
            return FakeResponse({"access_token": "fresh-access", "expires_in": 3599})
        if request.full_url == agy_usage.LOAD_CODE_ASSIST_URL:
            assert request.headers["Authorization"] == "Bearer fresh-access"
            assert request.headers["User-agent"] == ("antigravity/1.1.8 linux/amd64")
            assert json.loads(request.data) == {
                "metadata": {
                    "ideType": "IDE_UNSPECIFIED",
                    "platform": "PLATFORM_UNSPECIFIED",
                    "pluginType": "GEMINI",
                }
            }
            return FakeResponse(
                {
                    "cloudaicompanionProject": "account-project",
                    "currentTier": {"id": "free-tier"},
                }
            )
        assert request.full_url == agy_usage.QUOTA_URL
        assert request.headers["Authorization"] == "Bearer fresh-access"
        assert request.headers["User-agent"] == "antigravity/1.1.8 linux/amd64"
        assert json.loads(request.data) == {"project": "account-project"}
        return FakeResponse(quota_response)

    monkeypatch.setattr(agy_usage.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(
        agy_usage,
        "_antigravity_user_agent",
        lambda: "antigravity/1.1.8 linux/amd64",
    )

    capsys.readouterr()
    assert agy.main(["usage", "work"]) == 0
    output = capsys.readouterr().out
    assert request_urls == [
        agy_usage.TOKEN_URL,
        agy_usage.LOAD_CODE_ASSIST_URL,
        agy_usage.QUOTA_URL,
    ]
    assert "Account: work" in output
    assert "Identity: user@example.com" in output
    assert "Gemini Models" in output
    assert "5h limit: 100.00% remaining" in output
    assert "weekly limit: 85.56% remaining" in output
    assert output.index("5h limit") < output.index("weekly limit")
    assert "Claude and GPT models" in output
    assert "5h limit: 75.00% remaining" in output
    assert "weekly limit: 50.00% remaining" in output
    assert "saved-refresh" not in output
    assert "fresh-access" not in output
    assert agy.STATE_PATH.read_bytes() == state_before
    assert agy.OAUTH_TOKEN_PATH.read_bytes() == active_token_before


def test_agy_usage_defaults_to_current_account_without_refresh(
    agy_paths: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    token_data = {
        "token": {
            "access_token": "current-access",
            "refresh_token": "current-refresh",
            "expiry": "2999-01-01T00:00:00Z",
        }
    }
    agy.OAUTH_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    agy.OAUTH_TOKEN_PATH.write_text(json.dumps(token_data), encoding="utf-8")
    assert agy.main(["add", "current", "--from-current"]) == 0

    def fake_urlopen(request: Any, timeout: float) -> FakeResponse:
        if request.full_url == agy_usage.LOAD_CODE_ASSIST_URL:
            assert request.headers["Authorization"] == "Bearer current-access"
            return FakeResponse({"cloudaicompanionProject": "current-account-project"})
        assert request.full_url == agy_usage.QUOTA_URL
        assert request.headers["Authorization"] == "Bearer current-access"
        assert json.loads(request.data) == {"project": "current-account-project"}
        return FakeResponse(
            {
                "groups": [
                    {
                        "displayName": "Gemini Models",
                        "buckets": [
                            {"window": "5h", "remainingFraction": 0.25},
                            {"window": "weekly", "remainingFraction": 0.1},
                        ],
                    }
                ]
            }
        )

    monkeypatch.setattr(agy_usage.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(
        agy_usage,
        "_antigravity_user_agent",
        lambda: "antigravity/1.1.8 linux/amd64",
    )

    capsys.readouterr()
    assert agy.main(["usage"]) == 0
    output = capsys.readouterr().out
    assert "Account: current" in output
    assert "5h limit: 25.00% remaining" in output
    assert "weekly limit: 10.00% remaining" in output


def test_agy_usage_user_agent_tracks_installed_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agy_usage.shutil, "which", lambda command: "/opt/bin/agy")
    monkeypatch.setattr(
        agy_usage.subprocess,
        "run",
        lambda *args, **kwargs: agy_usage.subprocess.CompletedProcess(
            args[0], 0, stdout="1.4.2\n", stderr=""
        ),
    )
    monkeypatch.setattr(agy_usage.platform, "system", lambda: "Linux")
    monkeypatch.setattr(agy_usage.platform, "machine", lambda: "x86_64")

    assert agy_usage._antigravity_user_agent() == ("antigravity/1.4.2 linux/amd64")


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


def test_agy_auth_show(agy_paths: Path, capsys: pytest.CaptureFixture[str]) -> None:
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
    assert agy.main(["auth", "show", "my_acc"]) == 0
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
