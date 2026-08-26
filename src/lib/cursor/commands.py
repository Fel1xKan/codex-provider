from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import lib.cursor.db as db
import lib.cursor.store as st
from lib.common.common_store import (
    atomic_write_bytes,
    defer_directory_sync,
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


def _save_state_file(
    current: str,
    accounts: dict[str, Any],
    current_provider: str = "",
    providers: dict[str, Any] | None = None,
) -> None:
    state_data = {
        "current": current,
        "accounts": accounts,
        "current_provider": current_provider,
        "providers": providers or {},
    }
    st.state_dir().mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(
        st.state_path(),
        json.dumps(state_data, indent=2).encode("utf-8") + b"\n",
        secret=True,
        mode=SECRET_FILE_MODE,
    )


def _ensure_cursor_quit(force: bool) -> None:
    """Refuse to write Cursor's database while Cursor is running.

    Cursor caches the reactive storage in memory and overwrites database
    changes on save, so writes only take effect when the app is closed.
    """
    if not db.cursor_running():
        return
    if force:
        print(
            "warning: Cursor appears to be running; changes may be overwritten "
            "by Cursor and require a restart",
            file=sys.stderr,
        )
        return
    raise SwitchError(
        "Cursor appears to be running; quit Cursor first so the change is not "
        "overwritten, or pass --force to write anyway"
    )


def print_list() -> int:
    store = st.load_store()

    print("Accounts:")
    if not store.accounts:
        print("  (none)")
    for name in sort_providers_by_recent(
        store.accounts, ensure_recent_providers(st.recent_path())
    ):
        acc = store.accounts[name]
        marker = "*" if name == store.current else " "
        detail = f" ({acc.email})" if acc.email else ""
        print(f"{marker} {name}{detail}")

    print("Providers:")
    if not store.providers:
        print("  (none)")
    for name, prov in store.providers.items():
        marker = "*" if name == store.current_provider else " "
        key_state = "key set" if (prov.api_key or prov.api_key_cipher) else "no key"
        print(f"{marker} {name} ({prov.base_url}, {key_state})")

    print("Models:")
    models = db.user_added_models()
    if not models:
        print("  (none; run 'models sync <provider>' to import remote models)")
    for model in models:
        model_id = str(model.get("serverModelName") or model.get("name") or "")
        if not model_id:
            continue
        providers = sorted(
            name for name, prov in store.providers.items() if model_id in prov.models
        )
        origin = f" ({', '.join(providers)})" if providers else " (custom)"
        print(f"  - {model_id}{origin}")
    return 0


def print_status() -> int:
    store = st.load_store()
    current_acc = store.accounts.get(store.current) if store.current else None
    email = current_acc.email if current_acc else ""
    print(f"state database: {st.db_path()}")
    print(f"state file: {st.state_path()}")
    print(f"Current account: {store.current or '(none)'}")
    if email:
        print(f"Active identity: {email}")
    current_provider = store.providers.get(store.current_provider)
    if current_provider:
        print(
            f"Current provider: {store.current_provider} ({current_provider.base_url})"
        )
    base_url = db.read_openai_base_url()
    if base_url and (not current_provider or base_url != current_provider.base_url):
        print(f"Cursor base URL: {base_url}")
    current_model = db.read_current_model()
    if current_model:
        print(f"Current model: {current_model}")
    print("")
    return print_list()


def switch_account(
    account_name: str, dry_run: bool = False, force: bool = False
) -> int:
    if not st.ACCOUNT_PATTERN.fullmatch(account_name):
        raise SwitchError(f"invalid account name: {account_name}")
    st.acquire_lock()
    try:
        store = st.load_store()
        if account_name not in store.accounts:
            raise SwitchError(f"account not found: {account_name}")
        acc = store.accounts[account_name]

        if dry_run:
            print(f"would write auth data for account: {account_name}")
            for key in sorted(db.auth_db_updates(acc.auth_data)):
                print(f"  would update {key}")
            return 0

        _ensure_cursor_quit(force)
        db.apply_account_auth(acc.auth_data)
        accounts_data = st.accounts_data_dict(store)
        with defer_directory_sync():
            _save_state_file(account_name, accounts_data)
            record_recent_provider(st.recent_path(), account_name)
    finally:
        st.release_lock()
    print(f"switched account: {account_name}")
    return 0


def add_account(
    name: str,
    from_current: bool = False,
    from_file: str | None = None,
    dry_run: bool = False,
) -> int:
    if (
        not (from_current or from_file)
        and st.db_path().exists()
        and db.read_item("cursorAuth/accessToken")
    ):
        from_current = True

    if not st.ACCOUNT_PATTERN.fullmatch(name):
        raise SwitchError(f"invalid account name: {name}")

    if from_current:
        auth_data = db.current_auth_snapshot()
        if not auth_data:
            raise SwitchError("no logged-in Cursor account found in the state database")
    elif from_file:
        file_path = Path(from_file).expanduser()
        if not file_path.exists():
            raise SwitchError(f"auth file not found: {from_file}")
        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SwitchError(f"invalid auth JSON: {file_path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise SwitchError("auth file must contain a JSON object")
        auth_data = payload.get("auth_data", payload)
        if not isinstance(auth_data, dict):
            raise SwitchError("auth_data must be a JSON object")
    else:
        raise SwitchError(
            "must specify --from-current or --from-file, or log in to Cursor first"
        )

    email, display_name, auth_method = st.extract_account_info(auth_data)

    st.acquire_lock()
    try:
        store = st.load_store()
        accounts_data = st.accounts_data_dict(store)
        accounts_data[name] = {
            "email": email,
            "display_name": display_name,
            "auth_method": auth_method,
            "auth_data": auth_data,
        }
        if not dry_run:
            with defer_directory_sync():
                _save_state_file(store.current or name, accounts_data)
                record_recent_provider(st.recent_path(), name)
    finally:
        st.release_lock()

    action = "would add" if dry_run else "added"
    detail = f" ({email})" if email else ""
    print(f"{action} account: {name}{detail}")
    return 0


def delete_account(
    name: str, full: bool = False, dry_run: bool = False, force: bool = False
) -> int:
    st.acquire_lock()
    try:
        store = st.load_store()
        if name not in store.accounts:
            raise SwitchError(f"account not found: {name}")
        current = store.current
        if current == name:
            current = ""
        accounts_data = st.accounts_data_dict(store)
        accounts_data.pop(name, None)
        if not dry_run:
            with defer_directory_sync():
                _save_state_file(current, accounts_data)
                forget_recent_provider(st.recent_path(), name)
            if full:
                _ensure_cursor_quit(force)
                db.clear_account_auth()
    finally:
        st.release_lock()
    action = "would delete" if dry_run else "deleted"
    extra = " and clear auth from Cursor" if full else ""
    print(f"{action} account: {name}{extra}")
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
        accounts_data = st.accounts_data_dict(store)
        accounts_data[new_name] = accounts_data.pop(old_name)
        if not dry_run:
            with defer_directory_sync():
                _save_state_file(current, accounts_data)
                rename_recent_provider(st.recent_path(), old_name, new_name)
    finally:
        st.release_lock()
    action = "would rename" if dry_run else "renamed"
    print(f"{action} account: {old_name} -> {new_name}")
    return 0
