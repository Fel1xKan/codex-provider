from __future__ import annotations

import argparse
import getpass
import sys
from collections.abc import Callable
from urllib.parse import urlparse

from codex_provider_lib.errors import SwitchError

ProviderTest = Callable[[str | None, float], int]
AllProvidersTest = Callable[[float], int]
DirectTest = Callable[[str, str, float], int]


def add_auth_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "auth", help="Inspect or edit provider authentication data"
    )
    commands = parser.add_subparsers(dest="auth_command", required=True)
    detail = commands.add_parser(
        "detail", help="Show auth metadata without printing credential values"
    )
    detail.add_argument(
        "provider", nargs="?", help="Provider name; defaults to the current scope"
    )
    edit = commands.add_parser(
        "edit", help="Open provider authentication data in $VISUAL or $EDITOR"
    )
    edit.add_argument(
        "provider", nargs="?", help="Provider name; defaults to the current scope"
    )


def add_config_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "config", help="Inspect or edit provider configuration"
    )
    commands = parser.add_subparsers(dest="config_command", required=True)
    detail = commands.add_parser("detail", help="Show a provider config block")
    detail.add_argument(
        "provider", nargs="?", help="Provider name; defaults to the current provider"
    )
    edit = commands.add_parser(
        "edit", help="Open provider configuration in $VISUAL or $EDITOR"
    )
    edit.add_argument(
        "provider",
        nargs="?",
        help="Provider name to validate; defaults to the current provider",
    )


def add_doctor_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "doctor", help="Validate provider configuration and authentication data"
    )
    parser.add_argument(
        "--fix", action="store_true", help="Apply supported automatic repairs"
    )


def add_switch_parser(
    subparsers: argparse._SubParsersAction, *, include_model: bool = False
) -> None:
    parser = subparsers.add_parser("switch", help="Switch the active provider")
    parser.add_argument(
        "provider",
        nargs="?",
        help="Provider name; opens an interactive picker when omitted",
    )
    if include_model:
        parser.add_argument(
            "-m", "--model", help="Model ID or provider/model; prompts when ambiguous"
        )
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview changes without writing files"
    )


def add_provider_parsers(subparsers: argparse._SubParsersAction) -> None:
    add = subparsers.add_parser("add", help="Add a provider config and auth entry")
    add.add_argument("base_url", help="Provider base_url")
    add.add_argument("legacy_api_key", nargs="?", help=argparse.SUPPRESS)
    add.add_argument(
        "--api-key-stdin",
        action="store_true",
        help="Read API key from stdin instead of a hidden interactive prompt",
    )
    add.add_argument(
        "--provider", help="Provider name; defaults to the base_url domain"
    )
    add.add_argument(
        "--name", dest="display_name", help="Display name stored in provider config"
    )
    add.add_argument(
        "--wire-api", default="responses", help="wire_api value, default: responses"
    )
    add.add_argument(
        "--supports-websockets",
        choices=["true", "false"],
        help="Set supports_websockets explicitly when supported by the backend",
    )
    add.add_argument(
        "--dry-run", action="store_true", help="Preview changes without writing files"
    )

    delete = subparsers.add_parser("delete", help="Delete a provider config")
    delete.add_argument("provider", help="Provider name to delete")
    delete.add_argument(
        "--full", action="store_true", help="Also remove provider authentication data"
    )
    delete.add_argument(
        "--dry-run", action="store_true", help="Preview changes without writing files"
    )

    rename = subparsers.add_parser("rename", help="Rename a provider")
    rename.add_argument("old_provider", help="Existing provider name")
    rename.add_argument("new_provider", help="New provider name")
    rename.add_argument(
        "--dry-run", action="store_true", help="Preview changes without writing files"
    )


def add_test_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "test", help="Test a provider or direct base_url with /models"
    )
    parser.add_argument(
        "args",
        nargs="*",
        metavar="provider|base_url",
        help="No args/current provider, provider name, or direct base_url",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Test every configured provider and print an availability summary",
    )
    parser.add_argument(
        "--api-key-stdin",
        action="store_true",
        help="Read API key from stdin for direct base_url tests",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="HTTP timeout in seconds, default: 30",
    )


def add_ping_parser(subparsers: argparse._SubParsersAction, program: str) -> None:
    parser = subparsers.add_parser(
        "ping",
        aliases=["p"],
        help=f"Test one provider with a minimal {program} command",
    )
    parser.add_argument(
        "provider", nargs="?", help="Provider name; defaults to current provider"
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help=f"{program} command timeout in seconds, default: 120",
    )
    parser.add_argument("-m", "--model", help="Override model for this ping")
    parser.add_argument(
        "--prompt", default="say hi", help='Prompt for the ping, default: "say hi"'
    )


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


def dispatch_test(
    args: list[str],
    api_key_stdin: bool,
    timeout: float,
    test_all: bool,
    test_provider: ProviderTest,
    test_all_providers: AllProvidersTest,
    test_direct: DirectTest,
) -> int:
    if test_all:
        if args:
            raise SwitchError("--all cannot be combined with a provider or base_url")
        if api_key_stdin:
            raise SwitchError("--all cannot be combined with --api-key-stdin")
        return test_all_providers(timeout)
    if not args:
        if api_key_stdin:
            raise SwitchError("--api-key-stdin requires a base_url")
        return test_provider(None, timeout)
    if len(args) == 1:
        target = args[0]
        parsed = urlparse(target)
        if parsed.scheme and parsed.hostname:
            return test_direct(target, read_api_key(api_key_stdin), timeout)
        if api_key_stdin:
            raise SwitchError("--api-key-stdin requires a direct base_url")
        return test_provider(target, timeout)
    raise SwitchError(
        "test accepts either [provider] or <base-url>; API keys must not be "
        "passed as command arguments"
    )
