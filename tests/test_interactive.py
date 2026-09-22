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


def test_theme_palette_and_components() -> None:
    from lib.xpx.interactive import theme

    # Test RGB conversion
    r, g, b = theme.hex_to_rgb("#38BDF8")
    assert (r, g, b) == (56, 189, 248)

    # Test 256 color mapping
    idx = theme.rgb_to_256(r, g, b)
    assert 16 <= idx <= 255

    # Test breadcrumb
    bc = theme.breadcrumb(1, 4, "选择目标", context="codex")
    assert "步骤 1/4" in bc
    assert "选择目标" in bc
    assert "codex" in bc

    # Test pill and keycap
    with patch.object(theme, "supports_color", return_value=True):
        p = theme.pill("codex", "#1E3A8A", "#93C5FD")
        assert "codex" in p
        kc = theme.keycap("Enter", "确认")
        assert "Enter" in kc
        assert "确认" in kc


def test_render_banner_output() -> None:
    from io import StringIO

    from lib.xpx.interactive.wizards import _render_banner

    out = StringIO()
    with patch("sys.stdout", out):
        _render_banner()

    val = out.getvalue()
    assert "xpx control plane" in val
    assert "╭" in val
    assert "╰" in val


def test_windows_terminal_event_reading() -> None:
    import sys
    from unittest.mock import MagicMock

    session = TerminalSession(enable_mouse=False, hide_cursor=False)

    # Mock msvcrt for Windows key press: scan code for UP arrow (\xe0 + H)
    mock_msvcrt = MagicMock()
    mock_msvcrt.kbhit.side_effect = [True, True, False]
    mock_msvcrt.getwch.side_effect = ["\xe0", "H"]
    with patch.dict(sys.modules, {"msvcrt": mock_msvcrt}):
        ev = session._read_event_windows()
        assert ev.code == KeyCode.UP

    # Mock Enter (\r)
    mock_msvcrt2 = MagicMock()
    mock_msvcrt2.kbhit.return_value = True
    mock_msvcrt2.getwch.return_value = "\r"
    with patch.dict(sys.modules, {"msvcrt": mock_msvcrt2}):
        ev_enter = session._read_event_windows()
        assert ev_enter.code == KeyCode.ENTER


def test_clear_screen_behavior() -> None:
    from io import StringIO

    from lib.xpx.interactive.theme import clear_screen

    # 1. TTY enabled: writes ANSI clear screen sequence
    fake_out = StringIO()
    fake_out.isatty = lambda: True  # type: ignore[assignment]
    with patch("sys.stdout", fake_out):
        clear_screen()
        assert fake_out.getvalue() == "\033[2J\033[H"

    # 2. Non-TTY: does not write escape sequence
    fake_pipe = StringIO()
    fake_pipe.isatty = lambda: False  # type: ignore[assignment]
    with patch("sys.stdout", fake_pipe):
        clear_screen()
        assert fake_pipe.getvalue() == ""


def test_wizards_clear_screen_called() -> None:
    from lib.xpx.interactive.wizards import run_interactive_main

    with (
        patch("lib.xpx.interactive.wizards.clear_screen") as mock_clear,
        patch("lib.xpx.interactive.wizards.select", return_value="exit"),
        patch("lib.xpx.interactive.wizards._render_banner"),
    ):
        rc = run_interactive_main()
        assert rc == 0
        assert mock_clear.called
