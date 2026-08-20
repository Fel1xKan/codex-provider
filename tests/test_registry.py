from __future__ import annotations

import argparse

import cli.agy_provider as agy
import cli.codex_provider as codex
import cli.opencode_provider as op
from lib.common.backend import BaseBackend
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
    for parser in (codex.build_parser(), op.build_parser(), agy.build_parser()):
        assert shared <= set(parser_commands(parser))


def test_capability_commands_only_on_declaring_backends() -> None:
    codex_commands = set(parser_commands(codex.build_parser()))
    opencode_commands = set(parser_commands(op.build_parser()))
    agy_commands = set(parser_commands(agy.build_parser()))

    assert "models" not in codex_commands
    assert "models" not in agy_commands
    assert "models" in opencode_commands
    assert "usage" not in codex_commands
    assert "usage" not in opencode_commands
    assert "usage" in agy_commands
    assert "login" in agy_commands


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
