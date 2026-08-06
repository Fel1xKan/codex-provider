from __future__ import annotations

import base64
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

import cli.cursor_provider as cp
from lib.cursor import db as cdb

APPLICATION_USER_KEY = (
    "src.vs.platform.reactivestorage.browser.reactiveStorageServiceImpl."
    "persistentStorage.applicationUser"
)


def jwt_with(payload: dict[str, object]) -> str:
    raw = (
        base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8"))
        .decode("ascii")
        .rstrip("=")
    )
    return f"header.{raw}.sig"


def seed_auth_data(
    db_path: Path,
    email: str,
    *,
    display_name: str = "Test User",
    sign_up_type: str = "Google",
    sub: str = "google-oauth2|user_abc",
) -> dict[str, str]:
    auth_data = {
        "accessToken": jwt_with(
            {"sub": sub, "exp": 2000000000, "iss": "https://authentication.cursor.sh"}
        ),
        "refreshToken": jwt_with(
            {"sub": sub, "exp": 2000000000, "iss": "https://authentication.cursor.sh"}
        ),
        "cachedEmail": email,
        "cachedSignUpType": sign_up_type,
        "cachedScopedProfile": json.dumps({"displayName": display_name}),
        "stripeMembershipType": "free",
        "lastSignedInAuthId": sub,
    }
    con = sqlite3.connect(str(db_path))
    try:
        with con:
            for db_key, value in {
                "cursorAuth/accessToken": auth_data["accessToken"],
                "cursorAuth/refreshToken": auth_data["refreshToken"],
                "cursorAuth/cachedEmail": auth_data["cachedEmail"],
                "cursorAuth/cachedSignUpType": auth_data["cachedSignUpType"],
                "cursorAuth/cachedScopedProfile": auth_data["cachedScopedProfile"],
                "cursorAuth/stripeMembershipType": auth_data["stripeMembershipType"],
                "glass.lastSignedInAuthId": auth_data["lastSignedInAuthId"],
            }.items():
                con.execute(
                    "INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
                    (db_key, str(value)),
                )
    finally:
        con.close()
    return auth_data


def seed_application_user(db_path: Path) -> dict[str, Any]:
    surfaces = (
        "composer",
        "cmd-k",
        "background-composer",
        "composer-ensemble",
        "plan-execution",
        "spec",
        "deep-search",
        "quick-agent",
    )
    model_config = {
        surface: {
            "modelName": "default",
            "maxMode": False,
            "selectedModels": [{"modelId": "default", "parameters": []}],
        }
        for surface in surfaces
    }
    app_user = {
        "aiSettings": {"modelConfig": model_config},
        "availableDefaultModels2": [
            {"serverModelName": "default", "clientDisplayName": "Auto"},
            {
                "serverModelName": "claude-sonnet-4-6",
                "clientDisplayName": "Sonnet 4.6",
            },
            {"serverModelName": "gpt-5.3-codex", "clientDisplayName": "Codex 5.3"},
        ],
        "featureModelConfigs": {
            "composer": {
                "defaultModel": "default",
                "fallbackModels": ["claude-sonnet-4-6", "gpt-5.3-codex"],
                "bestOfNDefaultModels": ["gpt-5.3-codex"],
            }
        },
        "dashboardUserId": 123,
        "membershipType": "free",
        "isEnterprise": False,
        "modelLastUsedAt": None,
    }
    con = sqlite3.connect(str(db_path))
    try:
        with con:
            con.execute(
                "INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
                (APPLICATION_USER_KEY, json.dumps(app_user)),
            )
    finally:
        con.close()
    return app_user


def make_db(tmp_path: Path, name: str = "state.vscdb") -> Path:
    db_path = tmp_path / "Cursor" / "User" / "globalStorage" / name
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path))
    try:
        con.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value BLOB)")
    finally:
        con.close()
    return db_path


