from __future__ import annotations

import argparse

from lib.common.constants import VERSION
from lib.xpx.commands.cmd_account import (
    run_account_list,
    run_account_login,
    run_account_snapshot,
    run_account_usage,
)
from lib.xpx.commands.cmd_apply import run_apply
from lib.xpx.commands.cmd_auth import run_auth_set, run_auth_show
from lib.xpx.commands.cmd_config import run_config_set, run_config_show
from lib.xpx.commands.cmd_doctor import run_doctor
from lib.xpx.commands.cmd_import_export import run_export, run_import, run_migrate
from lib.xpx.commands.cmd_models import (
    run_models_list,
    run_models_set,
    run_models_sync,
)
from lib.xpx.commands.cmd_provider import (
    run_add,
    run_delete,
    run_list,
    run_rename,
    run_show,
)
from lib.xpx.commands.cmd_status import run_status
from lib.xpx.commands.cmd_test_ping import run_ping, run_test
from lib.xpx.commands.cmd_upgrade import run_upgrade


def build_parser(prog: str = "xpx") -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Unified AI Agent Provider Control Plane",
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"%(prog)s {VERSION}",
    )

    subparsers = parser.add_subparsers(dest="subcommand", metavar="<command>")

    # 1. Provider Assets
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

    p_show = subparsers.add_parser("show", help="Show provider details")
    p_show.add_argument("name", help="Provider name")
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

    p_rename = subparsers.add_parser("rename", help="Rename a provider")
    p_rename.add_argument("old", help="Current provider name")
    p_rename.add_argument("new", help="New provider name")
    p_rename.set_defaults(func=run_rename)

    # 2. Auth
    p_auth = subparsers.add_parser("auth", help="Manage provider credentials")
    auth_sub = p_auth.add_subparsers(dest="auth_action", metavar="<action>")

    p_auth_show = auth_sub.add_parser("show", help="Show API key summary")
    p_auth_show.add_argument("name", nargs="?", help="Provider name")
    p_auth_show.set_defaults(func=run_auth_show)

    p_auth_set = auth_sub.add_parser("set", help="Update provider API key")
    p_auth_set.add_argument("name", help="Provider name")
    p_auth_set.add_argument("--key", help="New API key string")
    p_auth_set.add_argument(
        "--key-stdin", action="store_true", help="Read new key from stdin"
    )
    p_auth_set.set_defaults(func=run_auth_set)

    # 3. Config
    p_config = subparsers.add_parser(
        "config", help="Manage universal and target options"
    )
    cfg_sub = p_config.add_subparsers(dest="config_action", metavar="<action>")

    p_cfg_show = cfg_sub.add_parser("show", help="Show configuration")
    p_cfg_show.add_argument("name", nargs="?", help="Provider name")
    p_cfg_show.add_argument("target", nargs="?", help="Target client name")
    p_cfg_show.set_defaults(func=run_config_show)

    p_cfg_set = cfg_sub.add_parser("set", help="Set configuration options")
    p_cfg_set.add_argument("name", help="Provider name")
    p_cfg_set.add_argument("target", nargs="?", help="Target client name (optional)")
    p_cfg_set.add_argument("--base-url", help="Universal base URL")
    p_cfg_set.add_argument("--default-model", help="Universal default model")
    p_cfg_set.add_argument(
        "--header", action="append", help="Target-specific header (key=value)"
    )
    p_cfg_set.add_argument(
        "--fast", action="store_true", default=None, help="Enable fast mode (Codex)"
    )
    p_cfg_set.add_argument(
        "--no-fast", action="store_false", dest="fast", help="Disable fast mode"
    )
    p_cfg_set.add_argument(
        "--wire-api", choices=["chat", "responses"], help="Codex wire API"
    )
    p_cfg_set.add_argument(
        "--web-search",
        nargs="?",
        const="true",
        default=None,
        help="Codex web search (true/false) (Codex only)",
    )
    p_cfg_set.add_argument(
        "--no-web-search",
        action="store_false",
        dest="web_search",
        help="Disable Codex web search (Codex only)",
    )
    p_cfg_set.add_argument(
        "--option", action="append", help="Generic option override (key=value)"
    )
    p_cfg_set.set_defaults(func=run_config_set)

    # 4. Models
    p_models = subparsers.add_parser(
        "models", help="Model capabilities and preferences"
    )
    mod_sub = p_models.add_subparsers(dest="models_action", metavar="<action>")

    p_mod_sync = mod_sub.add_parser("sync", help="Synchronize remote models")
    p_mod_sync.add_argument("provider", help="Provider name")
    p_mod_sync.add_argument(
        "--force",
        action="store_true",
        help="Force reset reasoning ladders to catalog default",
    )
    p_mod_sync.set_defaults(func=run_models_sync)

    p_mod_list = mod_sub.add_parser("list", help="List cached or remote models")
    p_mod_list.add_argument("provider", nargs="?", help="Provider name")
    p_mod_list.add_argument(
        "--remote", action="store_true", help="Fetch directly from remote endpoint"
    )
    p_mod_list.set_defaults(func=run_models_list)

    p_mod_set = mod_sub.add_parser("set", help="Update model preference")
    p_mod_set.add_argument("model", help="Model ID")
    p_mod_set.add_argument("provider", help="Provider name")
    p_mod_set.add_argument(
        "--default", action="store_true", help="Mark as provider default model"
    )
    p_mod_set.add_argument("--context", type=int, help="Context window limit")
    p_mod_set.add_argument("--max-output", type=int, help="Max output tokens limit")
    p_mod_set.add_argument("--effort", help="Default reasoning level")
    p_mod_set.set_defaults(func=run_models_set)

    # 5. Apply
    p_apply = subparsers.add_parser(
        "apply", help="Apply provider or account configuration to target client(s)"
    )
    p_apply.add_argument(
        "target", nargs="?", help="Target client(s), comma-separated (e.g. codex,pi)"
    )
    p_apply.add_argument(
        "provider_spec",
        nargs="?",
        help="Provider spec (e.g. deepseek, deepseek/reasoner, or :chat)",
    )
    p_apply.add_argument(
        "--all", action="store_true", help="Apply to all detected target clients"
    )
    p_apply.add_argument("--account", help="Apply named OAuth account")
    p_apply.add_argument("--model", help="Explicit model override")
    p_apply.add_argument(
        "--clear", action="store_true", help="Reset client to official default state"
    )
    p_apply.add_argument("--reset", action="store_true", help="Alias for --clear")
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
    p_apply.set_defaults(func=run_apply)

    # 6. Account
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

    # 7. Status, Doctor, Test, Ping, Import, Export, Upgrade
    p_status = subparsers.add_parser("status", help="Global dashboard of all clients")
    p_status.set_defaults(func=run_status)

    p_doc = subparsers.add_parser("doctor", help="System health check and repair")
    p_doc.add_argument(
        "--fix", action="store_true", help="Automatically repair detected issues"
    )
    p_doc.set_defaults(func=run_doctor)

    p_test = subparsers.add_parser("test", help="HTTP /models latency test")
    p_test.add_argument("provider", nargs="?", help="Provider name")
    p_test.add_argument("--all", action="store_true", help="Test all providers")
    p_test.set_defaults(func=run_test)

    p_ping = subparsers.add_parser(
        "ping", help="End-to-end prompt test across target clients"
    )
    p_ping.add_argument("target", nargs="?", help="Target client name")
    p_ping.add_argument("provider_spec", nargs="?", help="Optional provider spec")
    p_ping.add_argument(
        "--prompt", default="say hi", help="Prompt text (default: 'say hi')"
    )
    p_ping.add_argument("--timeout", type=int, default=60, help="Timeout in seconds")
    p_ping.add_argument(
        "--all", action="store_true", help="Concurrent parallel test across all clients"
    )
    p_ping.set_defaults(func=run_ping)

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

    p_upgrade = subparsers.add_parser("upgrade", help="Self-upgrade xpx binary")
    p_upgrade.add_argument(
        "--check", action="store_true", help="Check for newer version"
    )
    p_upgrade.add_argument("--notes", action="store_true", help="Show release notes")
    p_upgrade.add_argument("--dry-run", action="store_true", help="Preview upgrade")
    p_upgrade.set_defaults(func=run_upgrade)

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

    return parser
