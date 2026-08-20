from __future__ import annotations

import argparse
import sys
from typing import Any

import lib.codex.admin as adm
import lib.codex.edit as edit
import lib.codex.store as st
from lib.codex.doctor import (
    doctor,
)
from lib.codex.doctor import (
    run_codex_ping as default_run_codex_ping,
)
from lib.codex.switch import switch_provider
from lib.common.backend import BaseBackend
from lib.common.cli import (
    generic_main,
)
from lib.common.cli import (
    read_api_key as read_common_api_key,
)
from lib.common.errors import SwitchError
from lib.common.recent import (
    ensure_recent_providers,
    sort_providers_by_recent,
)
from lib.common.registry import build_parser_for


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


def ping_all_providers(timeout: float, model: str | None, prompt: str) -> int:
    state = st.load_provider_state()
    if not state.providers:
        raise SwitchError("no providers configured")

    results: list[tuple[str, int]] = []
    for index, provider in enumerate(sorted(state.providers)):
        if index:
            print("")
        try:
            result = ping_provider(provider, timeout, model, prompt)
        except SwitchError as exc:
            print(f"current provider: {state.active_provider}")
            print(f"ping provider: {provider}")
            print("ping result: failed")
            print(f"error: {exc}")
            result = 1
        results.append((provider, result))

    available = sum(result == 0 for _, result in results)
    print("")
    print("provider ping summary:")
    for provider, result in results:
        print(f"- {provider}: {'ok' if result == 0 else 'failed'}")
    print(f"available: {available}/{len(results)}")
    return 0 if available == len(results) else 1


class CodexBackend(BaseBackend):
    prog = "codex-provider"
    description = "Switch the default provider in Codex global config."
    command_help = {
        "list": "List providers from codex-provider config",
        "status": "Show current provider and configuration",
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

    def switch(self, target: str, model: str | None, dry_run: bool) -> int:
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
        return edit.add_provider(
            args.provider,
            args.base_url,
            api_key,
            args.display_name,
            args.wire_api,
            supports_ws,
            args.dry_run,
        )

    def delete(self, provider: str, full: bool, dry_run: bool) -> int:
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

    def doctor(self, fix: bool) -> int:
        return doctor(fix)

    def test_provider(self, provider: str | None, timeout: float) -> int:
        return adm.test_provider(provider, timeout)

    def test_all_providers(self, timeout: float) -> int:
        return adm.test_all_providers(timeout)

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

    def ping_all_providers(self, timeout: float, model: str | None, prompt: str) -> int:
        return ping_all_providers(timeout, model, prompt)

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
