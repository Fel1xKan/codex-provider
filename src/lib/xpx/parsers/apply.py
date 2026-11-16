"""Apply command: push provider credentials into native clients."""

from __future__ import annotations

import argparse

from lib.xpx.commands.cmd_apply import run_apply


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the apply subcommand."""
    p_apply = subparsers.add_parser(
        "apply", help="Apply provider or account configuration to target client(s)"
    )
    _core_arguments(p_apply)
    _codex_arguments(p_apply)
    p_apply.set_defaults(func=run_apply)


def _core_arguments(p_apply: argparse.ArgumentParser) -> None:
    """Positional target/provider spec plus the provider-agnostic flags."""
    p_apply.add_argument(
        "target", nargs="?", help="Target client(s), comma-separated (e.g. codex,pi)"
    )
    p_apply.add_argument(
        "provider_spec",
        nargs="?",
        help="Provider spec (e.g. deepseek, deepseek/reasoner, or :chat)",
    )
    p_apply.add_argument(
        "model_arg",
        nargs="?",
        help="Optional model override when provider is specified separately",
    )
    p_apply.add_argument(
        "--all", action="store_true", help="Apply to all detected target clients"
    )
    p_apply.add_argument("--account", help="Apply named OAuth account")
    p_apply.add_argument("--model", help="Explicit model override")
    p_apply.add_argument(
        "--clear", action="store_true", help="Reset client to official default state"
    )
    p_apply.add_argument(
        "--dry-run", action="store_true", help="Preview configuration changes"
    )
    p_apply.add_argument(
        "--no-save",
        action="store_true",
        help="Do not persist ad-hoc options to profile",
    )
    p_apply.add_argument(
        "--header", action="append", help="Target header override (key=value)"
    )


def _codex_arguments(p_apply: argparse.ArgumentParser) -> None:
    """Flags that only the Codex adapter consumes."""
    p_apply.add_argument(
        "--fast",
        action="store_true",
        default=None,
        help="Enable fast mode (Codex only)",
    )
    p_apply.add_argument(
        "--no-fast",
        action="store_false",
        dest="fast",
        help="Disable fast mode (Codex only)",
    )
    p_apply.add_argument(
        "--wire-api",
        choices=["chat", "responses"],
        help="Codex wire API (Codex only)",
    )
    p_apply.add_argument(
        "--web-search",
        nargs="?",
        const="true",
        default=None,
        help="Enable or set Codex web search (Codex only)",
    )
    p_apply.add_argument(
        "--no-web-search",
        action="store_false",
        dest="web_search",
        help="Disable Codex web search (Codex only)",
    )
    p_apply.add_argument(
        "--restart-daemon",
        action="store_true",
        dest="restart_daemon",
        default=None,
        help="Force restart background daemon even if active sessions exist",
    )
    p_apply.add_argument(
        "--no-restart-daemon",
        action="store_false",
        dest="restart_daemon",
        help="Do not restart or reload background daemons",
    )
