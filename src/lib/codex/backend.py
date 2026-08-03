from __future__ import annotations

import argparse
import sys
from typing import Any

import lib.codex.admin as adm
import lib.codex.edit as edit
import lib.codex.store as st
from lib.codex.doctor import (
    doctor,
)
from lib.codex.doctor import (
    run_codex_ping as default_run_codex_ping,
)
from lib.codex.switch import switch_provider
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


def get_run_codex_ping() -> Any:
    mod = sys.modules.get("cli.codex_provider") or sys.modules.get("codex_provider")
    if mod and hasattr(mod, "run_codex_ping"):
        return mod.run_codex_ping
    return default_run_codex_ping


def read_api_key(api_key_stdin: bool, prompt: str = "API key: ") -> str:
    mod = sys.modules.get("cli.codex_provider") or sys.modules.get("codex_provider")
    if (
        mod
        and hasattr(mod, "read_api_key")
        and mod.read_api_key is not None
        and mod.read_api_key != read_api_key
    ):
        return mod.read_api_key(api_key_stdin)
    return read_common_api_key(api_key_stdin, prompt)


def ping_provider(
    provider: str | None, timeout: float, model: str | None, prompt: str
) -> int:
    ping_fn = get_run_codex_ping()
    if provider is None:
        state = st.load_provider_state()
        if not state.active_provider:
            raise SwitchError("no active provider; switch to a provider first")
        return ping_fn(state.active_provider, timeout, model, prompt)
    with adm.temporary_provider(provider):
        return ping_fn(provider, timeout, model, prompt)


def ping_all_providers(timeout: float, model: str | None, prompt: str) -> int:
    state = st.load_provider_state()
    if not state.providers:
        raise SwitchError("no providers configured")

    results: list[tuple[str, int]] = []
    for index, provider in enumerate(sorted(state.providers)):
        if index:
            print("")
        try:
            result = ping_provider(provider, timeout, model, prompt)
        except SwitchError as exc:
            print(f"current provider: {state.active_provider}")
            print(f"ping provider: {provider}")
            print("ping result: failed")
            print(f"error: {exc}")
            result = 1
        results.append((provider, result))

    available = sum(result == 0 for _, result in results)
    print("")
    print("provider ping summary:")
    for provider, result in results:
        print(f"- {provider}: {'ok' if result == 0 else 'failed'}")
    print(f"available: {available}/{len(results)}")
    return 0 if available == len(results) else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codex-provider",
        description="Switch the default provider in Codex global config.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="List providers from codex-provider config")
    subparsers.add_parser("status", help="Show current provider and configuration")

    add_auth_parser(subparsers)
    add_config_parser(subparsers)
    add_doctor_parser(subparsers)
    add_test_parser(subparsers)
    add_ping_parser(subparsers, "codex")
    add_switch_parser(subparsers, include_model=False)
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
            return adm.print_list()
        if args.command == "status":
            return adm.print_status()

        if args.command == "switch":
            provider = args.provider
            if provider is None:
                state = st.load_provider_state()
                recent = load_recent_providers(st.recent_path())
                sorted_provs = sort_providers_by_recent(state.providers, recent)
                provider = select_provider_interactive(
                    state.active_provider or "", sorted_provs
                )
                if provider is None:
                    print("switch cancelled")
                    return 0
            return switch_provider(provider, args.dry_run)

        if args.command == "add":
            if args.legacy_api_key is not None:
                raise SwitchError(
                    "add accepts either [provider] or <base-url>; API keys must not be "
                    "passed as a command argument"
                )
            api_key = read_api_key(args.api_key_stdin)
            supports_ws = (
                True
                if args.supports_websockets == "true"
                else False
                if args.supports_websockets == "false"
                else None
            )
            return edit.add_provider(
                args.provider,
                args.base_url,
                api_key,
                args.display_name,
                args.wire_api,
                supports_ws,
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
                return adm.show_provider_config(args.provider)
            if args.config_command == "edit":
                return adm.edit_provider_config(args.provider)

        if args.command == "doctor":
            return doctor(args.fix)

        if args.command == "test":
            return dispatch_test(
                args.args,
                args.api_key_stdin,
                args.timeout,
                args.all,
                adm.test_provider,
                adm.test_all_providers,
                adm.test_direct_base_url,
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
            import lib.codex.transfer as transfer

            return transfer.export_command(args.file)

        if args.command == "import":
            import lib.codex.transfer as transfer

            return transfer.import_command(args.file, args.dry_run)

        return 0
    except SwitchError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"unexpected error: {e}", file=sys.stderr)
        return 1
