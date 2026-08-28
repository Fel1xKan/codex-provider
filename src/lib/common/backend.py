from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from lib.common import self_upgrade
from lib.common.constants import VERSION
from lib.common.errors import SwitchError
from lib.common.registry import COMMON_COMMANDS, ArgSpec, CommandSpec, SubcommandSpec


@dataclass(frozen=True)
class TestTarget:
    name: str
    base_url: str
    api_key: str
    anthropic: bool = False
    error: str | None = None


class BaseBackend:
    prog: str = ""
    description: str = ""
    capabilities: frozenset[str] = frozenset()
    switch_include_model: bool = False
    command_help: dict[str, str] = {}
    command_args: dict[str, tuple[ArgSpec, ...]] = {}
    command_subcommands: dict[str, tuple[SubcommandSpec, ...]] = {}
    extra_commands: tuple[CommandSpec, ...] = ()
    extra_handlers: dict[str, Callable[[Any], int]] = {}

    def commands(self) -> tuple[CommandSpec, ...]:
        commands = [
            spec
            for spec in COMMON_COMMANDS
            if spec.capability is None or spec.capability in self.capabilities
        ]
        commands.extend(self.extra_commands)
        return tuple(commands)

    def recent_entries(self) -> list[str]:
        raise NotImplementedError

    def current_entry(self) -> str | None:
        raise NotImplementedError

    def list(self) -> int:
        raise NotImplementedError

    def status(self) -> int:
        raise NotImplementedError

    def switch(
        self, target: str, model: str | None, dry_run: bool, force: bool = False
    ) -> int:
        raise NotImplementedError

    def add(self, args: Any) -> int:
        raise NotImplementedError

    def delete(
        self, provider: str, full: bool, dry_run: bool, force: bool = False
    ) -> int:
        raise NotImplementedError

    def rename(self, old: str, new: str, dry_run: bool) -> int:
        raise NotImplementedError

    def auth_detail(self, provider: str | None) -> int:
        raise NotImplementedError

    def auth_edit(self, provider: str | None) -> int:
        raise NotImplementedError

    def config_detail(self, provider: str | None) -> int:
        raise NotImplementedError

    def config_edit(self, provider: str | None) -> int:
        raise NotImplementedError

    def doctor(self, fix: bool) -> int:
        raise NotImplementedError

    def test_provider(self, provider: str | None, timeout: float) -> int:
        raise NotImplementedError

    def test_targets(self) -> list[TestTarget]:
        raise NotImplementedError

    def run_models_test(self, target: TestTarget, timeout: float) -> int:
        raise NotImplementedError

    def test_all_providers(self, timeout: float) -> int:
        targets = self.test_targets()
        results: list[tuple[str, int]] = []
        for index, target in enumerate(targets):
            if index:
                print("")
            if target.error:
                print(f"test provider: {target.name}")
                print(f"base_url: {target.base_url}")
                print("result: failed")
                print(f"error: {target.error}")
                results.append((target.name, 1))
                continue
            rc = self.run_models_test(target, timeout)
            results.append((target.name, rc))

        available = sum(rc == 0 for _, rc in results)
        print("")
        print("provider test summary:")
        for name, rc in results:
            print(f"- {name}: {'ok' if rc == 0 else 'failed'}")
        print(f"available: {available}/{len(results)}")
        return 0 if available == len(results) else 1

    def test_direct(self, base_url: str, api_key: str, timeout: float) -> int:
        raise NotImplementedError

    def ping_provider(
        self,
        provider: str | None,
        timeout: float,
        model: str | None,
        prompt: str,
    ) -> int:
        raise NotImplementedError

    def ping_entries(self) -> list[str]:
        raise NotImplementedError

    def ping_error_lines(self, name: str, prompt: str) -> list[str]:
        raise NotImplementedError

    def ping_all_providers(self, timeout: float, model: str | None, prompt: str) -> int:
        entries = self.ping_entries()
        if not entries:
            raise SwitchError("no providers configured")

        results: list[tuple[str, int]] = []
        for index, name in enumerate(entries):
            if index:
                print("")
            try:
                result = self.ping_provider(name, timeout, model, prompt)
            except SwitchError as exc:
                for line in self.ping_error_lines(name, prompt):
                    print(line)
                print("ping result: failed")
                print(f"error: {exc}")
                result = 1
            results.append((name, result))

        available = sum(result == 0 for _, result in results)
        print("")
        print("provider ping summary:")
        for name, result in results:
            print(f"- {name}: {'ok' if result == 0 else 'failed'}")
        print(f"available: {available}/{len(results)}")
        return 0 if available == len(results) else 1

    def export(self, file_path: str | None) -> int:
        raise NotImplementedError

    def import_(self, file_path: str | None, dry_run: bool) -> int:
        raise NotImplementedError

    def upgrade(self, check: bool, dry_run: bool) -> int:
        payload = self_upgrade.fetch_latest_release(self_upgrade.DEFAULT_REPOSITORY)
        plan = self_upgrade.build_upgrade_plan(
            self_upgrade.DEFAULT_REPOSITORY,
            self.prog,
            VERSION,
            payload,
        )
        if check or dry_run:
            print(f"current: {plan.current_version}")
            print(f"latest:  {plan.latest_version}")
            print(f"asset:   {plan.asset_name}")
            if not plan.update_available:
                print("up to date")
            else:
                print("would upgrade" if dry_run else "update available")
            return 0
        target = self_upgrade.current_executable()
        return self_upgrade.perform_upgrade(plan, target)
