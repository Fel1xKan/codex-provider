from __future__ import annotations

import argparse
import sys

import pytest

import cli.agy_provider as agy
import cli.claude_provider as claude
import cli.codex_provider as codex
import cli.cursor_provider as cursor
import cli.opencode_provider as op
from lib.common.backend import BaseBackend
from lib.common.cli import generic_main
from lib.common.registry import COMMON_COMMANDS, build_parser_for


def parser_commands(
    parser: argparse.ArgumentParser,
) -> dict[str, argparse.ArgumentParser]:
    action = next(
        item for item in parser._actions if isinstance(item, argparse._SubParsersAction)
    )
    return action.choices


def test_every_cli_exposes_shared_registry_commands() -> None:
    shared = {spec.name for spec in COMMON_COMMANDS if spec.capability is None}
    for parser in (
        codex.build_parser(),
        op.build_parser(),
        agy.build_parser(),
        cursor.build_parser(),
        claude.build_parser(),
    ):
        assert shared <= set(parser_commands(parser))


def test_capability_commands_only_on_declaring_backends() -> None:
    codex_commands = set(parser_commands(codex.build_parser()))
    opencode_commands = set(parser_commands(op.build_parser()))
    agy_commands = set(parser_commands(agy.build_parser()))
    cursor_commands = set(parser_commands(cursor.build_parser()))
    claude_commands = set(parser_commands(claude.build_parser()))

    assert "models" not in codex_commands
    assert "models" not in agy_commands
    assert "models" in opencode_commands
    assert "usage" not in codex_commands
    assert "usage" not in opencode_commands
    assert "usage" in agy_commands
    assert "login" in agy_commands
    assert "models" in cursor_commands
    assert "provider" in cursor_commands
    assert "official" not in claude_commands
    assert "models" in claude_commands


def test_codex_only_extensions_stay_out_of_other_clis() -> None:
    codex_config = codex.build_parser()
    opencode_config = op.build_parser()
    agy_config = agy.build_parser()
    cursor_config = cursor.build_parser()

    assert "official" in parser_commands(codex_config)
    for parser in (opencode_config, agy_config, cursor_config):
        assert "official" not in parser_commands(parser)
    assert "official" not in parser_commands(claude.build_parser())

    opencode_cmds = parser_commands(opencode_config)
    agy_cmds = parser_commands(agy_config)
    cursor_cmds = parser_commands(cursor_config)
    codex_cmds = parser_commands(codex_config)

    def config_subcommands(parser: argparse.ArgumentParser) -> set[str]:
        action = next(item for item in parser._actions if item.dest == "config_command")
        return set(action.choices)

    assert config_subcommands(opencode_cmds["config"]) == {"show", "edit"}
    assert config_subcommands(agy_cmds["config"]) == {"show", "edit"}
    assert config_subcommands(cursor_cmds["config"]) == {"show", "edit"}
    assert config_subcommands(codex_cmds["config"]) == {"show", "edit", "set"}

    def add_options(parser: argparse.ArgumentParser) -> set[str]:
        return {
            option for action in parser._actions for option in action.option_strings
        }

    for parser in (opencode_config, agy_config, cursor_config):
        other_add = add_options(parser_commands(parser)["add"])
        assert "--fast" not in other_add
    assert "--no-fast" not in add_options(codex_cmds["add"])


class StubBackend(BaseBackend):
    prog = "stub-provider"
    description = "stub provider"


def test_new_backend_gets_full_command_surface_from_registry() -> None:
    stub = StubBackend()
    parser = build_parser_for(stub)
    expected = set()
    for spec in COMMON_COMMANDS:
        expected.add(spec.name)
        expected.update(spec.aliases)
    assert set(parser_commands(parser)) == expected


class RecordingBackend(StubBackend):
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    def auth_detail(self, provider: str | None) -> int:
        self.calls.append(("auth_detail", provider))
        return 0

    def config_detail(self, provider: str | None) -> int:
        self.calls.append(("config_detail", provider))
        return 0


def test_subcommand_dispatch_resolves_through_registry() -> None:
    backend = RecordingBackend()

    assert generic_main(backend, ["auth", "show", "alpha"]) == 0
    assert backend.calls == [("auth_detail", "alpha")]

    assert generic_main(backend, ["config", "show", "alpha"]) == 0
    assert backend.calls[-1] == ("config_detail", "alpha")


def test_legacy_name_prints_rename_notice_and_refuses(
    capsys: pytest.CaptureFixture[str],
) -> None:
    original = sys.argv[0]
    try:
        sys.argv[0] = "codex-provider"
        assert codex.main(["--version"]) == 1
        captured = capsys.readouterr()
        assert "renamed" in captured.err
        assert "cpx" in captured.err

        sys.argv[0] = "cpx"
        assert codex.main(["--version"]) == 0
    finally:
        sys.argv[0] = original
