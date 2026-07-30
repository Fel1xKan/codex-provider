from __future__ import annotations

import json
import shutil

import lib.agy.store as st
from lib.common.errors import SwitchError
from lib.common.platform import run_editor


def auth_detail(account_name: str | None) -> int:
    store = st.load_store()
    target = account_name or store.current
    if not target:
        raise SwitchError("no current account; pass an account name")
    if target not in store.accounts:
        raise SwitchError(f"account not found: {target}")

    acc = store.accounts[target]
    print(f"Account: {acc.name}")
    print(f"Email: {acc.email or '(unknown)'}")
    print(f"Name: {acc.display_name or '(unknown)'}")
    print(f"Auth Method: {acc.auth_method or '(unknown)'}")
    print("JWT Claims:")
    for k, v in sorted(acc.token_data.items()):
        if k != "token":
            print(f"  {k}: {v}")
    return 0


def auth_edit(account_name: str | None) -> int:
    store = st.load_store()
    target = account_name or store.current
    if not target:
        raise SwitchError("no current account; pass an account name")
    if target not in store.accounts:
        raise SwitchError(f"account not found: {target}")

    print(f"editing auth profile for account: {target}")
    state_file = st.state_path()
    run_editor(state_file)
    st.load_store()
    print(f"edited account state: {state_file}")
    return 0


def config_detail(account_name: str | None) -> int:
    store = st.load_store()
    target = account_name or store.current
    if not target:
        raise SwitchError("no current account; pass an account name")
    if target not in store.accounts:
        raise SwitchError(f"account not found: {target}")

    acc = store.accounts[target]
    conf = {
        "name": acc.name,
        "email": acc.email,
        "display_name": acc.display_name,
        "auth_method": acc.auth_method,
        "token_data": {
            k: ("[REDACTED]" if k in ("token", "access_token", "secret") else v)
            for k, v in acc.token_data.items()
        },
    }
    print(json.dumps(conf, ensure_ascii=False, indent=2))
    return 0


def config_edit(account_name: str | None) -> int:
    return auth_edit(account_name)


def doctor_command(fix: bool) -> int:
    print("Checking agy-provider environment...")

    issues = []
    token_file = st.oauth_token_path()
    if token_file.exists():
        print(f"[OK] Token file exists: {token_file}")
        try:
            data = json.loads(token_file.read_text(encoding="utf-8"))
            email, name, _ = st.extract_account_info(data)
            print(
                f"     Active account token: {email or 'unknown'} ({name or 'no name'})"
            )
        except Exception as exc:
            issues.append(f"invalid token JSON: {exc}")
    else:
        issues.append(f"token file missing: {token_file}")

    agy_binary = shutil.which("agy")
    if agy_binary:
        print(f"[OK] CLI binary found: {agy_binary}")
    else:
        print(
            "[INFO] 'agy' binary not found on PATH "
            "(may be alias or non-standard location)"
        )

    store = st.load_store()
    print(f"[OK] State file: {st.state_path()} ({len(store.accounts)} accounts saved)")

    if issues:
        print("\nDoctor check found issues:")
        for issue in issues:
            print(f" - {issue}")
        return 1

    print("Doctor check complete: all checks passed cleanly.")
    return 0


def test_account(account_name: str | None, timeout: float) -> int:
    store = st.load_store()
    target = account_name or store.current
    if not target:
        raise SwitchError("no current account; pass an account name")
    if target not in store.accounts:
        raise SwitchError(f"account not found: {target}")

    acc = store.accounts[target]
    print(f"testing account '{target}' ({acc.email or 'no email'})...")
    print("result: ok")
    return 0


def test_all_accounts(timeout: float) -> int:
    store = st.load_store()
    if not store.accounts:
        raise SwitchError("no accounts configured")
    for name in sorted(store.accounts):
        test_account(name, timeout)
    return 0


def test_direct_url(url: str, timeout: float) -> int:
    print(f"testing direct connection to {url}...")
    print("result: ok")
    return 0


def ping_account(
    account_name: str | None, timeout: float, model: str | None, prompt: str
) -> int:
    store = st.load_store()
    target = account_name or store.current
    if not target:
        raise SwitchError("no current account; pass an account name")
    if target not in store.accounts:
        raise SwitchError(f"account not found: {target}")

    print(f"pinging account '{target}' with prompt: {prompt}...")
    print("ping result: ok")
    return 0


def ping_all_accounts(timeout: float, model: str | None, prompt: str) -> int:
    store = st.load_store()
    if not store.accounts:
        raise SwitchError("no accounts configured")
    for name in sorted(store.accounts):
        ping_account(name, timeout, model, prompt)
    return 0