@pytest.fixture
def cursor_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    tool_home = tmp_path / ".cursor-provider"
    db_path = make_db(tmp_path)

    monkeypatch.setattr(cp, "HOME", tmp_path)
    monkeypatch.setattr(cp, "CURSOR_DIR", tmp_path / "Cursor")
    monkeypatch.setattr(cp, "DB_PATH", db_path)
    monkeypatch.setattr(cp, "TOOL_HOME", tool_home)
    monkeypatch.setattr(cp, "DATA_DIR", tool_home)
    monkeypatch.setattr(cp, "STATE_DIR", tool_home / "state")
    monkeypatch.setattr(cp, "AUTH_PATH", tool_home / "auth.json")
    monkeypatch.setattr(cp, "STATE_PATH", tool_home / "state" / "state.json")
    monkeypatch.setattr(cp, "RECENT_PATH", tool_home / "state" / "recent.json")
    monkeypatch.setattr(cp, "LOCK_PATH", tool_home / "state" / "cursor-provider.lock")
    monkeypatch.setattr(cdb, "cursor_running", lambda: False)

    return tmp_path


def read_db_value(db_path: Path, key: str) -> str:
    con = sqlite3.connect(str(db_path))
    try:
        row = con.execute(
            "SELECT value FROM ItemTable WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            raise AssertionError(f"missing key in test database: {key}")
        return str(row[0])
    finally:
        con.close()


def test_add_from_current_and_list(
    cursor_paths: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seed_auth_data(cp.DB_PATH, "a@example.com", display_name="Alice")
    assert cp.main(["add", "work", "--from-current"]) == 0

    capsys.readouterr()
    assert cp.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "* work (a@example.com)" in out


def test_switch_writes_db_and_dry_run_leaves_db_unchanged(
    cursor_paths: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seed_auth_data(cp.DB_PATH, "a@example.com", sub="google-oauth2|user_a")
    assert cp.main(["add", "acc_a", "--from-current"]) == 0

    seed_auth_data(cp.DB_PATH, "b@example.com", sub="google-oauth2|user_b")
    assert cp.main(["add", "acc_b", "--from-current"]) == 0
    assert cp.main(["switch", "acc_b"]) == 0
    assert read_db_value(cp.DB_PATH, "cursorAuth/cachedEmail") == "b@example.com"

    db_before = cp.DB_PATH.read_bytes()
    state_before = cp.STATE_PATH.read_bytes()
    capsys.readouterr()
    assert cp.main(["switch", "acc_a", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "would write auth data for account: acc_a" in out
    assert "would update cursorAuth/accessToken" in out
    assert cp.DB_PATH.read_bytes() == db_before
    assert cp.STATE_PATH.read_bytes() == state_before

    assert cp.main(["switch", "acc_a"]) == 0
    assert read_db_value(cp.DB_PATH, "cursorAuth/cachedEmail") == "a@example.com"
    assert (
        read_db_value(cp.DB_PATH, "glass.lastSignedInAuthId") == "google-oauth2|user_a"
    )


def test_switch_updates_reactive_account_fields(
    cursor_paths: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seed_auth_data(cp.DB_PATH, "a@example.com", sub="google-oauth2|user_a")
    seed_application_user(cp.DB_PATH)
    assert cp.main(["add", "acc_a", "--from-current"]) == 0

    app_user = json.loads(read_db_value(cp.DB_PATH, APPLICATION_USER_KEY))
    assert app_user["dashboardUserId"] == 123

    con = sqlite3.connect(str(cp.DB_PATH))
    try:
        with con:
            con.execute(
                "INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
                ("cursorAuth/cachedEmail", "b@example.com"),
            )
    finally:
        con.close()
    token_b: dict[str, object] = dict(
        seed_auth_data(cp.DB_PATH, "b@example.com", sub="google-oauth2|user_b")
    )
    token_b["dashboardUserId"] = 456
    token_b["membershipType"] = "pro"
    token_b["isEnterprise"] = True
    app_user_b = {
        "aiSettings": {"modelConfig": {}},
        "availableDefaultModels2": [],
        "featureModelConfigs": {},
        "dashboardUserId": 456,
        "membershipType": "pro",
        "isEnterprise": True,
    }
    con = sqlite3.connect(str(cp.DB_PATH))
    try:
        with con:
            con.execute(
                "INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
                (APPLICATION_USER_KEY, json.dumps(app_user_b)),
            )
    finally:
        con.close()
    assert cp.main(["add", "acc_b", "--from-current"]) == 0
    assert cp.main(["switch", "acc_b"]) == 0

    app_user = json.loads(read_db_value(cp.DB_PATH, APPLICATION_USER_KEY))
    assert app_user["dashboardUserId"] == 456
    assert app_user["membershipType"] == "pro"
    assert app_user["isEnterprise"] is True


def test_model_list_and_set(
    cursor_paths: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seed_application_user(cp.DB_PATH)

    capsys.readouterr()
    assert cp.main(["models", "list"]) == 0
    out = capsys.readouterr().out
    assert "model catalog (3)" in out
    assert "- claude-sonnet-4-6 (Sonnet 4.6)" in out
    assert "composer: default" in out

    assert cp.main(["models", "set", "claude-sonnet-4-6"]) == 0
    app_user = json.loads(read_db_value(cp.DB_PATH, APPLICATION_USER_KEY))
    model_config = app_user["aiSettings"]["modelConfig"]
    for surface in ("composer", "cmd-k", "quick-agent", "spec"):
        assert model_config[surface]["modelName"] == "claude-sonnet-4-6"
        assert model_config[surface]["selectedModels"][0]["modelId"] == (
            "claude-sonnet-4-6"
        )
    assert "claude-sonnet-4-6" in app_user["modelLastUsedAt"]

    capsys.readouterr()
    assert cp.main(["models", "set", "not-a-model"]) == 1
    assert "unknown model id" in capsys.readouterr().err

    db_before = cp.DB_PATH.read_bytes()
    capsys.readouterr()
    assert cp.main(["models", "set", "gpt-5.3-codex", "--dry-run"]) == 0
    assert "would set model for 8 surfaces" in capsys.readouterr().out
    assert cp.DB_PATH.read_bytes() == db_before


def test_rename_and_delete(
    cursor_paths: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seed_auth_data(cp.DB_PATH, "a@example.com")
    assert cp.main(["add", "old_name", "--from-current"]) == 0

    assert cp.main(["rename", "old_name", "new_name"]) == 0
    capsys.readouterr()
    assert cp.main(["list"]) == 0
    assert "new_name" in capsys.readouterr().out

    assert cp.main(["delete", "new_name"]) == 0
    capsys.readouterr()
    assert cp.main(["list"]) == 0
    assert "new_name" not in capsys.readouterr().out

    seed_auth_data(cp.DB_PATH, "b@example.com")
    assert cp.main(["add", "acc_b", "--from-current"]) == 0
    assert cp.main(["switch", "acc_b"]) == 0
    assert cp.main(["delete", "acc_b", "--full"]) == 0
    con = sqlite3.connect(str(cp.DB_PATH))
    try:
        assert (
            con.execute(
                "SELECT 1 FROM ItemTable WHERE key = 'cursorAuth/accessToken'"
            ).fetchone()
            is None
        )
        assert (
            con.execute(
                "SELECT 1 FROM ItemTable WHERE key = 'cursorAuth/cachedEmail'"
            ).fetchone()
            is None
        )
    finally:
        con.close()


def test_auth_detail_never_prints_tokens(
    cursor_paths: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    auth_data = seed_auth_data(cp.DB_PATH, "user@example.com")
    assert cp.main(["add", "my_acc", "--from-current"]) == 0

    capsys.readouterr()
    assert cp.main(["auth", "detail", "my_acc"]) == 0
    out = capsys.readouterr().out
    assert "Account: my_acc" in out
    assert "Email: user@example.com" in out
    assert "Name: Test User" in out
    assert "sub: google-oauth2|user_abc" in out
    assert auth_data["accessToken"] not in out
    assert auth_data["refreshToken"] not in out


def test_config_detail_redacts_tokens(
    cursor_paths: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    auth_data = seed_auth_data(cp.DB_PATH, "user@example.com")
    assert cp.main(["add", "my_acc", "--from-current"]) == 0

    capsys.readouterr()
    assert cp.main(["config", "detail", "my_acc"]) == 0
    out = capsys.readouterr().out
    assert "[REDACTED]" in out
    assert auth_data["accessToken"] not in out
    assert auth_data["refreshToken"] not in out


def test_doctor(cursor_paths: Path, capsys: pytest.CaptureFixture[str]) -> None:
    seed_auth_data(cp.DB_PATH, "user@example.com")
    seed_application_user(cp.DB_PATH)

    capsys.readouterr()
    assert cp.main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "[OK] State database exists" in out
    assert "[OK] Access token present" in out
    assert "user@example.com" in out
    assert "[OK] applicationUser state found" in out


def test_status_shows_account_and_model(
    cursor_paths: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seed_auth_data(cp.DB_PATH, "user@example.com")
    app_user = seed_application_user(cp.DB_PATH)
    app_user["aiSettings"]["modelConfig"]["composer"]["modelName"] = "claude-sonnet-4-6"
    con = sqlite3.connect(str(cp.DB_PATH))
    try:
        with con:
            con.execute(
                "INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
                (APPLICATION_USER_KEY, json.dumps(app_user)),
            )
    finally:
        con.close()

    assert cp.main(["add", "work", "--from-current"]) == 0
    capsys.readouterr()
    assert cp.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "Current account: work" in out
    assert "Active identity: user@example.com" in out
    assert "Current model: claude-sonnet-4-6" in out


def test_test_command_checks_token_expiry(
    cursor_paths: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seed_auth_data(cp.DB_PATH, "user@example.com")
    assert cp.main(["add", "fresh", "--from-current"]) == 0
    capsys.readouterr()
    assert cp.main(["test", "fresh"]) == 0
    assert "result: ok" in capsys.readouterr().out

    con = sqlite3.connect(str(cp.DB_PATH))
    try:
        with con:
            con.execute(
                "INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
                ("cursorAuth/cachedEmail", "expired@example.com"),
            )
    finally:
        con.close()
    expired = seed_auth_data(
        cp.DB_PATH, "expired@example.com", sub="google-oauth2|user_e"
    )
    expired["accessToken"] = jwt_with({"sub": "google-oauth2|user_e", "exp": 1})
    con = sqlite3.connect(str(cp.DB_PATH))
    try:
        with con:
            con.execute(
                "INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
                ("cursorAuth/accessToken", expired["accessToken"]),
            )
    finally:
        con.close()
    assert cp.main(["add", "stale", "--from-current"]) == 0
    capsys.readouterr()
    assert cp.main(["test", "stale"]) == 1
    assert "token has expired" in capsys.readouterr().out


def test_export_and_import(
    cursor_paths: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seed_auth_data(cp.DB_PATH, "a@example.com", sub="google-oauth2|user_a")
    assert cp.main(["add", "acc_a", "--from-current"]) == 0

    export_file = cursor_paths / "export.json"
    assert cp.main(["export", str(export_file)]) == 0
    exported = json.loads(export_file.read_text(encoding="utf-8"))
    assert exported["type"] == "cursor-provider"
    assert "acc_a" in exported["accounts"]

    assert cp.main(["delete", "acc_a"]) == 0
    capsys.readouterr()
    assert cp.main(["import", str(export_file), "--dry-run"]) == 0
    assert "would add/update account: acc_a" in capsys.readouterr().out
    capsys.readouterr()
    assert cp.main(["list"]) == 0
    assert "acc_a" not in capsys.readouterr().out

    assert cp.main(["import", str(export_file)]) == 0
    capsys.readouterr()
    assert cp.main(["status"]) == 0
    assert "* acc_a" in capsys.readouterr().out


def test_switch_unknown_account_fails(
    cursor_paths: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seed_auth_data(cp.DB_PATH, "a@example.com")
    assert cp.main(["add", "acc_a", "--from-current"]) == 0
    capsys.readouterr()
    assert cp.main(["switch", "nope"]) == 1
    assert "account not found" in capsys.readouterr().err


def seed_openai_provider(
    db_path: Path, base_url: str = "https://api.deepseek.com/v1"
) -> None:
    app_user = seed_application_user(db_path)
    app_user["openAIBaseUrl"] = base_url
    con = sqlite3.connect(str(db_path))
    try:
        with con:
            con.execute(
                "INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
                (APPLICATION_USER_KEY, json.dumps(app_user)),
            )
            con.execute(
                "INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
                (
                    "secret://cursorAuth/openAIKey",
                    json.dumps({"type": "Buffer", "data": [118, 49, 48, 1, 2, 3]}),
                ),
            )
    finally:
        con.close()


@pytest.fixture
def oscrypt_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    from lib.cursor import oscrypt

    monkeypatch.setattr(oscrypt, "load_oscrypt_key", lambda: b"k" * 32)
    monkeypatch.setattr(oscrypt, "is_oscrypt_available", lambda: True)
    monkeypatch.setattr(
        oscrypt,
        "decrypt_secret_buffer",
        lambda value, key=None: "sk-test-key",
    )
    monkeypatch.setattr(
        oscrypt,
        "encrypt_secret_plaintext",
        lambda plaintext, key=None: json.dumps(
            {"type": "Buffer", "data": list(b"v10" + b"x" * 24)}
        ),
    )


def test_provider_add_from_current_and_list(
    cursor_paths: Path, oscrypt_mock: None, capsys: pytest.CaptureFixture[str]
) -> None:
    seed_openai_provider(cp.DB_PATH)
    assert cp.main(["provider", "add", "deepseek", "--from-current"]) == 0

    capsys.readouterr()
    assert cp.main(["provider", "list"]) == 0
    out = capsys.readouterr().out
    assert "* deepseek (https://api.deepseek.com/v1, key set)" in out

    capsys.readouterr()
    assert cp.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "Accounts:" in out
    assert "Providers:" in out
    assert "Models:" in out
    assert "* deepseek (https://api.deepseek.com/v1, key set)" in out

    capsys.readouterr()
    assert cp.main(["provider", "add", "other", "--from-current", "--dry-run"]) == 0
    assert "would add provider: other" in capsys.readouterr().out
    capsys.readouterr()
    assert cp.main(["provider", "list"]) == 0
    assert "other" not in capsys.readouterr().out


def test_provider_add_with_new_key_and_switch(
    cursor_paths: Path,
    oscrypt_mock: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import io

    seed_application_user(cp.DB_PATH)
    capsys.readouterr()
    assert cp.main(["provider", "add", "moon", "--from-current"]) == 1
    assert "no custom provider configured" in capsys.readouterr().err

    from lib.common import cli as common_cli

    monkeypatch.setattr(common_cli.sys, "stdin", io.StringIO("sk-stdin-key\n"))
    assert (
        cp.main(
            [
                "provider",
                "add",
                "moon",
                "--base-url",
                "https://api.moon.com",
                "--api-key-stdin",
            ]
        )
        == 0
    )
    state = json.loads(cp.STATE_PATH.read_text(encoding="utf-8"))
    assert "moon" in state["providers"]
    assert state["providers"]["moon"]["base_url"] == "https://api.moon.com/v1"
    assert state["providers"]["moon"]["api_key"] == "sk-stdin-key"

    db_before = cp.DB_PATH.read_bytes()
    assert cp.main(["provider", "switch", "moon", "--dry-run"]) == 0
    assert cp.DB_PATH.read_bytes() == db_before

    assert cp.main(["provider", "switch", "moon"]) == 0
    app_user = json.loads(read_db_value(cp.DB_PATH, APPLICATION_USER_KEY))
    assert app_user["openAIBaseUrl"] == "https://api.moon.com/v1"
    assert read_db_value(cp.DB_PATH, "secret://cursorAuth/openAIKey").startswith(
        '{"type": "Buffer"'
    )

    capsys.readouterr()
    assert cp.main(["status"]) == 0
    assert "Current provider: moon" in capsys.readouterr().out


def test_provider_delete_full_clears_cursor_config(
    cursor_paths: Path, oscrypt_mock: None, capsys: pytest.CaptureFixture[str]
) -> None:
    seed_openai_provider(cp.DB_PATH)
    assert cp.main(["provider", "add", "deepseek", "--from-current"]) == 0
    assert cp.main(["provider", "switch", "deepseek"]) == 0

    assert cp.main(["provider", "delete", "deepseek", "--full"]) == 0
    app_user = json.loads(read_db_value(cp.DB_PATH, APPLICATION_USER_KEY))
    assert "openAIBaseUrl" not in app_user
    con = sqlite3.connect(str(cp.DB_PATH))
    try:
        row = con.execute(
            "SELECT 1 FROM ItemTable WHERE key = 'secret://cursorAuth/openAIKey'"
        ).fetchone()
        assert row is None
    finally:
        con.close()


def test_models_sync_fetches_and_adds_catalog_models(
    cursor_paths: Path,
    oscrypt_mock: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed_openai_provider(cp.DB_PATH)
    assert cp.main(["provider", "add", "deepseek", "--from-current"]) == 0

    from lib.cursor import providers as prov_mod

    monkeypatch.setattr(
        prov_mod,
        "_fetch_model_ids",
        lambda base_url, api_key, timeout: ["deepseek-v4-flash", "deepseek-v4-pro"],
    )

    capsys.readouterr()
    assert cp.main(["models", "sync", "deepseek"]) == 0
    out = capsys.readouterr().out
    assert "deepseek-v4-pro" in out
    assert "added 2 new models" in out

    app_user = json.loads(read_db_value(cp.DB_PATH, APPLICATION_USER_KEY))
    catalog_ids = {m["serverModelName"] for m in app_user["availableDefaultModels2"]}
    assert "deepseek-v4-flash" in catalog_ids
    assert "deepseek-v4-pro" in catalog_ids

    capsys.readouterr()
    assert cp.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "- deepseek-v4-flash (deepseek)" in out
    assert "- deepseek-v4-pro (deepseek)" in out


def test_models_sync_requires_api_key(
    cursor_paths: Path,
    oscrypt_mock: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import io

    seed_application_user(cp.DB_PATH)
    assert (
        cp.main(["provider", "add", "nokey", "--base-url", "https://api.nokey.com"])
        == 1
    )
    assert "API key input requires a TTY or --api-key-stdin" in capsys.readouterr().err

    from lib.common import cli as common_cli

    monkeypatch.setattr(common_cli.sys, "stdin", io.StringIO("sk-stdin-key\n"))
    assert (
        cp.main(
            [
                "provider",
                "add",
                "nokey",
                "--base-url",
                "https://api.nokey.com",
                "--api-key-stdin",
            ]
        )
        == 0
    )

    from lib.cursor import providers as prov_mod

    monkeypatch.setattr(prov_mod, "_fetch_model_ids", lambda *a, **k: [])
    capsys.readouterr()
    assert cp.main(["models", "sync", "nokey", "--api-key-stdin"]) == 1
    assert "no models returned by the provider" in capsys.readouterr().err


def test_writes_are_rejected_while_cursor_running(
    cursor_paths: Path,
    oscrypt_mock: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from lib.cursor import db as cdb

    monkeypatch.setattr(cdb, "cursor_running", lambda: True)
    seed_openai_provider(cp.DB_PATH)
    seed_auth_data(cp.DB_PATH, "a@example.com", sub="google-oauth2|user_a")
    assert cp.main(["provider", "add", "deepseek", "--from-current"]) == 0
    assert cp.main(["add", "acc_a", "--from-current"]) == 0

    db_before = cp.DB_PATH.read_bytes()
    capsys.readouterr()
    assert cp.main(["models", "set", "claude-sonnet-4-6"]) == 1
    assert "quit Cursor first" in capsys.readouterr().err
    assert cp.DB_PATH.read_bytes() == db_before

    assert cp.main(["provider", "switch", "deepseek"]) == 1
    assert cp.DB_PATH.read_bytes() == db_before

    assert cp.main(["switch", "acc_a"]) == 1
    assert cp.DB_PATH.read_bytes() == db_before

    capsys.readouterr()
    assert cp.main(["models", "set", "claude-sonnet-4-6", "--force"]) == 0
    assert "warning: Cursor appears to be running" in capsys.readouterr().err
    assert cp.DB_PATH.read_bytes() != db_before


def test_password_to_aes_key_accepts_base64_32_bytes() -> None:
    import base64

    from lib.cursor import oscrypt

    key = b"k" * 32
    assert oscrypt.password_to_aes_key(base64.b64encode(key).decode()) == key
    assert oscrypt.password_to_aes_key("not-base64!!") is None
    assert oscrypt.password_to_aes_key(base64.b64encode(b"short").decode()) is None


def test_oscrypt_roundtrip_with_explicit_key() -> None:
    from lib.cursor import oscrypt

    key = b"\x01" * 32
    cipher = oscrypt.encrypt_secret_plaintext("sk-roundtrip", key=key)
    assert cipher is not None
    assert cipher.startswith('{"type": "Buffer"')
    plain = oscrypt.decrypt_secret_buffer(cipher, key=key)
    assert plain == "sk-roundtrip"
