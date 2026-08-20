from __future__ import annotations

import argparse
import sys
from typing import Any

import lib.opencode.admin as adm
import lib.opencode.commands as cmd
import lib.opencode.edit as edit
from lib.common.backend import BaseBackend
from lib.common.cli import (
    generic_main,
)
from lib.common.cli import (
    read_api_key as read_common_api_key,
)
from lib.common.errors import SwitchError
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
from lib.opencode.models import models_command
from lib.opencode.ping import (
    ping_all_providers,
    ping_provider,
)
from lib.opencode.store import (
    load_state,
    recent_path,
)


def read_api_key(api_key_stdin: bool, prompt: str = "API key: ") -> str:
    mod = sys.modules.get("cli.opencode_provider") or sys.modules.get(
        "opencode_provider"
    )
    if (
        mod
        and hasattr(mod, "read_api_key")
        and mod.read_api_key is not None
        and mod.read_api_key != read_api_key
    ):
        return mod.read_api_key(api_key_stdin)
    return read_common_api_key(api_key_stdin, prompt)


class OpenCodeBackend(BaseBackend):
    prog = "opencode-provider"
    description = "Switch the default provider in OpenCode global config."
    switch_include_model = True
    command_help = {
        "list": "List providers from OpenCode config",
        "status": "Show current provider and configuration",
    }
    extra_commands = (
        CommandSpec(
            "models",
            handler="models",
            summary="Manage provider models",
            subcommands=(
                SubcommandSpec(
                    "list",
                    dest="models_command",
                    help="List models for a provider",
                    args=(ArgSpec(("provider",), nargs="?", help="Provider name"),),
                ),
                SubcommandSpec(
                    "sync",
                    dest="models_command",
                    help="Sync models from provider API",
                    args=(
                        ArgSpec(("provider",), nargs="?", help="Provider name"),
                        ArgSpec(
                            ("--dry-run",),
                            action="store_true",
                            help="Perform a dry run",
                        ),
                        ArgSpec(
                            ("--all",),
                            action="store_true",
                            help="Sync models for every configured provider",
                        ),
                    ),
                ),
            ),
        ),
    )

    def recent_entries(self) -> list[str]:
        state = load_state()
        return sort_providers_by_recent(
            state.providers, ensure_recent_providers(recent_path())
        )

    def current_entry(self) -> str | None:
        return load_state().current_provider

    def list(self) -> int:
        return cmd.print_list()

    def status(self) -> int:
        return cmd.print_status()

    def switch(self, target: str, model: str | None, dry_run: bool) -> int:
        return cmd.switch_provider(target, model, dry_run)

    def add(self, args: Any) -> int:
        if args.legacy_api_key is not None:
            raise SwitchError(
                "add accepts either [provider] or <base-url>; API keys must not be "
                "passed as a command argument"
            )
        api_key = read_api_key(args.api_key_stdin)
        return edit.add_provider(
            args.base_url,
            api_key,
            args.provider,
            args.display_name,
            args.wire_api,
            args.dry_run,
        )

    def delete(self, provider: str, full: bool, dry_run: bool) -> int:
        return edit.delete_provider(provider, full, dry_run)

    def rename(self, old: str, new: str, dry_run: bool) -> int:
        return edit.rename_provider(old, new, dry_run)

    def auth_detail(self, provider: str | None) -> int:
        return adm.show_auth(provider)

    def auth_edit(self, provider: str | None) -> int:
        return adm.edit_auth(provider)

    def config_detail(self, provider: str | None) -> int:
        return adm.show_config(provider)

    def config_edit(self, provider: str | None) -> int:
        return adm.edit_config(provider)

    def doctor(self, fix: bool) -> int:
        return adm.doctor_command(fix)

    def test_provider(self, provider: str | None, timeout: float) -> int:
        return adm.test_provider(provider, timeout)

    def test_all_providers(self, timeout: float) -> int:
        return adm.test_all_providers(timeout)

    def test_direct(self, base_url: str, api_key: str, timeout: float) -> int:
        return adm.test_direct(base_url, api_key, timeout)

    def ping_provider(
        self,
        provider: str | None,
        timeout: float,
        model: str | None,
        prompt: str,
    ) -> int:
        return ping_provider(provider, timeout, model, prompt)

    def ping_all_providers(self, timeout: float, model: str | None, prompt: str) -> int:
        return ping_all_providers(timeout, model, prompt)

    def export(self, file_path: str | None) -> int:
        import lib.opencode.transfer as transfer

        return transfer.export_command(file_path)

    def import_(self, file_path: str | None, dry_run: bool) -> int:
        import lib.opencode.transfer as transfer

        return transfer.import_command(file_path, dry_run)

    def models(
        self,
        command: str,
        provider: str | None,
        dry_run: bool,
        all_providers: bool,
    ) -> int:
        return models_command(command, provider, dry_run, all_providers)


BACKEND = OpenCodeBackend()


def build_parser() -> argparse.ArgumentParser:
    return build_parser_for(BACKEND)


def main(argv: list[str] | None = None) -> int:
    return generic_main(BACKEND, argv)
