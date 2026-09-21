from __future__ import annotations

from unittest.mock import patch

from cli import xpx as xpx_cli
from lib.xpx.interactive.selector import Choice, checkbox, confirm, prompt_text, select
from lib.xpx.interactive.terminal import (
    InputEvent,
    KeyCode,
    TerminalSession,
)


def test_choice_creation() -> None:
    c = Choice("Codex", "codex", description="OpenAI Codex adapter", checked=True)
    assert c.title == "Codex"
    assert c.value == "codex"
    assert c.description == "OpenAI Codex adapter"
    assert c.checked is True


def test_terminal_session_sgr_mouse_parser() -> None:
    session = TerminalSession(enable_mouse=False, hide_cursor=False)

    # Mock stdin.read(1) to stream SGR mouse sequence: [<64;20;10M (Wheel Up)
    seq = list("[<64;20;10M")
    with patch("sys.stdin.read", side_effect=seq):
        session._has_bytes = lambda _timeout=0.04: len(seq) > 0  # type: ignore[assignment]
        event = session._parse_escape_sequence()
        assert event.code == KeyCode.MOUSE_WHEEL_UP
        assert event.mouse_x == 20
        assert event.mouse_y == 10

    # Test Wheel Down: [<65;20;10M
    seq_down = list("[<65;20;10M")
    with patch("sys.stdin.read", side_effect=seq_down):
        session._has_bytes = lambda _timeout=0.04: len(seq_down) > 0  # type: ignore[assignment]
        event = session._parse_escape_sequence()
        assert event.code == KeyCode.MOUSE_WHEEL_DOWN

    # Test Left Click: [<0;15;8M
    seq_click = list("[<0;15;8M")
    with patch("sys.stdin.read", side_effect=seq_click):
        session._has_bytes = lambda _timeout=0.04: len(seq_click) > 0  # type: ignore[assignment]
        event = session._parse_escape_sequence()
        assert event.code == KeyCode.MOUSE_CLICK
        assert event.mouse_x == 15
        assert event.mouse_y == 8


def test_terminal_session_arrow_keys() -> None:
    session = TerminalSession(enable_mouse=False, hide_cursor=False)

    # UP arrow: [A
    seq_up = list("[A")
    with patch("sys.stdin.read", side_effect=seq_up):
        session._has_bytes = lambda _timeout=0.04: len(seq_up) > 0  # type: ignore[assignment]
        assert session._parse_escape_sequence().code == KeyCode.UP

    # DOWN arrow: [B
    seq_down = list("[B")
    with patch("sys.stdin.read", side_effect=seq_down):
        session._has_bytes = lambda _timeout=0.04: len(seq_down) > 0  # type: ignore[assignment]
        assert session._parse_escape_sequence().code == KeyCode.DOWN

    # SS3 UP arrow: OA
    seq_ss3 = list("OA")
    with patch("sys.stdin.read", side_effect=seq_ss3):
        session._has_bytes = lambda _timeout=0.04: len(seq_ss3) > 0  # type: ignore[assignment]
        assert session._parse_escape_sequence().code == KeyCode.UP

    # Standalone ESC (no bytes follow)
    session._has_bytes = lambda _timeout=0.04: False  # type: ignore[assignment]
    assert session._parse_escape_sequence().code == KeyCode.ESC


def test_select_single_with_enter() -> None:
    choices = [Choice("Codex", "codex"), Choice("Claude", "claude")]

    # Simulate: DOWN, then ENTER
    events = [
        InputEvent(KeyCode.DOWN),
        InputEvent(KeyCode.ENTER),
    ]

    with patch.object(TerminalSession, "read_event", side_effect=events):
        res = select("选择客户端", choices)
        assert res == "claude"


def test_select_filter_and_search() -> None:
    choices = [
        Choice("deepseek", "deepseek"),
        Choice("siliconflow", "siliconflow"),
        Choice("openrouter", "openrouter"),
    ]

    # Type 's', 'i', then ENTER -> filters to 'siliconflow'
    events = [
        InputEvent(KeyCode.CHAR, char="s"),
        InputEvent(KeyCode.CHAR, char="i"),
        InputEvent(KeyCode.ENTER),
    ]

    with patch.object(TerminalSession, "read_event", side_effect=events):
        res = select("选择 Provider", choices)
        assert res == "siliconflow"


def test_checkbox_space_toggle_and_select_all() -> None:
    choices = [
        Choice("codex", "codex", checked=False),
        Choice("claude", "claude", checked=False),
        Choice("opencode", "opencode", checked=False),
    ]

    # Move DOWN, press SPACE (toggle claude), press ENTER
    events = [
        InputEvent(KeyCode.DOWN),
        InputEvent(KeyCode.SPACE),
        InputEvent(KeyCode.ENTER),
    ]

    with patch.object(TerminalSession, "read_event", side_effect=events):
        res = checkbox("勾选客户端", choices)
        assert res == ["claude"]

    # Test 'a' key (select all)
    choices2 = [
        Choice("codex", "codex", checked=False),
        Choice("claude", "claude", checked=False),
    ]
    events_all = [
        InputEvent(KeyCode.CHAR, char="a"),
        InputEvent(KeyCode.ENTER),
    ]

    with patch.object(TerminalSession, "read_event", side_effect=events_all):
        res2 = checkbox("勾选客户端", choices2)
        assert res2 == ["codex", "claude"]


