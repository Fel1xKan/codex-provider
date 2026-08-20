from __future__ import annotations

import argparse
import sys

import lib.opencode.admin as adm
import lib.opencode.commands as cmd
import lib.opencode.edit as edit
from lib.common.cli import (
    add_auth_parser,
    add_config_parser,
    add_doctor_parser,
    add_export_parser,
    add_import_parser,
    add_ping_parser,
    add_provider_parsers,
    add_switch_parser,
    add_test_parser,
    dispatch_ping,
    dispatch_test,
)
from lib.common.cli import (
    read_api_key as read_common_api_key,
)
from lib.common.constants import VERSION
from lib.common.errors import SwitchError
from lib.common.platform import select_provider_interactive
from lib.common.recent import (
    load_recent_providers,
    sort_providers_by_recent,
)
from lib.opencode.models import (
    add_models_parser,
    models_command,
)
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="opencode-provider",
        description="Switch the default provider in OpenCode global config.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="List providers from OpenCode config")
    subparsers.add_parser("status", help="Show current provider and configuration")

    add_auth_parser(subparsers)
    add_config_parser(subparsers)
    add_doctor_parser(subparsers)
    add_models_parser(subparsers)
    add_test_parser(subparsers)
    add_ping_parser(subparsers, "opencode")
    add_switch_parser(subparsers, include_model=True)
    add_provider_parsers(subparsers)
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
            return cmd.print_list()
        if args.command == "status":
            return cmd.print_status()

        if args.command == "switch":
            provider = args.provider
            if provider is None:
                state = load_state()
                recent = load_recent_providers(recent_path())
                sorted_provs = sort_providers_by_recent(state.providers, recent)
                provider = select_provider_interactive(
                    state.current_provider or "", sorted_provs
                )
                if provider is None:
                    print("switch cancelled")
                    return 0
            return cmd.switch_provider(provider, args.model, args.dry_run)

        if args.command == "add":
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

        if args.command == "delete":
            return edit.delete_provider(args.provider, args.full, args.dry_run)

        if args.command == "rename":
            return edit.rename_provider(
                args.old_provider, args.new_provider, args.dry_run
            )

        if args.command == "auth":
            if args.auth_command == "detail":
                return adm.show_auth(args.provider)
            if args.auth_command == "edit":
                return adm.edit_auth(args.provider)

        if args.command == "config":
            if args.config_command == "detail":
                return adm.show_config(args.provider)
            if args.config_command == "edit":
                return adm.edit_config(args.provider)

        if args.command == "doctor":
            return adm.doctor_command(args.fix)

        if args.command == "models":
            return models_command(
                args.models_command,
                args.provider,
                getattr(args, "dry_run", False),
                getattr(args, "all", False),
            )

        if args.command == "test":
            return dispatch_test(
                args.args,
                args.api_key_stdin,
                args.timeout,
                args.all,
                adm.test_provider,
                adm.test_all_providers,
                adm.test_direct,
            )

        if args.command in ("ping", "p"):
            return dispatch_ping(
                args.provider,
                args.all,
                args.timeout,
                args.model,
                args.prompt,
                ping_provider,
                ping_all_providers,
            )

        if args.command == "export":
            import lib.opencode.transfer as transfer

            return transfer.export_command(args.file)

        if args.command == "import":
            import lib.opencode.transfer as transfer

            return transfer.import_command(args.file, args.dry_run)

        return 0
    except SwitchError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"unexpected error: {e}", file=sys.stderr)
        return 1
