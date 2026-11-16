"""Provider add/manage wizards for the interactive shell."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Any

from lib.xpx.commands.cmd_models import run_models_sync
from lib.xpx.commands.cmd_provider import run_add, run_delete
from lib.xpx.commands.cmd_set import run_set, run_show
from lib.xpx.commands.cmd_test_ping import run_test
from lib.xpx.i18n import t
from lib.xpx.interactive.model_picker import (
    UNIVERSAL_CURATED_MODELS,
    load_shared_models,
    prompt_select_model,
)
from lib.xpx.interactive.prompts import confirm_action, wait_enter
from lib.xpx.interactive.selector import (
    BOLD,
    GREEN,
    RESET,
    YELLOW,
    Choice,
    prompt_text,
    select,
)
from lib.xpx.interactive.theme import clear_screen
from lib.xpx.store.provider_store import ProviderStore

PROVIDER_PRESETS: dict[str, dict[str, str]] = {
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "protocol": "openai",
        "model": "deepseek-chat",
    },
    "siliconflow": {
        "base_url": "https://api.siliconflow.cn/v1",
        "protocol": "openai",
        "model": "deepseek-ai/DeepSeek-V3",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "protocol": "openai",
        "model": "anthropic/claude-3.5-sonnet",
    },
    "bailian": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "protocol": "openai",
        "model": "qwen-plus",
    },
    "moonshot": {
        "base_url": "https://api.moonshot.cn/v1",
        "protocol": "openai",
        "model": "moonshot-v1-8k",
    },
    "zhipu": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "protocol": "openai",
        "model": "glm-4-flash",
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "protocol": "openai",
        "model": "llama-3.3-70b-versatile",
    },
    "mistral": {
        "base_url": "https://api.mistral.ai/v1",
        "protocol": "openai",
        "model": "mistral-large-latest",
    },
}


@dataclass
class _AddState:
    """Answers gathered so far while adding a provider."""

    name: str = ""
    base_url: str = ""
    protocol: str = "openai"
    key: str | None = None
    default_model: str | None = None
    step: int = 1


def add_provider_wizard() -> None:
    """Step-by-step wizard to add a new provider with Esc back and Enter confirm."""
    state = _AddState()
    while True:
        clear_screen()
        sys.stdout.write(f"\n{BOLD}{t('pv.add_title')}{RESET}\n")
        if _ADD_STEPS[state.step](state) == "EXIT":
            return


def _preset(name: str) -> dict[str, str]:
    return PROVIDER_PRESETS.get(name.lower(), {})


def _step_name(state: _AddState) -> str | None:
    resolved = prompt_text(t("pv.name_prompt"), default=state.name, allow_empty=False)
    if not resolved:
        return "EXIT"
    state.name = resolved
    state.step = 2
    return None


def _step_url(state: _AddState) -> str | None:
    resolved = prompt_text(
        t("pv.url_prompt", name=state.name),
        default=state.base_url or _preset(state.name).get("base_url", ""),
        allow_empty=False,
    )
    if not resolved:
        state.step = 1
        return None
    state.base_url = resolved
    state.step = 3
    return None


def _step_protocol(state: _AddState) -> str | None:
    default_protocol = _preset(state.name).get("protocol", "openai")
    resolved = select(
        t("pv.proto_prompt", name=state.name),
        [
            Choice("openai (OpenAI API)", "openai"),
            Choice("anthropic (Anthropic Claude)", "anthropic"),
        ],
        default_index=0 if default_protocol == "openai" else 1,
    )
    if not resolved:
        state.step = 2
        return None
    state.protocol = resolved
    state.step = 4
    return None


def _step_key(state: _AddState) -> str | None:
    resolved = prompt_text(
        t("pv.key_prompt", name=state.name),
        default=state.key or "",
        password=True,
        allow_empty=True,
    )
    if resolved is None:
        state.step = 3
        return None
    state.key = resolved
    state.step = 5
    return None


def _step_model(state: _AddState) -> str | None:
    default_model = state.default_model or _preset(state.name).get("model", "")
    chosen = select(
        t("pv.model_prompt", name=state.name),
        _add_model_choices(default_model, load_shared_models()),
    )
    if not chosen:
        state.step = 4
        return None
    if chosen == "__none__":
        state.default_model = ""
    elif chosen == "__custom__":
        custom = prompt_text(t("apply.model_custom_prompt"), allow_empty=True)
        if custom is None:
            return None
        state.default_model = custom
    else:
        state.default_model = chosen
    state.step = 6
    return None


def _add_model_choices(
    default_model: str, shared_models: dict[str, Any]
) -> list[Choice]:
    choices: list[Choice] = []
    if default_model:
        choices.append(
            Choice(
                f"🌟 {default_model}",
                default_model,
                description=t("pv.model_recommended"),
            )
        )
    choices.append(
        Choice(t("pv.model_none"), "__none__", description=t("pv.model_none_desc"))
    )
    choices.append(
        Choice(
            f"✏️  {t('apply.model_custom')}",
            "__custom__",
            description=t("apply.model_custom_desc"),
        )
    )
    for mid in UNIVERSAL_CURATED_MODELS:
        if mid == default_model:
            continue
        info = shared_models.get(mid) or {}
        choices.append(Choice(mid, mid, description=info.get("display_name") or mid))
    return choices


def _step_confirm(state: _AddState) -> str | None:
    _render_add_card(state)
    if not confirm_action(t("pv.confirm_add_prompt", name=state.name)):
        state.step = 5
        return None
    clear_screen()
    run_add(
        argparse.Namespace(
            name=state.name,
            base_url=state.base_url,
            key=state.key,
            key_stdin=False,
            default_model=state.default_model or None,
            protocol=state.protocol,
        )
    )
    sys.stdout.write(f"\n{GREEN}{t('pv.add_success', name=state.name)}{RESET}\n")
    wait_enter()
    return "EXIT"


def _render_add_card(state: _AddState) -> None:
    native_cmd = f"xpx add {state.name} {state.base_url} --protocol {state.protocol}"
    if state.key:
        native_cmd += " --key sk-••••"
    if state.default_model:
        native_cmd += f" --default-model {state.default_model}"
    key_preview = "sk-••••••••" if state.key else "(none)"
    model_preview = state.default_model or "(none)"
    sys.stdout.write(
        f"\n{BOLD}┌── {t('pv.confirm_add_title')} "
        f"──────────────────────────────┐{RESET}\n"
    )
    sys.stdout.write(f"│  Name:      {state.name:<43}│\n")
    sys.stdout.write(f"│  Base URL:  {state.base_url:<43}│\n")
    sys.stdout.write(f"│  Protocol:  {state.protocol:<43}│\n")
    sys.stdout.write(f"│  API Key:   {key_preview:<43}│\n")
    sys.stdout.write(f"│  Model:     {model_preview:<43}│\n")
    sys.stdout.write(f"│  Command:   {native_cmd:<43}│\n")
    sys.stdout.write(
        f"{BOLD}└────────────────────────────────────────────────────────┘{RESET}\n"
    )


_ADD_STEPS = {
    1: _step_name,
    2: _step_url,
    3: _step_protocol,
    4: _step_key,
    5: _step_model,
    6: _step_confirm,
}


def manage_providers_wizard(providers: list[Any]) -> None:
    """Manage an individual provider."""
    if not providers:
        sys.stdout.write(f"{YELLOW}{t('apply.provider_none')}{RESET}\n")
        wait_enter()
        return
    while True:
        target = _pick_provider(providers)
        if not target:
            return
        clear_screen()
        sys.stdout.write(f"\n{BOLD}{t('pv.details_title', name=target)}{RESET}\n")
        run_show(argparse.Namespace(name=target))
        action = _pick_action(target)
        if not action or action == "back":
            continue
        if _run_action(target, action):
            return


def _pick_provider(providers: list[Any]) -> str | None:
    clear_screen()
    sys.stdout.write(f"\n{BOLD}{t('pv.title')}{RESET}\n")
    choices = [
        Choice(pv.name, pv.name, description=f"({pv.protocol} | {pv.base_url})")
        for pv in providers
    ]
    return select(t("pv.select_manage"), choices)


def _pick_action(target: str) -> str | None:
    return select(
        f"[{target}]",
        [
            Choice(t("pv.action_auth_set"), "auth_set"),
            Choice(t("pv.action_model_set"), "model_set"),
            Choice(t("pv.action_sync"), "sync"),
            Choice(t("pv.action_test"), "test"),
            Choice(t("pv.action_delete"), "delete"),
            Choice(t("ui.back"), "back"),
        ],
    )


def _run_action(target: str, action: str) -> bool:
    """Run one management action; True means the wizard should exit."""
    if action == "auth_set":
        _action_auth_set(target)
    elif action == "model_set":
        _action_model_set(target)
    elif action == "sync":
        _action_sync(target)
    elif action == "test":
        _action_test(target)
    elif action == "delete":
        return _action_delete(target)
    return False


def _action_auth_set(target: str) -> None:
    new_key = prompt_text(f"[{target}] API Key", password=True, allow_empty=False)
    if not new_key or not confirm_action(f"Update API Key for '{target}'?"):
        return
    clear_screen()
    run_set(
        argparse.Namespace(
            name=target,
            key=new_key,
            key_stdin=False,
            target=None,
            base_url=None,
            protocol=None,
            default_model=None,
            header=None,
            fast=None,
            wire_api=None,
            web_search=None,
            option=None,
            rename_to=None,
        )
    )
    wait_enter()


def _action_model_set(target: str) -> None:
    chosen = prompt_select_model(target, include_keep=False)
    if not chosen:
        return
    clear_screen()
    provider = ProviderStore().require(target)
    provider.default_model = chosen
    message = t("pv.model_updated", name=target, model=chosen)
    sys.stdout.write(f"\n{GREEN}{message}{RESET}\n")
    wait_enter()


def _action_sync(target: str) -> None:
    if not confirm_action(f"Synchronize remote models for '{target}'?"):
        return
    clear_screen()
    run_models_sync(argparse.Namespace(provider=target, force=False))
    wait_enter()


def _action_test(target: str) -> None:
    clear_screen()
    run_test(argparse.Namespace(provider=target, all=False))
    wait_enter()


def _action_delete(target: str) -> bool:
    if not confirm_action(t("pv.delete_confirm", name=target), default_confirm=False):
        return False
    clear_screen()
    run_delete(argparse.Namespace(name=target, full=True, dry_run=False))
    wait_enter()
    return True
