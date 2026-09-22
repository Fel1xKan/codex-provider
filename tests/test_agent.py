from __future__ import annotations

import argparse
from unittest.mock import MagicMock, patch

import pytest

from cli import xpx as xpx_cli
from lib.common.errors import SwitchError
from lib.xpx.adapters.claude import ClaudeAdapter
from lib.xpx.adapters.codex import CodexAdapter
from lib.xpx.adapters.cursor import CursorAdapter
from lib.xpx.adapters.opencode import OpenCodeAdapter
from lib.xpx.adapters.pi import PiAdapter
from lib.xpx.commands import cmd_agent


def test_adapter_cli_version_parsing() -> None:
    adp = CodexAdapter()

    # 1. Parse codex version format
    with (
        patch.object(adp, "get_binary_path", return_value="/fake/codex"),
        patch(
            "subprocess.run",
            return_value=MagicMock(
                stdout="codex-cli 0.155.1\n", stderr="", returncode=0
            ),
        ),
    ):
        if hasattr(adp, "_cached_cli_version"):
            delattr(adp, "_cached_cli_version")
        ver = adp.get_cli_version()
        assert ver == "v0.155.1"

    # 2. Parse claude version format
    claude_adp = ClaudeAdapter()
    with (
        patch.object(claude_adp, "get_binary_path", return_value="/fake/claude"),
        patch(
            "subprocess.run",
            return_value=MagicMock(
                stdout="2.1.267 (Claude Code)\n", stderr="", returncode=0
            ),
        ),
    ):
        ver = claude_adp.get_cli_version()
        assert ver == "v2.1.267"

    # 3. Handle failure / timeout
    err_adp = OpenCodeAdapter()
    with (
        patch.object(err_adp, "get_binary_path", return_value="/fake/opencode"),
        patch("subprocess.run", side_effect=Exception("timeout")),
    ):
        ver = err_adp.get_cli_version()
        assert ver is None


def test_agent_list_cli(capsys: pytest.CaptureFixture[str]) -> None:
    rc = xpx_cli.main(["agent", "list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Agent" in out
    assert "Installed" in out
    assert "Version" in out
    assert "codex" in out
    assert "claude" in out
    assert "opencode" in out
    assert "cursor" in out

    # Test default subcommand 'agent' without 'list'
    rc_def = xpx_cli.main(["agent"])
    assert rc_def == 0


def test_agent_install_cli(capsys: pytest.CaptureFixture[str]) -> None:
    # 1. Unknown agent error
    with pytest.raises(SwitchError):
        cmd_agent.run_agent_install(
            argparse.Namespace(
                target="nonexistent_agent", all=False, dry_run=False, force=False
            )
        )

    # 2. No target and no --all shows usage and missing
    rc_none = cmd_agent.run_agent_install(
        argparse.Namespace(target=None, all=False, dry_run=False, force=False)
    )
    assert rc_none in (0, 1)
    out_none = capsys.readouterr().out
    assert "xpx agent install <name>" in out_none

    # 3. Dry run install for cursor (guide)
    rc_cursor = xpx_cli.main(["agent", "install", "cursor", "--dry-run", "--force"])
    assert rc_cursor == 0
    out_cursor = capsys.readouterr().out
    assert "cursor.com" in out_cursor

    # 4. Dry run install for claude
    with patch("shutil.which", return_value="/fake/npm"):
        rc_claude = xpx_cli.main(["agent", "install", "claude", "--dry-run", "--force"])
        assert rc_claude == 0
        out_claude = capsys.readouterr().out
        assert "would execute:" in out_claude
        assert "@anthropic-ai/claude-code" in out_claude

    # 5. Dry run install all
    rc_all = xpx_cli.main(["agent", "install", "--all", "--dry-run", "--force"])
    assert rc_all == 0
    out_all = capsys.readouterr().out
    assert "Installing" in out_all


def test_agent_update_cli(capsys: pytest.CaptureFixture[str]) -> None:
    # 1. Unknown agent error
    with pytest.raises(SwitchError):
        cmd_agent.run_agent_update(
            argparse.Namespace(target="nonexistent_agent", all=False, dry_run=False)
        )

    # 2. No target and no --all shows usage
    rc_none = cmd_agent.run_agent_update(
        argparse.Namespace(target=None, all=False, dry_run=False)
    )
    assert rc_none in (0, 1)
    out_none = capsys.readouterr().out
    assert "xpx agent update <name>" in out_none

    # 3. Update non-installed agent gives helpful message
    cursor_adp = CursorAdapter()
    with (
        patch.object(cursor_adp, "get_binary_path", return_value=None),
        patch(
            "lib.xpx.commands.cmd_agent.get_all_adapters",
            return_value={"cursor": cursor_adp},
        ),
    ):
        rc_uninst = cmd_agent.run_agent_update(
            argparse.Namespace(target="cursor", all=False, dry_run=False)
        )
        assert rc_uninst == 1
        err = capsys.readouterr().err
        assert "is not installed" in err

    # 4. Dry run update for claude (native update command)
    claude_adp = ClaudeAdapter()
    with (
        patch.object(
            claude_adp, "get_binary_path", return_value="/usr/local/bin/claude"
        ),
        patch(
            "lib.xpx.commands.cmd_agent.get_all_adapters",
            return_value={"claude": claude_adp},
        ),
    ):
        rc_upd = cmd_agent.run_agent_update(
            argparse.Namespace(target="claude", all=False, dry_run=True)
        )
        assert rc_upd == 0
        out_upd = capsys.readouterr().out
        assert "would execute: /usr/local/bin/claude update" in out_upd


def test_agent_install_missing_npm() -> None:
    pi_adp = PiAdapter()
    assert pi_adp.package_name == "@earendil-works/pi-coding-agent"
    with patch("lib.xpx.adapters.base.find_node_package_manager", return_value=None):
        ok, msg = pi_adp.install(dry_run=False)
        assert ok is False
        assert "Node.js package manager" in msg

    # Pi uses native 'pi update' when installed
    with patch.object(pi_adp, "get_binary_path", return_value="/fake/bin/pi"):
        ok_up, msg_up = pi_adp.update(dry_run=True)
        assert ok_up is True
        assert "would execute: /fake/bin/pi update" in msg_up


def test_agent_install_and_update_execution() -> None:
    codex_adp = CodexAdapter()

    # Successful install execution
    with (
        patch("lib.xpx.adapters.base.find_node_package_manager", return_value="npm"),
        patch("subprocess.run", return_value=MagicMock(returncode=0)),
    ):
        ok, msg = codex_adp.install(dry_run=False)
        assert ok is True
        assert "Successfully installed" in msg

    # Failed install execution
    with (
        patch("lib.xpx.adapters.base.find_node_package_manager", return_value="npm"),
        patch("subprocess.run", return_value=MagicMock(returncode=1)),
    ):
        ok, msg = codex_adp.install(dry_run=False)
        assert ok is False
        assert "exited with code 1" in msg


def test_top_level_install_and_update_shortcuts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Test 'xpx install --help' and 'xpx update --help'
    with pytest.raises(SystemExit) as exc1:
        xpx_cli.main(["install", "--help"])
    assert exc1.value.code == 0
    assert "Install target agent CLI(s)" in capsys.readouterr().out

    with pytest.raises(SystemExit) as exc2:
        xpx_cli.main(["update", "--help"])
    assert exc2.value.code == 0
    assert "Update target agent CLI(s)" in capsys.readouterr().out
