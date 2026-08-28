from __future__ import annotations

import argparse
import sys
from typing import Any

import lib.codex.admin as adm
import lib.codex.edit as edit
import lib.codex.store as st
from lib.codex.doctor import (
    doctor,
    load_auth_json,
)
from lib.codex.doctor import (
    run_codex_ping as default_run_codex_ping,
)
from lib.codex.switch import switch_provider
from lib.common.backend import BaseBackend, TestTarget
from lib.common.cli import (
    generic_main,
)
from lib.common.cli import (
    read_api_key as read_common_api_key,
)
from lib.common.constants import MODE_OFFICIAL
from lib.common.errors import SwitchError
from lib.common.recent import (
    ensure_recent_providers,
    sort_providers_by_recent,
)
from lib.common.registry import (
    ADD_ARGS,
    APPLY_OPT,
    CONFIG_EDIT_SUB,
    CONFIG_SHOW_SUB,
    DRY_RUN,
    FAST_MODE_OFF,
    FAST_MODE_OPT,
    HEADER_OPT,
    MODEL_CATALOG_OPT,
    ArgSpec,
    CommandSpec,
    SubcommandSpec,
    build_parser_for,
)


def get_run_codex_ping() -> Any:
    mod = sys.modules.get("cli.codex_provider") or sys.modules.get("codex_provider")
    if mod and hasattr(mod, "run_codex_ping"):
        return mod.run_codex_ping
    return default_run_codex_ping


def read_api_key(api_key_stdin: bool, prompt: str = "API key: ") -> str:
    mod = sys.modules.get("cli.codex_provider") or sys.modules.get("codex_provider")
    if (
        mod
        and hasattr(mod, "read_api_key")
        and mod.read_api_key is not None
        and mod.read_api_key != read_api_key
    ):
        return mod.read_api_key(api_key_stdin)
    return read_common_api_key(api_key_stdin, prompt)


def ping_provider(
    provider: str | None, timeout: float, model: str | None, prompt: str
) -> int:
    ping_fn = get_run_codex_ping()
    if provider is None:
        state = st.load_provider_state()
        if not state.active_provider:
            raise SwitchError("no active provider; switch to a provider first")
        return ping_fn(state.active_provider, timeout, model, prompt)
    with adm.temporary_provider(provider):
        return ping_fn(provider, timeout, model, prompt)


