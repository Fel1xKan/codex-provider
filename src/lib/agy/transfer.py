from __future__ import annotations

import json
from contextlib import nullcontext

import lib.agy.store as st
from lib.agy.commands import switch_account
from lib.common.errors import SwitchError
from lib.common.transfer import (
    read_import_data,
    validate_export,
    write_export,
)


def export_command(file_path: str | None) -> int:
    store = st.load_store()
    accounts_data = {}
    for name, a in store.accounts.items():
        accounts_data[name] = {
            "email": a.email,
            "display_name": a.display_name,
            "auth_method": a.auth_method,
            "token_data": a.token_data,
        }

    export_data = {
        "type": "agy-provider",
        "version": 1,
        "current": store.current,
        "accounts": accounts_data,
    }

    payload = json.dumps(export_data, indent=2, ensure_ascii=False) + "\n"
    write_export(payload, file_path, "agy")
    return 0


def import_command(file_path: str | None, dry_run: bool) -> int:
    try:
        data = read_import_data(file_path)
    except KeyboardInterrupt:
        return 1
    validate_export(data, "agy-provider")

    accounts_to_import = data.get("accounts")
    if not isinstance(accounts_to_import, dict):
        raise SwitchError("accounts must be a JSON object")

    lock = nullcontext() if dry_run else st.lock_mgr
    with lock:
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

        for name, acc_info in accounts_to_import.items():
            if not st.ACCOUNT_PATTERN.fullmatch(name):
                raise SwitchError(f"invalid account name: {name}")
            if not isinstance(acc_info, dict):
                raise SwitchError(f"invalid account entry: {name}")
            token_data = acc_info.get("token_data")
            if not isinstance(token_data, dict):
                raise SwitchError(f"account {name} must have a token_data object")

            email, display_name, auth_method = st.extract_account_info(token_data)

            action = "would add/update" if dry_run else "added/updated"
            print(f"{action} account: {name}")

            if not dry_run:
                accounts_data[name] = {
                    "email": acc_info.get("email") or email,
                    "display_name": acc_info.get("display_name") or display_name,
                    "auth_method": acc_info.get("auth_method") or auth_method,
                    "token_data": token_data,
                }

        current = data.get("current")

        if not dry_run:
            from lib.agy.commands import _save_state_file

            st.state_dir().mkdir(parents=True, exist_ok=True)
            _save_state_file(store.current or current or "", accounts_data)

        if current and (current in accounts_to_import or current in store.accounts):
            if dry_run:
                print(f"would switch account: {current}")
            else:
                switch_account(current, dry_run=False)

    return 0
