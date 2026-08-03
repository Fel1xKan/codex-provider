from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import lib.agy.store as st
from lib.common.common_store import (
    atomic_write_bytes,
    fsync_directory,
)
from lib.common.constants import SECRET_FILE_MODE
from lib.common.errors import SwitchError
from lib.common.recent import (
    ensure_recent_providers,
    forget_recent_provider,
    record_recent_provider,
    rename_recent_provider,
    sort_providers_by_recent,
)


def _save_state_file(current: str, accounts: dict[str, Any]) -> None:
    state_data = {"current": current, "accounts": accounts}
    st.state_dir().mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(
        st.state_path(),
        json.dumps(state_data, indent=2).encode("utf-8") + b"\n",
        secret=True,
        mode=SECRET_FILE_MODE,
    )


def print_list() -> int:
    store = st.load_store()
    for name in sort_providers_by_recent(
        store.accounts, ensure_recent_providers(st.recent_path())
    ):
        acc = store.accounts[name]
        marker = "*" if name == store.current else " "
        detail = f" ({acc.email})" if acc.email else ""
        print(f"{marker} {name}{detail}")
    return 0


def print_status() -> int:
    store = st.load_store()
    current_acc = store.accounts.get(store.current) if store.current else None
    email = current_acc.email if current_acc else ""
    print(f"oauth token path: {st.oauth_token_path()}")
    print(f"auth file: {st.auth_path()}")
    print(f"Current account: {store.current or '(none)'}")
    if email:
        print(f"Active identity: {email}")
    print("")
    return print_list()


def switch_account(account_name: str, dry_run: bool = False) -> int:
    if not st.ACCOUNT_PATTERN.fullmatch(account_name):
        raise SwitchError(f"invalid account name: {account_name}")
    st.acquire_lock()
    try:
        store = st.load_store()
        if account_name not in store.accounts:
            raise SwitchError(f"account not found: {account_name}")
        acc = store.accounts[account_name]
        if not dry_run:
            token_payload = json.dumps(acc.token_data, indent=2).encode("utf-8") + b"\n"
            st.oauth_token_path().parent.mkdir(parents=True, exist_ok=True)
            atomic_write_bytes(
                st.oauth_token_path(),
                token_payload,
                secret=True,
                mode=SECRET_FILE_MODE,
            )
            atomic_write_bytes(
                st.standalone_oauth_token_path(),
                token_payload,
                secret=True,
                mode=SECRET_FILE_MODE,
            )
            fsync_directory(st.oauth_token_path().parent)
            st.write_wincred_token(acc.token_data)
            accounts_data = {
                name: {
                    "email": a.email,
                    "display_name": a.display_name,
                    "auth_method": a.auth_method,
                    "token_data": a.token_data,
                }
                for name, a in store.accounts.items()
            }
            _save_state_file(account_name, accounts_data)
            record_recent_provider(st.recent_path(), account_name)
    finally:
        st.release_lock()
    action = "would switch" if dry_run else "switched"
    print(f"{action} account: {account_name}")
    return 0


def add_account(
    name: str,
    from_current: bool = False,
    from_dir: str | None = None,
    from_file: str | None = None,
    dry_run: bool = False,
) -> int:
    if not (from_current or from_dir or from_file):
        given_path = Path(name).expanduser()
        if given_path.is_dir():
            from_dir = str(given_path)
            name = given_path.name
        elif st.oauth_token_path().exists():
            from_current = True

    if not st.ACCOUNT_PATTERN.fullmatch(name):
        raise SwitchError(f"invalid account name: {name}")

    token_data = None
    if from_current:
        token_path = st.oauth_token_path()
        if not token_path.exists():
            raise SwitchError(f"current token file not found: {token_path}")
        try:
            token_data = json.loads(token_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SwitchError(
                f"invalid current token JSON: {token_path}: {exc}"
            ) from exc
    elif from_dir:
        dir_path = Path(from_dir).expanduser()
        token_path = (
            dir_path / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"
        )
        if not token_path.exists():
            token_path = (
                dir_path
                / ".gemini"
                / "antigravity-cli"
                / "jetski-standalone-oauth-token"
            )
        if not token_path.exists():
            token_path = dir_path / "antigravity-oauth-token"
        if not token_path.exists():
            raise SwitchError(f"token file not found in directory: {from_dir}")
        try:
            token_data = json.loads(token_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SwitchError(f"invalid token JSON: {token_path}: {exc}") from exc
    elif from_file:
        file_path = Path(from_file).expanduser()
        if not file_path.exists():
            raise SwitchError(f"token file not found: {from_file}")
        try:
            token_data = json.loads(file_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SwitchError(f"invalid token JSON: {file_path}: {exc}") from exc
    else:
        raise SwitchError(
            "must specify one of --from-current, --from-dir, or --from-file"
        )

    if not isinstance(token_data, dict):
        raise SwitchError("token file must contain a JSON object")

    email, display_name, auth_method = st.extract_account_info(token_data)

    st.acquire_lock()
    try:
        store = st.load_store()
        accounts_data = {
            n: {
                "email": a.email,
                "display_name": a.display_name,
                "auth_method": a.auth_method,
                "token_data": a.token_data,
            }
            for n, a in store.accounts.items()
        }
        accounts_data[name] = {
            "email": email,
            "display_name": display_name,
            "auth_method": auth_method,
            "token_data": token_data,
        }
        if not dry_run:
            _save_state_file(store.current or name, accounts_data)
            record_recent_provider(st.recent_path(), name)
    finally:
        st.release_lock()

    action = "would add" if dry_run else "added"
    detail = f" ({email})" if email else ""
    print(f"{action} account: {name}{detail}")
    return 0


def delete_account(name: str, full: bool = False, dry_run: bool = False) -> int:
    st.acquire_lock()
    try:
        store = st.load_store()
        if name not in store.accounts:
            raise SwitchError(f"account not found: {name}")
        current = store.current
        if current == name:
            current = ""
        accounts_data = {
            n: {
                "email": a.email,
                "display_name": a.display_name,
                "auth_method": a.auth_method,
                "token_data": a.token_data,
            }
            for n, a in store.accounts.items()
            if n != name
        }
        if not dry_run:
            _save_state_file(current, accounts_data)
            forget_recent_provider(st.recent_path(), name)
    finally:
        st.release_lock()
    action = "would delete" if dry_run else "deleted"
    print(f"{action} account: {name}")
    return 0


def rename_account(old_name: str, new_name: str, dry_run: bool = False) -> int:
    if not st.ACCOUNT_PATTERN.fullmatch(new_name):
        raise SwitchError(f"invalid account name: {new_name}")
    st.acquire_lock()
    try:
        store = st.load_store()
        if old_name not in store.accounts:
            raise SwitchError(f"account not found: {old_name}")
        if new_name in store.accounts and new_name != old_name:
            raise SwitchError(f"account already exists: {new_name}")

        current = new_name if store.current == old_name else store.current
        accounts_data = {}
        for n, a in store.accounts.items():
            target_key = new_name if n == old_name else n
            accounts_data[target_key] = {
                "email": a.email,
                "display_name": a.display_name,
                "auth_method": a.auth_method,
                "token_data": a.token_data,
            }
        if not dry_run:
            _save_state_file(current, accounts_data)
            rename_recent_provider(st.recent_path(), old_name, new_name)
    finally:
        st.release_lock()
    action = "would rename" if dry_run else "renamed"
    print(f"{action} account: {old_name} -> {new_name}")
    return 0