class CodexBackend(BaseBackend):
    prog = "cpx"
    legacy_name = "codex-provider"
    description = "Switch the default provider in Codex global config."
    command_help = {
        "list": "List providers from cpx config",
        "status": "Show current provider and configuration",
    }
    command_args = {
        "add": (
            *ADD_ARGS,
            MODEL_CATALOG_OPT,
            FAST_MODE_OPT,
            HEADER_OPT,
            APPLY_OPT,
            DRY_RUN,
        ),
    }
    command_subcommands = {
        "config": (
            CONFIG_SHOW_SUB,
            CONFIG_EDIT_SUB,
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
                        ("--wire-api",),
                        help="wire_api value",
                    ),
                    ArgSpec(
                        ("--supports-websockets",),
                        choices=("true", "false"),
                        help="Set supports_websockets explicitly",
                    ),
                    ArgSpec(
                        ("--supports-standalone-web-search",),
                        choices=("true", "false"),
                        help=(
                            "Enable or disable Codex live web search for this provider"
                        ),
                    ),
                    MODEL_CATALOG_OPT,
                    FAST_MODE_OPT,
                    FAST_MODE_OFF,
                    HEADER_OPT,
                    ArgSpec(
                        ("--reset",),
                        action="store_true",
                        help=(
                            "Clear fast mode, web search, and model catalog "
                            "options for the provider"
                        ),
                    ),
                    APPLY_OPT,
                    DRY_RUN,
                ),
            ),
        ),
    }
    extra_commands = (
        CommandSpec(
            "official",
            handler="official",
            summary="Manage the official Codex login provider",
            subcommands=(
                SubcommandSpec(
                    "add",
                    dest="official_command",
                    help="Snapshot the current Codex login as an official provider",
                    args=(
                        ArgSpec(
                            ("provider",),
                            nargs="?",
                            default="official",
                            help="Provider name, default: official",
                        ),
                        ArgSpec(
                            ("--name",),
                            dest="display_name",
                            help="Display name stored in provider config",
                        ),
                        DRY_RUN,
                    ),
                ),
            ),
        ),
    )
    extra_handlers = {
        "official": lambda args: edit.add_official_provider(
            args.provider, args.display_name, args.dry_run
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
        api_key = read_api_key(args.api_key_stdin)
        supports_ws = (
            True
            if args.supports_websockets == "true"
            else False
            if args.supports_websockets == "false"
            else None
        )
        supports_web_search = (
            True
            if getattr(args, "supports_standalone_web_search", "") == "true"
            else False
            if getattr(args, "supports_standalone_web_search", "") == "false"
            else None
        )
        return edit.add_provider(
            args.provider,
            args.base_url,
            api_key,
            args.display_name,
            args.wire_api,
            supports_ws,
            args.dry_run,
            getattr(args, "fast", False),
            getattr(args, "apply", False),
            getattr(args, "header", None),
            supports_standalone_web_search=supports_web_search,
            model_catalog_json=getattr(args, "provider_model_catalog_json", None),
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
        fast_mode: bool | None = None
        if args.fast and args.no_fast:
            raise SwitchError("--fast and --no-fast cannot be combined")
        if args.no_fast:
            fast_mode = False
        elif args.fast:
            fast_mode = True
        return edit.set_provider_options(
            args.provider,
            args.display_name,
            args.wire_api,
            args.supports_websockets,
            args.supports_standalone_web_search,
            args.provider_model_catalog_json,
            fast_mode,
            getattr(args, "header", None),
            args.reset,
            getattr(args, "apply", False),
            args.dry_run,
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
            if config.get("mode") == MODE_OFFICIAL:
                continue
            base_url = config.get("base_url", "")
            profile = st.auth_profile_path(provider, create=False)
            if not profile.exists():
                targets.append(
                    TestTarget(
                        provider,
                        base_url,
                        "",
                        error=(
                            "auth profile is missing for provider "
                            f"'{provider}': {profile}"
                        ),
                    )
                )
                continue
            try:
                auth_data = load_auth_json(profile)
                api_key = auth_data.get("OPENAI_API_KEY", "")
            except Exception as exc:
                targets.append(TestTarget(provider, base_url, "", error=str(exc)))
                continue
            targets.append(TestTarget(provider, base_url, api_key))
        return targets

    def run_models_test(self, target: TestTarget, timeout: float) -> int:
        state = st.ensure_provider_state(read_only=True)
        return adm.get_run_models_test()(
            target.name,
            target.base_url,
            target.api_key,
            timeout,
            state.active_provider,
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
        return ping_provider(provider, timeout, model, prompt)

    def ping_entries(self) -> list[str]:
        state = st.load_provider_state()
        return sorted(state.providers)

    def ping_error_lines(self, name: str, prompt: str) -> list[str]:
        state = st.load_provider_state()
        return [f"current provider: {state.active_provider}", f"ping provider: {name}"]

    def export(self, file_path: str | None) -> int:
        import lib.codex.transfer as transfer

        return transfer.export_command(file_path)

    def import_(self, file_path: str | None, dry_run: bool) -> int:
        import lib.codex.transfer as transfer

        return transfer.import_command(file_path, dry_run)


BACKEND = CodexBackend()


def build_parser() -> argparse.ArgumentParser:
    return build_parser_for(BACKEND)


def main(argv: list[str] | None = None) -> int:
    return generic_main(BACKEND, argv)
