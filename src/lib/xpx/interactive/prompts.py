"""Shared interactive prompts: Enter-to-continue and explicit confirmation."""

from __future__ import annotations

import sys

from lib.xpx.i18n import t
from lib.xpx.interactive.selector import Choice, select


def wait_enter() -> None:
    sys.stdout.write(f"\n{t('ui.press_enter')}")
    sys.stdout.flush()
    sys.stdin.readline()


def confirm_action(prompt: str, *, default_confirm: bool = True) -> bool:
    """Explicit confirmation step: Enter confirms, Esc returns to previous step."""
    choices = [
        Choice(t("ui.action_confirm"), True),
        Choice(t("ui.action_back"), False),
    ]
    idx = 0 if default_confirm else 1
    res = select(prompt, choices, default_index=idx, allow_search=False)
    return bool(res)
