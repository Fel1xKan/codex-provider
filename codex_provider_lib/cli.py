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
