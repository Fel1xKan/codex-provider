"""Account commands: login, snapshot, list, usage."""

from __future__ import annotations

import argparse

from lib.xpx.commands.cmd_account import (
    run_account_list,
    run_account_login,
    run_account_snapshot,
    run_account_usage,
)


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the accounts subcommands."""
    p_acc = subparsers.add_parser("account", help="OAuth/Session account management")
    acc_sub = p_acc.add_subparsers(dest="account_action", metavar="<action>")

    p_acc_login = acc_sub.add_parser("login", help="OAuth interactive login")
    p_acc_login.add_argument("target", help="Target client (e.g. agy)")
    p_acc_login.add_argument("name", nargs="?", help="Account alias")
    p_acc_login.set_defaults(func=run_account_login)

    p_acc_snap = acc_sub.add_parser(
        "snapshot", help="Snapshot existing login credentials"
    )
    p_acc_snap.add_argument("target", help="Target client (e.g. codex, cursor, agy)")
    p_acc_snap.add_argument("name", help="Account alias")
    p_acc_snap.set_defaults(func=run_account_snapshot)

    p_acc_list = acc_sub.add_parser("list", help="List saved accounts")
    p_acc_list.set_defaults(func=run_account_list)

    p_acc_usage = acc_sub.add_parser("usage", help="Check quota and usage")
    p_acc_usage.add_argument("target", nargs="?", default="agy", help="Target client")
    p_acc_usage.add_argument("name", nargs="?", help="Account alias")
    p_acc_usage.set_defaults(func=run_account_usage)
