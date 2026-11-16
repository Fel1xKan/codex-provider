"""System commands: status, doctor, test, migrate, import, export, upgrade."""

from __future__ import annotations

import argparse

from lib.xpx.commands.cmd_doctor import run_doctor
from lib.xpx.commands.cmd_import_export import run_export, run_import, run_migrate
from lib.xpx.commands.cmd_status import run_status
from lib.xpx.commands.cmd_test_ping import run_test
from lib.xpx.commands.cmd_upgrade import run_upgrade


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the system subcommands."""
    _status_doctor_test(subparsers)
    _migrate_import_export(subparsers)
    _upgrade(subparsers)


def _status_doctor_test(subparsers: argparse._SubParsersAction) -> None:
    """Register the status-doctor-test subcommand(s)."""
    p_status = subparsers.add_parser("status", help="Global dashboard of all clients")
    p_status.set_defaults(func=run_status)

    p_doc = subparsers.add_parser("doctor", help="System health check and repair")
    p_doc.add_argument(
        "--fix", action="store_true", help="Automatically repair detected issues"
    )
    p_doc.set_defaults(func=run_doctor)

    p_test = subparsers.add_parser(
        "test",
        help="Test provider reachability (add --deep for end-to-end client checks)",
        description=(
            "Probe provider connectivity. By default this performs one HTTP GET "
            "against each provider's /models endpoint, which only proves the "
            "credentials and network work. Pass --deep to additionally spawn "
            "each target client and send a real prompt, proving the whole "
            "client -> provider path works."
        ),
    )
    p_test.add_argument("provider", nargs="?", help="Provider name (shallow mode)")
    p_test.add_argument(
        "--deep",
        action="store_true",
        help="Also run a real prompt through target clients (slow, end-to-end)",
    )
    p_test.add_argument(
        "--target",
        help="Target client(s) for --deep, comma-separated (default: all installed)",
    )
    p_test.add_argument(
        "--model",
        help="Model to use for --deep (default: the provider's default model)",
    )
    p_test.add_argument(
        "--prompt", default="say hi", help="Prompt for --deep (default: 'say hi')"
    )
    p_test.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="Per-target timeout in seconds for --deep (default: 60)",
    )
    p_test.add_argument(
        "--all", action="store_true", help="Test all providers / all clients"
    )
    p_test.set_defaults(func=run_test)


def _migrate_import_export(subparsers: argparse._SubParsersAction) -> None:
    """Register the migrate-import-export subcommand(s)."""
    p_migrate = subparsers.add_parser(
        "migrate", help="Migrate legacy configurations from previous CLIs"
    )
    p_migrate.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview discovered legacy configurations without writing changes",
    )
    p_migrate.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Force overwrite existing providers, accounts, and target states",
    )
    p_migrate.set_defaults(func=run_migrate)

    p_import = subparsers.add_parser("import", help="Import provider configurations")
    p_import.add_argument(
        "file",
        nargs="?",
        help="Path to config file (auto-detects format). If omitted, runs migrate.",
    )
    p_import.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Force overwrite existing configurations",
    )
    p_import.set_defaults(func=run_import)

    p_export = subparsers.add_parser(
        "export", help="Export configurations to JSON backup"
    )
    p_export.add_argument("file", nargs="?", help="Destination backup file path")
    p_export.set_defaults(func=run_export)


def _upgrade(subparsers: argparse._SubParsersAction) -> None:
    """Register the upgrade subcommand(s)."""
    p_upgrade = subparsers.add_parser("upgrade", help="Self-upgrade xpx binary")
    p_upgrade.add_argument(
        "--check", action="store_true", help="Check for newer version"
    )
    p_upgrade.add_argument("--notes", action="store_true", help="Show release notes")
    p_upgrade.add_argument("--dry-run", action="store_true", help="Preview upgrade")
    p_upgrade.set_defaults(func=run_upgrade)
