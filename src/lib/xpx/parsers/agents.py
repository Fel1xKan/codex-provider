"""Agent CLI management and the interactive wizard shortcut."""

from __future__ import annotations

import argparse

from lib.xpx.commands.cmd_agent import (
    run_agent_install,
    run_agent_list,
    run_agent_update,
)


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the agents subcommands."""
    p_agent = subparsers.add_parser(
        "agent", help="Manage target agent CLIs (list, install, update)"
    )
    agent_sub = p_agent.add_subparsers(dest="agent_action", metavar="<action>")

    p_agent_list = agent_sub.add_parser(
        "list", help="List supported agent CLIs, versions, and installation status"
    )
    p_agent_list.set_defaults(func=run_agent_list)

    p_agent_install = agent_sub.add_parser(
        "install", help="Install target agent CLI(s)"
    )
    p_agent_install.add_argument(
        "target",
        nargs="?",
        help="Target agent name(s), comma-separated (e.g. claude, codex,agy)",
    )
    p_agent_install.add_argument(
        "--all", action="store_true", help="Install all missing agent CLIs"
    )
    p_agent_install.add_argument(
        "--dry-run", action="store_true", help="Preview install command"
    )
    p_agent_install.add_argument(
        "--force", action="store_true", help="Reinstall even if already installed"
    )
    p_agent_install.set_defaults(func=run_agent_install)

    p_agent_update = agent_sub.add_parser("update", help="Update target agent CLI(s)")
    p_agent_update.add_argument(
        "target",
        nargs="?",
        help="Target agent name(s), comma-separated (e.g. claude, codex,agy)",
    )
    p_agent_update.add_argument(
        "--all", action="store_true", help="Update all installed agent CLIs"
    )
    p_agent_update.add_argument(
        "--dry-run", action="store_true", help="Preview update command"
    )
    p_agent_update.set_defaults(func=run_agent_update)

    p_agent.set_defaults(func=run_agent_list)

    # Top-level convenience shortcuts
    p_interactive = subparsers.add_parser(
        "interactive",
        aliases=["i", "menu"],
        help="Interactive control plane wizard",
    )
    p_interactive.set_defaults(
        func=lambda _args: __import__(
            "lib.xpx.interactive.wizards", fromlist=["run_interactive_main"]
        ).run_interactive_main()
    )
