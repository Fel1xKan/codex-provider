from __future__ import annotations

import getpass
import sys
from typing import Any
from urllib.parse import urlparse

from lib.common.errors import SwitchError
from lib.common.platform import select_provider_interactive
from lib.common.registry import COMMON_COMMANDS, build_parser_for


def read_api_key(api_key_stdin: bool, prompt: str = "API key: ") -> str:
    if api_key_stdin:
        api_key = sys.stdin.readline().strip()
    elif sys.stdin.isatty():
        api_key = getpass.getpass(prompt).strip()
    else:
        raise SwitchError("API key input requires a TTY or --api-key-stdin")
    if not api_key:
        raise SwitchError("api_key must not be empty")
    return api_key


def dispatch_test(backend: Any, args: Any) -> int:
    if args.all:
        if args.args:
            raise SwitchError("--all cannot be combined with a provider or base_url")
        if args.api_key_stdin:
            raise SwitchError("--all cannot be combined with --api-key-stdin")
        return backend.test_all_providers(args.timeout)
    if not args.args:
        if args.api_key_stdin:
            raise SwitchError("--api-key-stdin requires a base_url")
        return backend.test_provider(None, args.timeout)
    if len(args.args) == 1:
        target = args.args[0]
        parsed = urlparse(target)
        if parsed.scheme and parsed.hostname:
            return backend.test_direct(
                target, read_api_key(args.api_key_stdin), args.timeout
            )
        if args.api_key_stdin:
            raise SwitchError("--api-key-stdin requires a direct base_url")
        return backend.test_provider(target, args.timeout)
    raise SwitchError(
        "test accepts either [provider] or <base-url>; API keys must not be "
        "passed as command arguments"
    )


def dispatch_ping(backend: Any, args: Any) -> int:
    if args.all:
        if args.provider is not None:
            raise SwitchError("--all cannot be combined with a provider")
        return backend.ping_all_providers(args.timeout, args.model, args.prompt)
    return backend.ping_provider(args.provider, args.timeout, args.model, args.prompt)


def handle_switch(backend: Any, args: Any) -> int:
    target = args.provider
    if target is None:
        recent = backend.recent_entries()
        target = select_provider_interactive(backend.current_entry() or "", recent)
        if target is None:
            print("switch cancelled")
            return 0
    return backend.switch(
        target,
        getattr(args, "model", None),
        args.dry_run,
        getattr(args, "force", False),
    )


def _handle_list(backend: Any, args: Any) -> int:
    return backend.list()


def _handle_status(backend: Any, args: Any) -> int:
    return backend.status()


def _handle_switch_cmd(backend: Any, args: Any) -> int:
    return handle_switch(backend, args)


def _handle_add(backend: Any, args: Any) -> int:
    return backend.add(args)


def _handle_delete(backend: Any, args: Any) -> int:
    return backend.delete(
        args.provider,
        args.full,
        args.dry_run,
        getattr(args, "force", False),
    )


def _handle_rename(backend: Any, args: Any) -> int:
    return backend.rename(args.old_provider, args.new_provider, args.dry_run)


def _handle_auth(backend: Any, args: Any) -> int:
    return _dispatch_subcommand(backend, "auth", args)


def _handle_config(backend: Any, args: Any) -> int:
    return _dispatch_subcommand(backend, "config", args)


def _dispatch_subcommand(backend: Any, command_name: str, args: Any) -> int:
    spec = next((item for item in COMMON_COMMANDS if item.name == command_name), None)
    if spec is None or not spec.subcommands:
        return 0
    subcommands = backend.command_subcommands.get(command_name, spec.subcommands)
    value = getattr(args, spec.subcommands[0].dest, None)
    for sub in subcommands:
        if sub.name == value:
            handler = getattr(backend, sub.handler)
            return handler(args) if sub.pass_args else handler(args.provider)
    return 0


def _handle_doctor(backend: Any, args: Any) -> int:
    return backend.doctor(args.fix)


def _handle_test(backend: Any, args: Any) -> int:
    return dispatch_test(backend, args)


def _handle_ping(backend: Any, args: Any) -> int:
    return dispatch_ping(backend, args)


def _handle_export(backend: Any, args: Any) -> int:
    return backend.export(args.file)


def _handle_import(backend: Any, args: Any) -> int:
    return backend.import_(args.file, args.dry_run)


def _handle_upgrade(backend: Any, args: Any) -> int:
    return backend.upgrade(args.check, args.dry_run)


HANDLERS: dict[str, Any] = {
    "list": _handle_list,
    "status": _handle_status,
    "switch": _handle_switch_cmd,
    "add": _handle_add,
    "delete": _handle_delete,
    "rename": _handle_rename,
    "auth": _handle_auth,
    "config": _handle_config,
    "doctor": _handle_doctor,
    "test": _handle_test,
    "ping": _handle_ping,
    "export": _handle_export,
    "import": _handle_import,
    "upgrade": _handle_upgrade,
}


def generic_main(backend: Any, argv: list[str] | None = None) -> int:
    parser = build_parser_for(backend)
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1

    try:
        handler = HANDLERS.get(args.command)
        if handler is not None:
            return handler(backend, args)
        extra = backend.extra_handlers
        if args.command in extra:
            return extra[args.command](args)
        return 0
    except SwitchError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"unexpected error: {e}", file=sys.stderr)
        return 1
