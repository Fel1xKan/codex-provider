from __future__ import annotations

import argparse
import sys

import lib.cursor.store as st
from lib.common.cli import (
    add_auth_parser,
    add_config_parser,
    add_doctor_parser,
    add_export_parser,
    add_import_parser,
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
from lib.cursor.admin import (
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
from lib.cursor.commands import (
    add_account,
    delete_account,
    print_list,
    print_status,
    rename_account,
    switch_account,
)
from lib.cursor.models import (
    model_list_command,
    model_set_command,
    models_sync_command,
)


def add_model_parser(subparsers: argparse._SubParsersAction) -> None:
    model_parser = subparsers.add_parser(
        "models", help="List or switch the Cursor model selection"
    )
    model_sub = model_parser.add_subparsers(dest="models_command", required=True)
    model_sub.add_parser("list", help="List the model catalog and current selection")
    set_parser = model_sub.add_parser("set", help="Set the model for all surfaces")
    set_parser.add_argument("model_id", help="Model id from the Cursor catalog")
    set_parser.add_argument(
        "--dry-run", action="store_true", help="Preview changes without writing files"
    )
    set_parser.add_argument(
        "--force",
        action="store_true",
        help="Write even when Cursor is running (may be overwritten)",
    )
    sync_parser = model_sub.add_parser(
        "sync",
        help="Fetch models from a custom provider and add them to Cursor",
    )
    sync_parser.add_argument("provider", nargs="?", help="Provider name")
    sync_parser.add_argument(
        "--api-key-stdin",
        action="store_true",
        help="Read the API key from standard input",
    )
    sync_parser.add_argument("--timeout", type=float, default=30.0)
    sync_parser.add_argument(
        "--dry-run", action="store_true", help="Preview changes without writing files"
    )
    sync_parser.add_argument(
        "--force",
        action="store_true",
        help="Write even when Cursor is running (may be overwritten)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cursor-provider",
        description="Switch account and model configuration for Cursor.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="List accounts from cursor-provider config")
    subparsers.add_parser("status", help="Show the current active account and status")

    add_model_parser(subparsers)

    from lib.cursor.providers import add_provider_parser

    add_provider_parser(subparsers)

    add_auth_parser(subparsers)
    add_config_parser(subparsers)
    add_doctor_parser(subparsers)
    add_switch_parser(subparsers, include_model=False)
    subparsers.choices["switch"].add_argument(
        "--force",
        action="store_true",
        help="Write even when Cursor is running (may be overwritten)",
    )

    add = subparsers.add_parser("add", help="Add an account from the current login")
    add.add_argument("account", nargs="?", help="Account name")
    add.add_argument("--from-current", action="store_true", help="Import active login")
    add.add_argument("--from-file", help="Import auth data from a JSON file")
    add.add_argument(
        "--dry-run", action="store_true", help="Preview changes without writing files"
    )

    delete = subparsers.add_parser("delete", help="Delete an account")
    delete.add_argument("provider", help="Account name to delete")
    delete.add_argument(
        "--full", action="store_true", help="Also clear auth data in Cursor"
    )
    delete.add_argument(
        "--dry-run", action="store_true", help="Preview changes without writing files"
    )
    delete.add_argument(
        "--force",
        action="store_true",
        help="Write even when Cursor is running (may be overwritten)",
    )

    rename = subparsers.add_parser("rename", help="Rename an account")
    rename.add_argument("old_provider", help="Existing account name")
    rename.add_argument("new_provider", help="New account name")
    rename.add_argument(
        "--dry-run", action="store_true", help="Preview changes without writing files"
    )

    add_test_parser(subparsers)
    add_ping_parser(subparsers, "cursor")
    add_export_parser(subparsers)
    add_import_parser(subparsers)

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

        if args.command == "models":
            if args.models_command == "list":
                return model_list_command()
            if args.models_command == "set":
                return model_set_command(args.model_id, args.dry_run, args.force)
            if args.models_command == "sync":
                return models_sync_command(
                    args.provider,
                    args.api_key_stdin,
                    args.timeout,
                    args.dry_run,
                    args.force,
                )

        if args.command == "provider":
            from lib.cursor.providers import dispatch_provider

            return dispatch_provider(args)

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
            return switch_account(account, args.dry_run, args.force)

        if args.command == "add":
            return add_account(
                name=args.account or "",
                from_current=args.from_current,
                from_file=args.from_file,
                dry_run=args.dry_run,
            )

        if args.command == "delete":
            return delete_account(args.provider, args.full, args.dry_run, args.force)

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

        if args.command == "export":
            import lib.cursor.transfer as transfer

            return transfer.export_command(args.file)

        if args.command == "import":
            import lib.cursor.transfer as transfer

            return transfer.import_command(args.file, args.dry_run)

        return 0
    except SwitchError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"unexpected error: {e}", file=sys.stderr)
        return 1
