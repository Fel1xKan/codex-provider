"""Provider asset commands: add, list, show, set, delete."""

from __future__ import annotations

import argparse

from lib.xpx.commands.cmd_provider import run_add, run_delete, run_list
from lib.xpx.commands.cmd_set import run_set, run_show


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the providers subcommands."""
    _add_list_show_delete(subparsers)
    _set(subparsers)


def _add_list_show_delete(subparsers: argparse._SubParsersAction) -> None:
    """Register the add-list-show-delete subcommand(s)."""
    p_add = subparsers.add_parser("add", help="Add a new API provider")
    p_add.add_argument("name", help="Provider identifier (e.g. deepseek)")
    p_add.add_argument("base_url", nargs="?", help="API base URL")
    p_add.add_argument("--key", help="API key string")
    p_add.add_argument(
        "--key-stdin", action="store_true", help="Read API key from stdin"
    )
    p_add.add_argument("--default-model", help="Default primary model")
    p_add.add_argument(
        "--protocol",
        default="openai",
        choices=["openai", "anthropic"],
        help="Protocol type",
    )
    p_add.set_defaults(func=run_add)

    p_list = subparsers.add_parser("list", help="List all configured providers")
    p_list.add_argument("--json", action="store_true", help="Output as JSON")
    p_list.set_defaults(func=run_list)

    p_show = subparsers.add_parser(
        "show",
        help="Show provider configuration (all providers when no name given)",
        description=(
            "Read a provider's effective configuration, including masked "
            "credentials, target overrides, and where it is currently active. "
            "Replaces the former 'auth show' and 'config show'."
        ),
    )
    p_show.add_argument("name", nargs="?", help="Provider name")
    p_show.add_argument("--target", help="Show only this target's overrides")
    p_show.add_argument(
        "--reveal-key",
        action="store_true",
        help="Print the API key instead of a masked summary",
    )
    p_show.set_defaults(func=run_show)

    p_delete = subparsers.add_parser("delete", help="Delete a provider")
    p_delete.add_argument("name", help="Provider name")
    p_delete.add_argument(
        "--full", action="store_true", help="Also clear provider from active clients"
    )
    p_delete.add_argument(
        "--dry-run", action="store_true", help="Preview deletion without executing"
    )
    p_delete.set_defaults(func=run_delete)


def _set(subparsers: argparse._SubParsersAction) -> None:
    """Register the set subcommand(s)."""
    p_set = subparsers.add_parser(
        "set",
        help="Create a provider or update any of its fields",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Single write surface for a provider.\n\n"
            "  xpx set <provider> [options]          edit the provider itself\n"
            "  xpx set <provider> <target> [options] edit that client's overrides\n\n"
            "Universal fields (base URL, protocol, default model, API key, "
            "headers, name) apply to the provider; target overrides (fast mode, "
            "wire API, web search, per-client headers, options) apply only when "
            "that client uses the provider. Replaces the former 'rename', "
            "'auth set', and 'config set'. Sending an option a target cannot "
            "honor is an error rather than a silent no-op."
        ),
    )
    p_set.add_argument("name", help="Provider name (created when it does not exist)")
    p_set.add_argument(
        "target",
        nargs="?",
        help=(
            "Target client whose overrides to update (omit to edit the provider itself)"
        ),
    )
    p_set.add_argument("--base-url", help="API base URL")
    p_set.add_argument(
        "--protocol", choices=["openai", "anthropic"], help="Protocol type"
    )
    p_set.add_argument("--default-model", help="Default primary model")
    p_set.add_argument("--key", help="API key string")
    p_set.add_argument(
        "--key-stdin", action="store_true", help="Read the API key from stdin"
    )
    p_set.add_argument(
        "--header",
        action="append",
        help="Header (key=value); pass key= to remove",
    )
    p_set.add_argument(
        "--fast", action="store_true", default=None, help="Enable fast mode (Codex)"
    )
    p_set.add_argument(
        "--no-fast", action="store_false", dest="fast", help="Disable fast mode"
    )
    p_set.add_argument(
        "--wire-api", choices=["chat", "responses"], help="Codex wire API"
    )
    p_set.add_argument(
        "--web-search",
        nargs="?",
        const="true",
        default=None,
        help="Codex web search (true/false) (Codex only)",
    )
    p_set.add_argument(
        "--no-web-search",
        action="store_false",
        dest="web_search",
        help="Disable Codex web search (Codex only)",
    )
    p_set.add_argument(
        "--option",
        action="append",
        help="Generic target option (key=value)",
    )
    p_set.add_argument(
        "--name", dest="rename_to", help="Rename the provider to this name"
    )
    p_set.set_defaults(func=run_set)
