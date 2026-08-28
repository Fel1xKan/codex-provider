from __future__ import annotations

import argparse
from typing import Any

import lib.cursor.admin as adm
import lib.cursor.commands as cmd
import lib.cursor.store as st
from lib.common.backend import BaseBackend
from lib.common.cli import generic_main
from lib.common.recent import (
    ensure_recent_providers,
    sort_providers_by_recent,
)
from lib.common.registry import (
    ArgSpec,
    CommandSpec,
    SubcommandSpec,
    build_parser_for,
)
from lib.cursor.models import (
    model_list_command,
    model_set_command,
    models_sync_command,
)
from lib.cursor.providers import dispatch_provider


def _handle_cursor_models(args: Any) -> int:
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
    return 0


class CursorBackend(BaseBackend):
    prog = "cupx"
    legacy_name = "cursor-provider"
    description = "Switch account and model configuration for Cursor."
    command_help = {
        "list": "List accounts from cupx config",
        "status": "Show the current active account and status",
        "add": "Add an account from the current login",
        "delete": "Delete an account",
        "rename": "Rename an account",
    }
    command_args = {
        "add": (
            ArgSpec(("account",), nargs="?", help="Account name"),
            ArgSpec(
                ("--from-current",),
                action="store_true",
                help="Import active login",
            ),
            ArgSpec(("--from-file",), help="Import auth data from a JSON file"),
            ArgSpec(
                ("--dry-run",),
                action="store_true",
                help="Preview changes without writing files",
            ),
        ),
        "delete": (
            ArgSpec(("provider",), help="Account name to delete"),
            ArgSpec(
                ("--full",),
                action="store_true",
                help="Also clear auth data in Cursor",
            ),
            ArgSpec(
                ("--dry-run",),
                action="store_true",
                help="Preview changes without writing files",
            ),
            ArgSpec(
                ("--force",),
                action="store_true",
                help="Write even when Cursor is running (may be overwritten)",
            ),
        ),
        "switch": (
            ArgSpec(
                ("provider",),
                nargs="?",
                help="Provider name; opens an interactive picker when omitted",
            ),
            ArgSpec(
                ("--dry-run",),
                action="store_true",
                help="Preview changes without writing files",
            ),
            ArgSpec(
                ("--force",),
                action="store_true",
                help="Write even when Cursor is running (may be overwritten)",
            ),
        ),
    }
    extra_commands = (
        CommandSpec(
            "models",
            handler="models",
            summary="List or switch the Cursor model selection",
            subcommands=(
                SubcommandSpec(
                    "list",
                    dest="models_command",
                    help="List the model catalog and current selection",
                ),
                SubcommandSpec(
                    "set",
                    dest="models_command",
                    help="Set the model for all surfaces",
                    args=(
                        ArgSpec(("model_id",), help="Model id from the Cursor catalog"),
                        ArgSpec(
                            ("--dry-run",),
                            action="store_true",
                            help="Preview changes without writing files",
                        ),
                        ArgSpec(
                            ("--force",),
                            action="store_true",
                            help=(
                                "Write even when Cursor is running (may be overwritten)"
                            ),
                        ),
                    ),
                ),
                SubcommandSpec(
                    "sync",
                    dest="models_command",
                    help=("Fetch models from a custom provider and add them to Cursor"),
                    args=(
                        ArgSpec(("provider",), nargs="?", help="Provider name"),
                        ArgSpec(
                            ("--api-key-stdin",),
                            action="store_true",
                            help="Read the API key from standard input",
                        ),
                        ArgSpec(("--timeout",), type=float, default=30.0),
                        ArgSpec(
                            ("--dry-run",),
                            action="store_true",
                            help="Preview changes without writing files",
                        ),
                        ArgSpec(
                            ("--force",),
                            action="store_true",
                            help=(
                                "Write even when Cursor is running (may be overwritten)"
                            ),
                        ),
                    ),
                ),
            ),
        ),
        CommandSpec(
            "provider",
            handler="provider",
            summary="Manage custom OpenAI-compatible providers",
            subcommands=(
                SubcommandSpec(
                    "list",
                    dest="provider_command",
                    help="List configured providers",
                ),
                SubcommandSpec(
                    "add",
                    dest="provider_command",
                    help="Add a custom provider",
                    args=(
                        ArgSpec(("name",), help="Provider name"),
                        ArgSpec(
                            ("--from-current",),
                            action="store_true",
                            help=(
                                "Capture the provider currently configured in Cursor"
                            ),
                        ),
                        ArgSpec(("--base-url",), help="OpenAI-compatible base URL"),
                        ArgSpec(
                            ("--api-key-stdin",),
                            action="store_true",
                            help=(
                                "Read API key from stdin instead of a hidden "
                                "interactive prompt"
                            ),
                        ),
                        ArgSpec(
                            ("--dry-run",),
                            action="store_true",
                            help="Preview changes without writing files",
                        ),
                    ),
                ),
                SubcommandSpec(
                    "switch",
                    dest="provider_command",
                    help="Switch the active provider",
                    args=(
                        ArgSpec(("name",), help="Provider name"),
                        ArgSpec(
                            ("--dry-run",),
                            action="store_true",
                            help="Preview changes without writing files",
                        ),
                        ArgSpec(
                            ("--force",),
                            action="store_true",
                            help=(
                                "Write even when Cursor is running (may be overwritten)"
                            ),
                        ),
                    ),
                ),
                SubcommandSpec(
                    "delete",
                    dest="provider_command",
                    help="Delete a provider",
                    args=(
                        ArgSpec(("name",), help="Provider name"),
                        ArgSpec(
                            ("--full",),
                            action="store_true",
                            help="Also clear the provider config in Cursor",
                        ),
                        ArgSpec(
                            ("--dry-run",),
                            action="store_true",
                            help="Preview changes without writing files",
                        ),
                        ArgSpec(
                            ("--force",),
                            action="store_true",
                            help=(
                                "Write even when Cursor is running (may be overwritten)"
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )
    extra_handlers = {
        "models": _handle_cursor_models,
        "provider": lambda args: dispatch_provider(args),
    }

    def recent_entries(self) -> list[str]:
        store = st.load_store()
        return sort_providers_by_recent(
            store.accounts, ensure_recent_providers(st.recent_path())
        )

    def current_entry(self) -> str | None:
        return st.load_store().current or None

    def list(self) -> int:
        return cmd.print_list()

    def status(self) -> int:
        return cmd.print_status()

    def switch(
        self, target: str, model: str | None, dry_run: bool, force: bool = False
    ) -> int:
        return cmd.switch_account(target, dry_run, force)

    def add(self, args: Any) -> int:
        return cmd.add_account(
            name=args.account or "",
            from_current=args.from_current,
            from_file=args.from_file,
            dry_run=args.dry_run,
        )

    def delete(
        self, provider: str, full: bool, dry_run: bool, force: bool = False
    ) -> int:
        return cmd.delete_account(provider, full, dry_run, force)

    def rename(self, old: str, new: str, dry_run: bool) -> int:
        return cmd.rename_account(old, new, dry_run)

    def auth_detail(self, provider: str | None) -> int:
        return adm.auth_detail(provider)

    def auth_edit(self, provider: str | None) -> int:
        return adm.auth_edit(provider)

    def config_detail(self, provider: str | None) -> int:
        return adm.config_detail(provider)

    def config_edit(self, provider: str | None) -> int:
        return adm.config_edit(provider)

    def doctor(self, fix: bool) -> int:
        return adm.doctor_command(fix)

    def test_provider(self, provider: str | None, timeout: float) -> int:
        return adm.test_account(provider, timeout)

    def test_all_providers(self, timeout: float) -> int:
        return adm.test_all_accounts(timeout)

    def test_direct(self, base_url: str, api_key: str, timeout: float) -> int:
        return adm.test_direct_url(base_url, api_key, timeout)

    def ping_provider(
        self,
        provider: str | None,
        timeout: float,
        model: str | None,
        prompt: str,
    ) -> int:
        return adm.ping_account(provider, timeout, model, prompt)

    def ping_all_providers(self, timeout: float, model: str | None, prompt: str) -> int:
        return adm.ping_all_accounts(timeout, model, prompt)

    def export(self, file_path: str | None) -> int:
        import lib.cursor.transfer as transfer

        return transfer.export_command(file_path)

    def import_(self, file_path: str | None, dry_run: bool) -> int:
        import lib.cursor.transfer as transfer

        return transfer.import_command(file_path, dry_run)


BACKEND = CursorBackend()


def build_parser() -> argparse.ArgumentParser:
    return build_parser_for(BACKEND)


def main(argv: list[str] | None = None) -> int:
    return generic_main(BACKEND, argv)
