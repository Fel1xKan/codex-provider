from __future__ import annotations

from collections.abc import Callable
from typing import Any

from lib.common.registry import COMMON_COMMANDS, ArgSpec, CommandSpec


class BaseBackend:
    prog: str = ""
    description: str = ""
    capabilities: frozenset[str] = frozenset()
    switch_include_model: bool = False
    command_help: dict[str, str] = {}
    command_args: dict[str, tuple[ArgSpec, ...]] = {}
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

    def switch(self, target: str, model: str | None, dry_run: bool) -> int:
        raise NotImplementedError

    def add(self, args: Any) -> int:
        raise NotImplementedError

    def delete(self, provider: str, full: bool, dry_run: bool) -> int:
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

    def test_all_providers(self, timeout: float) -> int:
        raise NotImplementedError

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

    def ping_all_providers(self, timeout: float, model: str | None, prompt: str) -> int:
        raise NotImplementedError

    def export(self, file_path: str | None) -> int:
        raise NotImplementedError

    def import_(self, file_path: str | None, dry_run: bool) -> int:
        raise NotImplementedError
