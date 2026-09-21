from __future__ import annotations

import json
import sqlite3
from typing import Any

from lib.common.errors import SwitchError
from lib.xpx.adapters.agy import get_agy_cli_dir
from lib.xpx.adapters.codex import get_codex_home
from lib.xpx.adapters.cursor import get_cursor_db_path
from lib.xpx.adapters.registry import get_adapter
from lib.xpx.store.account_store import AccountSpec, AccountStore


def run_account_login(args: Any) -> int:
    target = args.target.strip().lower()
    name = getattr(args, "name", None) or "default"
    get_adapter(target)  # validate target

    if target == "agy":
        from lib.xpx.accounts.agy_login import login as agy_login

        token_data = agy_login()
        if not token_data:
            raise SwitchError("Antigravity OAuth login was cancelled or failed")
        acc_store = AccountStore()
        acc = AccountSpec(
            target="agy",
            name=name,
            account_type="google-oauth",
            token_data=token_data,
        )
        acc_store.save(acc)
        print(f"✔ Logged in and saved Antigravity account '{name}'.")
        return 0

    raise SwitchError(
        f"interactive login is not supported for '{target}'; "
        "use 'snapshot' to capture existing login"
    )


def run_account_snapshot(args: Any) -> int:
    target = args.target.strip().lower()
    name = args.name.strip()
    get_adapter(target)
    acc_store = AccountStore()

    if target == "codex":
        auth_file = get_codex_home() / "auth.json"
        if not auth_file.is_file():
            raise SwitchError(f"no Codex auth file found at {auth_file}")
        try:
            token_data = json.loads(auth_file.read_text(encoding="utf-8"))
        except Exception as exc:
            raise SwitchError(f"unable to read {auth_file}: {exc}") from exc
        acc = AccountSpec(
            target="codex",
            name=name,
            account_type="chatgpt-session",
            token_data=token_data,
        )
        acc_store.save(acc)
        print(f"✔ Snapshot saved for Codex account '{name}'.")
        return 0

    if target == "cursor":
        db_path = get_cursor_db_path()
        if not db_path.is_file():
            raise SwitchError(f"Cursor state database not found at {db_path}")
        con = sqlite3.connect(str(db_path))
        try:
            auth_keys = (
                "cursorAuth/accessToken",
                "cursorAuth/refreshToken",
                "cursorAuth/cachedEmail",
                "cursorAuth/cachedSignUpType",
                "cursorAuth/stripeMembershipType",
            )
            placeholders = ",".join("?" for _ in auth_keys)
            query = f"SELECT key, value FROM ItemTable WHERE key IN ({placeholders})"
            rows = dict(con.execute(query, auth_keys).fetchall())
            if not rows:
                raise SwitchError("no Cursor auth credentials found in state database")
            acc = AccountSpec(
                target="cursor",
                name=name,
                account_type="cursor-auth",
                token_data=rows,
                metadata={"email": rows.get("cursorAuth/cachedEmail", "")},
            )
            acc_store.save(acc)
            print(f"✔ Snapshot saved for Cursor account '{name}'.")
            return 0
        finally:
            con.close()

    if target == "agy":
        token_file = get_agy_cli_dir() / "antigravity-oauth-token"
        if not token_file.is_file():
            raise SwitchError(f"no Antigravity token found at {token_file}")
        try:
            token_data = json.loads(token_file.read_text(encoding="utf-8"))
        except Exception as exc:
            raise SwitchError(f"unable to read {token_file}: {exc}") from exc
        acc = AccountSpec(
            target="agy",
            name=name,
            account_type="google-oauth",
            token_data=token_data,
        )
        acc_store.save(acc)
        print(f"✔ Snapshot saved for Antigravity account '{name}'.")
        return 0

    raise SwitchError(f"account snapshot is not supported for '{target}'")


def run_account_list(args: Any) -> int:
    acc_store = AccountStore()
    accounts = acc_store.list_all()
    if not accounts:
        print(
            "No accounts saved. Run 'xpx account snapshot <target> <name>' to save one."
        )
        return 0

    header = f"{'TARGET':<12} {'NAME':<20} {'TYPE':<20} {'IDENTITY':<25}"
    print(header)
    print("-" * len(header))
    for a in accounts:
        ident = a.metadata.get("email") or "-"
        print(f"{a.target:<12} {a.name:<20} {a.account_type:<20} {ident:<25}")
    return 0


def run_account_usage(args: Any) -> int:
    target = getattr(args, "target", "agy") or "agy"
    name = getattr(args, "name", None)

    if target != "agy":
        print(f"Quota usage query is not supported for '{target}'.")
        return 0

    acc_store = AccountStore()
    if name:
        acc = acc_store.require("agy", name)
    else:
        accounts = acc_store.list_by_target("agy")
        if not accounts:
            raise SwitchError("no Antigravity accounts saved")
        acc = accounts[0]

    from lib.xpx.accounts.agy_usage import print_account_usage

    return print_account_usage(acc.token_data, acc.name)
