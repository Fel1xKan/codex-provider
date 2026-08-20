from __future__ import annotations

import argparse
from typing import Any

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
from lib.agy.login import login_account
from lib.agy.usage import usage_command
from lib.common.backend import BaseBackend
from lib.common.cli import generic_main
from lib.common.recent import (
    ensure_recent_providers,
    sort_providers_by_recent,
)
from lib.common.registry import (
    ArgSpec,
    CommandSpec,
    build_parser_for,
)


class AgyBackend(BaseBackend):
    prog = "agy-provider"
    description = "Switch account configurations for Antigravity (agy) CLI."
    command_help = {
        "list": "List accounts from agy-provider config",
        "status": "Show the current active account and status",
        "add": "Add or import an account configuration",
        "delete": "Delete an account",
        "rename": "Rename an account",
    }
    command_args = {
        "add": (
            ArgSpec(("account",), nargs="?", help="Account name"),
            ArgSpec(("base_url",), nargs="?", hidden=True),
            ArgSpec(("legacy_api_key",), nargs="?", hidden=True),
            ArgSpec(
                ("--api-key-stdin",),
                action="store_true",
                help="Read token JSON from stdin instead of interactive prompt",
            ),
            ArgSpec(("--from-dir",), help="Import token from an account directory"),
            ArgSpec(
                ("--from-current",),
                action="store_true",
                help="Import active token",
            ),
            ArgSpec(
                ("--login",),
                action="store_true",
                help="Initiate interactive login session",
            ),
            ArgSpec(
                ("--dry-run",),
                action="store_true",
                help="Preview changes without writing files",
            ),
        ),
    }
    extra_commands = (
        CommandSpec(
            "usage",
            handler="usage",
            summary="Show Antigravity 5-hour and weekly quota remaining",
            args=(
                ArgSpec(
                    ("provider",),
                    nargs="?",
                    help="Account name (defaults to the current account)",
                ),
            ),
        ),
        CommandSpec(
            "login",
            handler="login",
            summary="Initiate interactive AGY login session and save as account",
            args=(
                ArgSpec(("account",), nargs="?", help="Account name to save as"),
                ArgSpec(
                    ("--dry-run",),
                    action="store_true",
                    help="Preview changes without writing files",
                ),
            ),
        ),
    )
    extra_handlers = {
        "usage": lambda args: usage_command(args.provider),
        "login": lambda args: login_account(args.account, args.dry_run),
    }

    def recent_entries(self) -> list[str]:
        store = st.load_store()
        return sort_providers_by_recent(
            store.accounts, ensure_recent_providers(st.recent_path())
        )

    def current_entry(self) -> str | None:
        return st.load_store().current or None

    def list(self) -> int:
        return print_list()

    def status(self) -> int:
        return print_status()

    def switch(self, target: str, model: str | None, dry_run: bool) -> int:
        return switch_account(target, dry_run)

    def add(self, args: Any) -> int:
        if getattr(args, "login", False):
            return login_account(args.account or args.base_url, args.dry_run)
        target_acc = args.account or args.base_url
        return add_account(
            name=target_acc,
            from_current=args.from_current,
            from_dir=args.from_dir,
            from_file=None,
            dry_run=args.dry_run,
        )

    def delete(self, provider: str, full: bool, dry_run: bool) -> int:
        return delete_account(provider, full, dry_run)

    def rename(self, old: str, new: str, dry_run: bool) -> int:
        return rename_account(old, new, dry_run)

    def auth_detail(self, provider: str | None) -> int:
        return auth_detail(provider)

    def auth_edit(self, provider: str | None) -> int:
        return auth_edit(provider)

    def config_detail(self, provider: str | None) -> int:
        return config_detail(provider)

    def config_edit(self, provider: str | None) -> int:
        return config_edit(provider)

    def doctor(self, fix: bool) -> int:
        return doctor_command(fix)

    def test_provider(self, provider: str | None, timeout: float) -> int:
        return test_account(provider, timeout)

    def test_all_providers(self, timeout: float) -> int:
        return test_all_accounts(timeout)

    def test_direct(self, base_url: str, api_key: str, timeout: float) -> int:
        return test_direct_url(base_url, timeout)

    def ping_provider(
        self,
        provider: str | None,
        timeout: float,
        model: str | None,
        prompt: str,
    ) -> int:
        return ping_account(provider, timeout, model, prompt)

    def ping_all_providers(self, timeout: float, model: str | None, prompt: str) -> int:
        return ping_all_accounts(timeout, model, prompt)

    def export(self, file_path: str | None) -> int:
        import lib.agy.transfer as transfer

        return transfer.export_command(file_path)

    def import_(self, file_path: str | None, dry_run: bool) -> int:
        import lib.agy.transfer as transfer

        return transfer.import_command(file_path, dry_run)


BACKEND = AgyBackend()


def build_parser() -> argparse.ArgumentParser:
    return build_parser_for(BACKEND)


def main(argv: list[str] | None = None) -> int:
    return generic_main(BACKEND, argv)
