from __future__ import annotations

import argparse
import sys

import lib.agy.store as st
from lib.agy.admin import (
    auth_detail,
    auth_edit,
    config_detail,
    config_edit,
    doctor_command,
    ping_account,
    ping_all_accounts,
    test_account,
    test_all_accounts,
    test_direct_url,
)
from lib.agy.commands import (
    add_account,
    delete_account,
    print_list,
    print_status,
    rename_account,
    switch_account,
)
from lib.common.cli import (
    add_auth_parser,
    add_config_parser,
    add_doctor_parser,
    add_ping_parser,
    add_switch_parser,
    add_test_parser,
    dispatch_ping,
    dispatch_test,
)
from lib.common.constants import VERSION
from lib.common.errors import SwitchError
from lib.common.platform import select_provider_interactive
from lib.common.recent import (
    load_recent_providers,
    sort_providers_by_recent,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agy-provider",
        description="Switch account configurations for Antigravity (agy) CLI.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="List accounts from agy-provider config")
    subparsers.add_parser("status", help="Show the current active account and status")

    add_auth_parser(subparsers)
    add_config_parser(subparsers)
    add_doctor_parser(subparsers)
    add_switch_parser(subparsers, include_model=False)

    add = subparsers.add_parser("add", help="Add or import an account configuration")
    add.add_argument("account", nargs="?", help="Account name")
    add.add_argument("base_url", nargs="?", help=argparse.SUPPRESS)
    add.add_argument("legacy_api_key", nargs="?", help=argparse.SUPPRESS)
    add.add_argument(
        "--api-key-stdin",
        action="store_true",
        help="Read token JSON from stdin instead of interactive prompt",
    )
    add.add_argument("--from-dir", help="Import token from an account directory")
    add.add_argument("--from-current", action="store_true", help="Import active token")
    add.add_argument(
        "--dry-run", action="store_true", help="Preview changes without writing files"
    )

    delete = subparsers.add_parser("delete", help="Delete an account")
    delete.add_argument("provider", help="Account name to delete")
    delete.add_argument(
        "--full", action="store_true", help="Also remove account authentication data"
    )
    delete.add_argument(
        "--dry-run", action="store_true", help="Preview changes without writing files"
    )

    rename = subparsers.add_parser("rename", help="Rename an account")
    rename.add_argument("old_provider", help="Existing account name")
    rename.add_argument("new_provider", help="New account name")
    rename.add_argument(
        "--dry-run", action="store_true", help="Preview changes without writing files"
    )

    add_test_parser(subparsers)
    add_ping_parser(subparsers, "agy")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1

    try:
        if args.command == "list":
            return print_list()
        if args.command == "status":
            return print_status()

        if args.command == "switch":
            account = args.provider
            if account is None:
                store = st.load_store()
                recent = load_recent_providers(st.recent_path())
                sorted_accs = sort_providers_by_recent(store.accounts, recent)
                account = select_provider_interactive(store.current or "", sorted_accs)
                if account is None:
                    print("switch cancelled")
                    return 0
            return switch_account(account, args.dry_run)

        if args.command == "add":
            target_acc = args.account or args.base_url
            return add_account(
                name=target_acc,
                from_current=args.from_current,
                from_dir=args.from_dir,
                from_file=None,
                dry_run=args.dry_run,
            )

        if args.command == "delete":
            return delete_account(args.provider, args.full, args.dry_run)

        if args.command == "rename":
            return rename_account(args.old_provider, args.new_provider, args.dry_run)

        if args.command == "auth":
            if args.auth_command == "detail":
                return auth_detail(args.provider)
            if args.auth_command == "edit":
                return auth_edit(args.provider)

        if args.command == "config":
            if args.config_command == "detail":
                return config_detail(args.provider)
            if args.config_command == "edit":
                return config_edit(args.provider)

        if args.command == "doctor":
            return doctor_command(args.fix)

        if args.command == "test":
            return dispatch_test(
                args.args,
                args.api_key_stdin,
                args.timeout,
                args.all,
                test_account,
                test_all_accounts,
                test_direct_url,
            )

        if args.command in ("ping", "p"):
            return dispatch_ping(
                args.provider,
                args.all,
                args.timeout,
                args.model,
                args.prompt,
                ping_account,
                ping_all_accounts,
            )

        return 0
    except SwitchError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"unexpected error: {e}", file=sys.stderr)
        return 1