def test_prompt_text_and_confirm() -> None:
    # Text input: type 'k', 'e', 'y', enter
    events_text = [
        InputEvent(KeyCode.CHAR, char="k"),
        InputEvent(KeyCode.CHAR, char="e"),
        InputEvent(KeyCode.CHAR, char="y"),
        InputEvent(KeyCode.ENTER),
    ]
    with patch.object(TerminalSession, "read_event", side_effect=events_text):
        val = prompt_text("API Key")
        assert val == "key"

    # Text input with LEFT arrow and insert
    events_cursor = [
        InputEvent(KeyCode.CHAR, char="a"),
        InputEvent(KeyCode.CHAR, char="b"),
        InputEvent(KeyCode.LEFT),
        InputEvent(KeyCode.CHAR, char="x"),
        InputEvent(KeyCode.ENTER),
    ]
    with patch.object(TerminalSession, "read_event", side_effect=events_cursor):
        assert prompt_text("Name") == "axb"

    # Confirm prompt: default True + enter
    with patch.object(
        TerminalSession, "read_event", return_value=InputEvent(KeyCode.ENTER)
    ):
        ok = confirm("确定？")
        assert ok is True


def test_cli_interactive_subcommand_routing() -> None:
    with patch(
        "lib.xpx.interactive.wizards.run_interactive_main", return_value=0
    ) as mock_main:
        rc = xpx_cli.main(["i"])
        assert rc == 0
        assert mock_main.called

    with patch(
        "lib.xpx.interactive.wizards.run_interactive_main", return_value=0
    ) as mock_main2:
        rc2 = xpx_cli.main(["interactive"])
        assert rc2 == 0
        assert mock_main2.called


def test_confirm_action_enter_and_esc() -> None:
    from lib.xpx.interactive.wizards import _confirm_action

    # 1. Enter confirms execution
    with patch.object(
        TerminalSession, "read_event", return_value=InputEvent(KeyCode.ENTER)
    ):
        assert _confirm_action("确认执行？") is True

    # 2. Esc goes back
    with patch.object(
        TerminalSession, "read_event", return_value=InputEvent(KeyCode.ESC)
    ):
        assert _confirm_action("确认执行？") is False


def test_prompt_select_model_flow() -> None:
    from lib.xpx.interactive.wizards import _prompt_select_model
    from lib.xpx.store.provider_store import ProviderSpec

    mock_pv = ProviderSpec(
        name="cistern",
        base_url="https://api.cistern.com/v1",
        api_key="sk-test",
        default_model="deepseek-chat",
    )

    with (
        patch(
            "lib.xpx.store.provider_store.ProviderStore.require",
            return_value=mock_pv,
        ),
        patch("lib.xpx.store.catalog_store.CatalogStore.get", return_value=None),
    ):
        # 1. Select a model directly
        with patch(
            "lib.xpx.interactive.wizards.select", return_value="deepseek-reasoner"
        ):
            res = _prompt_select_model("cistern", include_keep=True)
            assert res == "deepseek-reasoner"

        # 2. Select __keep__
        with patch("lib.xpx.interactive.wizards.select", return_value="__keep__"):
            res = _prompt_select_model("cistern", include_keep=True)
            assert res == "__keep__"

        # 3. Select __custom__ and type custom model
        with (
            patch("lib.xpx.interactive.wizards.select", return_value="__custom__"),
            patch(
                "lib.xpx.interactive.wizards.prompt_text",
                return_value="my-special-model",
            ),
        ):
            res = _prompt_select_model("cistern", include_keep=True)
            assert res == "my-special-model"


def test_render_card_alignment() -> None:
    from lib.xpx.interactive.selector import render_card, str_display_width

    # 1. Chinese title + typical apply lines
    zh_title = "最终配置确认"
    lines = [
        "Targets:     opencode",
        "Provider:    cistern/deepseek-v4.1-flash",
        "Command:     xpx apply opencode cistern/deepseek-v4.1-flash",
    ]
    card = render_card(zh_title, lines)
    card_lines = card.strip().split("\n")
    widths = [str_display_width(line) for line in card_lines]
    # All lines must have the EXACT same visual width
    assert len(set(widths)) == 1
    assert widths[0] >= 60

    # 2. English title + long lines
    en_title = "Final Configuration Confirmation"
    card_en = render_card(en_title, lines)
    card_en_lines = card_en.strip().split("\n")
    en_widths = [str_display_width(line) for line in card_en_lines]
    assert len(set(en_widths)) == 1


def test_apply_direct_exit_on_success() -> None:
    from lib.xpx.interactive.wizards import run_interactive_main

    # If apply succeeds (returns 0), run_interactive_main exits immediately with 0
    with (
        patch("lib.xpx.interactive.wizards.select", side_effect=["apply"]),
        patch("lib.xpx.interactive.wizards.run_interactive_apply", return_value=0),
        patch("lib.xpx.interactive.wizards._render_banner"),
    ):
        rc = run_interactive_main()
        assert rc == 0

    # If apply is cancelled (returns None), loop continues and exits when exit selected
    with (
        patch("lib.xpx.interactive.wizards.select", side_effect=["apply", "exit"]),
        patch("lib.xpx.interactive.wizards.run_interactive_apply", return_value=None),
        patch("lib.xpx.interactive.wizards._render_banner"),
    ):
        rc = run_interactive_main()
        assert rc == 0
