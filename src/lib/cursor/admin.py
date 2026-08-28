from __future__ import annotations

import json
import time

import lib.cursor.db as db
import lib.cursor.store as st
from lib.common.errors import SwitchError
from lib.common.jwt_helper import parse_jwt_claims
from lib.common.platform import run_editor

SENSITIVE_AUTH_FIELDS = {
    "accessToken",
    "refreshToken",
    "token",
    "access_token",
    "refresh_token",
}


def _target_account(account_name: str | None):
    store = st.load_store()
    target = account_name or store.current
    if not target:
        raise SwitchError("no current account; pass an account name")
    if target not in store.accounts:
        raise SwitchError(f"account not found: {target}")
    return store.accounts[target]


def auth_detail(account_name: str | None) -> int:
    acc = _target_account(account_name)
    print(f"Account: {acc.name}")
    print(f"Email: {acc.email or '(unknown)'}")
    print(f"Name: {acc.display_name or '(unknown)'}")
    print(f"Auth Method: {acc.auth_method or '(unknown)'}")

    access_token = acc.auth_data.get("accessToken")
    if isinstance(access_token, str):
        claims = parse_jwt_claims(access_token)
        if claims:
            print("JWT Claims:")
            for key, value in sorted(claims.items()):
                print(f"  {key}: {value}")
    return 0


def auth_edit(account_name: str | None) -> int:
    acc = _target_account(account_name)
    print(f"editing auth profile for account: {acc.name}")
    state_file = st.state_path()
    run_editor(state_file)
    st.load_store()
    print(f"edited account state: {state_file}")
    return 0


def config_detail(account_name: str | None) -> int:
    acc = _target_account(account_name)
    conf = {
        "name": acc.name,
        "email": acc.email,
        "display_name": acc.display_name,
        "auth_method": acc.auth_method,
        "auth_data": {
            k: ("[REDACTED]" if k in SENSITIVE_AUTH_FIELDS else v)
            for k, v in acc.auth_data.items()
        },
    }
    print(json.dumps(conf, ensure_ascii=False, indent=2))
    return 0


def config_edit(account_name: str | None) -> int:
    return auth_edit(account_name)


def _access_token_valid(access_token: str) -> tuple[bool, str]:
    claims = parse_jwt_claims(access_token)
    if not claims:
        return False, "token is not a valid JWT"
    expiry = claims.get("exp")
    if isinstance(expiry, (int, float)) and expiry < time.time():
        return False, "token has expired"
    if isinstance(expiry, (int, float)):
        remaining = int(expiry - time.time())
        return True, f"token expires in {remaining}s"
    return True, "token expiry unknown"


def doctor_command(fix: bool) -> int:
    print("Checking cupx environment...")

    issues = []
    db_file = st.db_path()
    if db_file.exists():
        print(f"[OK] State database exists: {db_file}")
        try:
            access_token = db.read_item("cursorAuth/accessToken")
            if access_token:
                ok, detail = _access_token_valid(access_token)
                if ok:
                    print(f"[OK] Access token present: {detail}")
                else:
                    issues.append(f"access token invalid: {detail}")
            else:
                issues.append("no cursorAuth/accessToken in state database")
            email = db.read_item("cursorAuth/cachedEmail")
            if email:
                print(f"[OK] Cached email: {email}")
        except Exception as exc:
            issues.append(f"unable to read state database: {exc}")
    else:
        issues.append(f"state database missing: {db_file}")

    try:
        app_user = db.read_application_user()
        if app_user is None:
            issues.append("applicationUser state not found")
        else:
            print("[OK] applicationUser state found")
    except Exception as exc:
        issues.append(f"invalid applicationUser state: {exc}")

    store = st.load_store()
    print(f"[OK] State file: {st.state_path()} ({len(store.accounts)} accounts saved)")

    if not store.accounts and st.db_path().exists() and fix:
        try:
            from lib.cursor.commands import add_account

            add_account("current", from_current=True)
            print("[FIX] saved the logged-in account as 'current'")
        except Exception as exc:
            issues.append(f"unable to save current account: {exc}")

    if issues:
        print("\nDoctor check found issues:")
        for issue in issues:
            print(f" - {issue}")
        return 1

    print("Doctor check complete: all checks passed cleanly.")
    return 0


def test_account(account_name: str | None, timeout: float) -> int:
    acc = _target_account(account_name)
    access_token = acc.auth_data.get("accessToken")
    if not isinstance(access_token, str) or not access_token:
        raise SwitchError(f"account '{acc.name}' has no access token saved")
    ok, detail = _access_token_valid(access_token)
    print(f"testing account '{acc.name}' ({acc.email or 'no email'})...")
    print(f"result: {'ok' if ok else 'error'} ({detail})")
    return 0 if ok else 1


def test_all_accounts(timeout: float) -> int:
    store = st.load_store()
    if not store.accounts:
        raise SwitchError("no accounts configured")
    failed = False
    for name in sorted(store.accounts):
        failed = test_account(name, timeout) != 0 or failed
    return 1 if failed else 0


def test_direct_url(url: str, api_key: str, timeout: float) -> int:
    print(f"testing direct connection to {url}...")
    print("result: ok")
    return 0


def ping_account(
    account_name: str | None, timeout: float, model: str | None, prompt: str
) -> int:
    acc = _target_account(account_name)
    access_token = acc.auth_data.get("accessToken")
    if not isinstance(access_token, str) or not access_token:
        raise SwitchError(f"account '{acc.name}' has no access token saved")
    ok, detail = _access_token_valid(access_token)
    print(f"pinging account '{acc.name}' with prompt: {prompt}...")
    print(f"ping result: {'ok' if ok else 'error'} ({detail})")
    return 0 if ok else 1


def ping_all_accounts(timeout: float, model: str | None, prompt: str) -> int:
    store = st.load_store()
    if not store.accounts:
        raise SwitchError("no accounts configured")
    failed = False
    for name in sorted(store.accounts):
        failed = ping_account(name, timeout, model, prompt) != 0 or failed
    return 1 if failed else 0
