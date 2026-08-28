from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import lib.claude.admin as adm
import lib.claude.edit as edit
import lib.claude.ping as ping
import lib.claude.store as st
from lib.claude.doctor import doctor
from lib.claude.models import models_command
from lib.claude.switch import switch_provider
from lib.common.backend import BaseBackend, TestTarget
from lib.common.cli import generic_main
from lib.common.cli import read_api_key as read_common_api_key
from lib.common.errors import SwitchError
from lib.common.recent import (
    ensure_recent_providers,
    sort_providers_by_recent,
)
from lib.common.registry import (
    ArgSpec,
    CommandSpec,
    SubcommandSpec,
    build_parser_for,
)


def read_api_key(api_key_stdin: bool, prompt: str = "API key: ") -> str:
    mod = sys.modules.get("cli.claude_provider") or sys.modules.get("claude_provider")
    if (
        mod
        and hasattr(mod, "read_api_key")
        and mod.read_api_key is not None
        and mod.read_api_key != read_api_key
    ):
        return mod.read_api_key(api_key_stdin)
    return read_common_api_key(api_key_stdin, prompt)


class ClaudeBackend(BaseBackend):
    prog = "clpx"
    legacy_name = "claude-provider"
    description = "Switch the default provider in Claude global settings."
    command_help = {
        "list": "List providers from clpx config",
        "status": "Show current provider and configuration",
    }
    command_args = {
        "add": (
            ArgSpec(
                ("base_url",),
                nargs="?",
                help="Provider base_url; omitted with --from-settings",
            ),
            ArgSpec(("legacy_api_key",), nargs="?", hidden=True),
            ArgSpec(
                ("--api-key-stdin",),
                action="store_true",
                help="Read API key from stdin instead of a hidden interactive prompt",
            ),
            ArgSpec(
                ("--provider",),
                help="Provider name; defaults to the base_url domain",
            ),
            ArgSpec(
                ("--name",),
                dest="display_name",
                help="Display name stored in provider config",
            ),
            ArgSpec(("--model",), help="Default model for this provider"),
            ArgSpec(
                ("--from-settings",),
                action="store_true",
                help=(
                    "Snapshot ANTHROPIC_* env and modelOverrides from the "
                    "current settings.json into this provider"
                ),
            ),
            ArgSpec(
                ("--env",),
                action="append",
                metavar="KEY=VALUE",
                help="Extra env variable for this provider; repeatable",
            ),
            ArgSpec(
                ("--dry-run",),
                action="store_true",
                help="Preview changes without writing files",
            ),
        ),
    }
    command_subcommands = {
        "config": (
            SubcommandSpec(
                "show",
                dest="config_command",
                handler="config_detail",
                help="Show a provider config block",
                args=(ArgSpec(("provider",), nargs="?", help="Provider name"),),
            ),
            SubcommandSpec(
                "edit",
                dest="config_command",
                handler="config_edit",
                help="Open the tool provider config in an editor",
                args=(ArgSpec(("provider",), nargs="?", help="Provider name"),),
            ),
            SubcommandSpec(
                "set",
                dest="config_command",
                handler="config_set",
                help="Set provider options without opening an editor",
                pass_args=True,
                args=(
                    ArgSpec(
                        ("provider",),
                        nargs="?",
                        help="Provider name; defaults to the current provider",
                    ),
                    ArgSpec(
                        ("--name",),
                        dest="display_name",
                        help="Display name stored in provider config",
                    ),
                    ArgSpec(
                        ("--model",),
                        help="Default model for this provider",
                    ),
                    ArgSpec(
                        ("--models-url",),
                        help=(
                            "Model list endpoint for `test`; defaults to "
                            "base_url + /models"
                        ),
                    ),
                    ArgSpec(
                        ("--dry-run",),
                        action="store_true",
                        help="Preview changes without writing files",
                    ),
                ),
            ),
        ),
    }
    extra_commands = (
        CommandSpec(
            "models",
            handler="models",
            summary="Manage provider models",
            subcommands=(
                SubcommandSpec(
                    "list",
                    dest="models_command",
                    help="List models synced for a provider",
                    args=(
                        ArgSpec(("provider",), nargs="?", help="Provider name"),
                        ArgSpec(
                            ("--remote",),
                            action="store_true",
                            help="Fetch models live from the provider API",
                        ),
                    ),
                ),
                SubcommandSpec(
                    "sync",
                    dest="models_command",
                    help="Sync models from provider API into ~/.claude-provider",
                    args=(
                        ArgSpec(("provider",), nargs="?", help="Provider name"),
                        ArgSpec(
                            ("--dry-run",),
                            action="store_true",
                            help="Preview changes without writing files",
                        ),
                        ArgSpec(
                            ("--all",),
                            action="store_true",
                            help="Sync models for every configured provider",
                        ),
                    ),
                ),
                SubcommandSpec(
                    "set",
                    dest="models_command",
                    help="Set the default model for a provider",
                    args=(
                        ArgSpec(("model",), help="Model ID"),
                        ArgSpec(("provider",), nargs="?", help="Provider name"),
                        ArgSpec(
                            ("--dry-run",),
                            action="store_true",
                            help="Preview changes without writing files",
                        ),
                    ),
                ),
            ),
        ),
    )
    extra_handlers = {
        "models": lambda args: models_command(
            args.models_command,
            args.provider,
            getattr(args, "model", None),
            getattr(args, "dry_run", False),
            getattr(args, "all", False),
            getattr(args, "remote", False),
        ),
    }

    def recent_entries(self) -> list[str]:
        state = st.ensure_provider_state(read_only=True)
        return sort_providers_by_recent(
            state.providers, ensure_recent_providers(st.recent_path())
        )

    def current_entry(self) -> str | None:
        return st.ensure_provider_state(read_only=True).active_provider or None

    def list(self) -> int:
        return adm.print_list()

    def status(self) -> int:
        return adm.print_status()

    def switch(
        self, target: str, model: str | None, dry_run: bool, force: bool = False
    ) -> int:
        return switch_provider(target, dry_run)

    def add(self, args: Any) -> int:
        if args.legacy_api_key is not None:
            raise SwitchError(
                "add accepts either [provider] or <base-url>; API keys must not be "
                "passed as a command argument"
            )
        api_key = (
            ""
            if getattr(args, "from_settings", False)
            else read_api_key(args.api_key_stdin)
        )
        return edit.add_provider(
            args.provider,
            args.base_url,
            api_key,
            args.display_name,
            args.model,
            args.dry_run,
            getattr(args, "from_settings", False),
            getattr(args, "env", None),
        )

    def delete(
        self, provider: str, full: bool, dry_run: bool, force: bool = False
    ) -> int:
        return edit.delete_provider(provider, full, dry_run)

    def rename(self, old: str, new: str, dry_run: bool) -> int:
        return edit.rename_provider(old, new, dry_run)

    def auth_detail(self, provider: str | None) -> int:
        return adm.show_auth(provider)

    def auth_edit(self, provider: str | None) -> int:
        return adm.edit_auth(provider)

    def config_detail(self, provider: str | None) -> int:
        return adm.show_provider_config(provider)

    def config_edit(self, provider: str | None) -> int:
        return adm.edit_provider_config(provider)

    def config_set(self, args: Any) -> int:
        return edit.set_provider_options(
            args.provider,
            args.display_name,
            args.model,
            args.dry_run,
            getattr(args, "models_url", None),
        )

    def doctor(self, fix: bool) -> int:
        return doctor(fix)

    def test_provider(self, provider: str | None, timeout: float) -> int:
        return adm.test_provider(provider, timeout)

    def test_targets(self) -> list[TestTarget]:
        state = st.ensure_provider_state(read_only=True)
        if not state.providers:
            raise SwitchError("no providers configured")
        targets: list[TestTarget] = []
        for provider in sorted(state.providers):
            config = state.providers[provider]
            base_url = config.get("base_url", "")
            profile = st.auth_profile_path(provider, create=False)
            if not profile.exists():
                targets.append(
                    TestTarget(
                        provider,
                        base_url,
                        "",
                        anthropic=True,
                        error=(
                            "auth profile is missing for provider "
                            f"'{provider}': {profile}"
                        ),
                    )
                )
                continue
            try:
                payload = json.loads(profile.read_text(encoding="utf-8"))
                api_key = payload.get("ANTHROPIC_AUTH_TOKEN") or payload.get(
                    "ANTHROPIC_API_KEY", ""
                )
            except Exception as exc:
                targets.append(
                    TestTarget(provider, base_url, "", anthropic=True, error=str(exc))
                )
                continue
            targets.append(TestTarget(provider, base_url, api_key, anthropic=True))
        return targets

    def run_models_test(self, target: TestTarget, timeout: float) -> int:
        state = st.ensure_provider_state(read_only=True)
        config = state.providers.get(target.name, {})
        return adm.get_run_models_test()(
            target.name,
            target.base_url,
            target.api_key,
            timeout,
            state.active_provider,
            anthropic=target.anthropic,
            models_url_override=config.get("models_url") or None,
        )

    def test_direct(self, base_url: str, api_key: str, timeout: float) -> int:
        return adm.test_direct_base_url(base_url, api_key, timeout)

    def ping_provider(
        self,
        provider: str | None,
        timeout: float,
        model: str | None,
        prompt: str,
    ) -> int:
        return ping.ping_provider(provider, timeout, model, prompt)

    def ping_entries(self) -> list[str]:
        state = st.ensure_provider_state(read_only=True)
        return sorted(state.providers)

    def ping_error_lines(self, name: str, prompt: str) -> list[str]:
        state = st.ensure_provider_state(read_only=True)
        return [
            f"current provider: {state.active_provider}",
            f"ping provider: {name}",
        ]

    def export(self, file_path: str | None) -> int:
        import lib.claude.transfer as transfer

        return transfer.export_command(file_path)

    def import_(self, file_path: str | None, dry_run: bool) -> int:
        import lib.claude.transfer as transfer

        return transfer.import_command(file_path, dry_run)


BACKEND = ClaudeBackend()


def build_parser() -> argparse.ArgumentParser:
    return build_parser_for(BACKEND)


def main(argv: list[str] | None = None) -> int:
    return generic_main(BACKEND, argv)
