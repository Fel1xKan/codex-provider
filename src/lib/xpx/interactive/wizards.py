from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Any

from lib.common.constants import VERSION
from lib.xpx.adapters.registry import detect_installed_adapters, get_all_adapters
from lib.xpx.commands.cmd_account import (
    run_account_list,
    run_account_login,
    run_account_usage,
)
from lib.xpx.commands.cmd_agent import (
    run_agent_install,
    run_agent_list,
    run_agent_update,
)
from lib.xpx.commands.cmd_apply import run_apply
from lib.xpx.commands.cmd_doctor import run_doctor
from lib.xpx.commands.cmd_models import run_models_list, run_models_sync
from lib.xpx.commands.cmd_status import run_status
from lib.xpx.commands.cmd_test_ping import run_test
from lib.xpx.i18n import get_language, set_language, t
from lib.xpx.interactive.model_picker import prompt_select_model as _prompt_select_model
from lib.xpx.interactive.prompts import confirm_action as _confirm_action
from lib.xpx.interactive.prompts import wait_enter as _wait_enter
from lib.xpx.interactive.provider_wizards import (
    add_provider_wizard as _wizard_add_provider,
)
from lib.xpx.interactive.provider_wizards import (
    manage_providers_wizard as _wizard_manage_providers,
)
from lib.xpx.interactive.selector import (
    BOLD,
    GREEN,
    RED,
    RESET,
    YELLOW,
    Choice,
    checkbox,
    prompt_text,
    render_card,
    select,
)
from lib.xpx.interactive.theme import (
    DIM_TEXT,
    MUTED,
    SUCCESS,
    TEXT,
    WARNING,
    breadcrumb,
    clear_screen,
    styled,
    target_badge,
)
from lib.xpx.store.account_store import AccountStore
from lib.xpx.store.provider_store import ProviderStore
from lib.xpx.store.state_store import StateStore

KNOWN_PROVIDER_PRESETS: dict[str, dict[str, str]] = {
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


def _render_banner() -> None:
    """Renders a modern, structured status dashboard card above the menu."""
    state_store = StateStore()
    current_state = state_store.load()
    adapters = get_all_adapters()

    lines: list[str] = []
    for t_name in sorted(adapters.keys()):
        adp = adapters[t_name]
        ts = current_state.targets.get(t_name)
        ver = adp.get_cli_version()
        ver_str = f"[{ver}]" if ver else ""
        t_tag = target_badge(t_name)

        if ts and ts.active_name:
            if ts.active_type == "provider":
                model_info = f" ({ts.active_model})" if ts.active_model else ""
                status_str = (
                    f"{styled('●', fg_color=SUCCESS)} "
                    f"{styled(ts.active_name, fg_color=TEXT, bold=True)}"
                    f"{styled(model_info, fg_color=MUTED)}"
                )
            else:
                account_tag = f"({t('apply.mode_account')})"
                status_str = (
                    f"{styled('●', fg_color=SUCCESS)} "
                    f"{styled(ts.active_name, fg_color=WARNING)} "
                    f"{styled(account_tag, fg_color=MUTED)}"
                )
        else:
            if adp.get_binary_path():
                inactive_tag = f"({t('ui.status_inactive')})"
                status_str = (
                    f"{styled('○', fg_color=DIM_TEXT)} "
                    f"{styled(inactive_tag, fg_color=DIM_TEXT)}"
                )
            else:
                not_inst_tag = f"({t('agent.not_installed')})"
                status_str = (
                    f"{styled('-', fg_color=DIM_TEXT)} "
                    f"{styled(not_inst_tag, fg_color=DIM_TEXT)}"
                )

        v_col = styled(ver_str, fg_color=DIM_TEXT) if ver_str else ""
        lines.append(f"{t_tag}  {status_str}  {v_col}".strip())

    title = f"◈  {t('banner.title')} v{VERSION}"
    card = render_card(title, lines)
    sys.stdout.write(f"\n{card}\n")
    sys.stdout.flush()


def run_interactive_language() -> None:
    """Interactive language switcher."""
    clear_screen()
    current = get_language()
    choices = [
        Choice("中文 (Simplified Chinese)", "zh"),
        Choice("English", "en"),
        Choice(t("ui.back"), "back"),
    ]
    def_idx = 0 if current == "zh" else 1
    chosen = select(t("main.language"), choices, default_index=def_idx)
    if chosen and chosen != "back":
        set_language(chosen, persist=True)
        sys.stdout.write(f"\n{GREEN}✔ Language switched to: {chosen}{RESET}\n")
        _wait_enter()


def run_interactive_agents() -> int:
    """Agent CLI installation and update management wizard."""
    while True:
        clear_screen()
        sys.stdout.write(f"\n{BOLD}{t('agent.title')}{RESET}\n")
        choices = [
            Choice(t("agent.action_list"), "list"),
            Choice(t("agent.action_install_missing"), "install"),
            Choice(t("agent.action_update_all"), "update"),
            Choice(t("ui.back_menu"), "back"),
        ]
        action = select(t("pv.action_prompt"), choices)
        if not action or action == "back":
            return 0

        if action == "list":
            clear_screen()
            run_agent_list(argparse.Namespace())
            _wait_enter()
        elif action == "install":
            adapters = get_all_adapters()
            missing = [
                name
                for name in ("codex", "claude", "opencode", "agy", "pi", "cursor")
                if name in adapters and not adapters[name].get_binary_path()
            ]
            if not missing:
                sys.stdout.write(f"\n{GREEN}{t('agent.all_installed')}{RESET}\n")
                _wait_enter()
                continue
            opts = (
                [
                    Choice(
                        f"🌟 {t('agent.install_all')} ({', '.join(missing)})", "__all__"
                    )
                ]
                + [Choice(name, name) for name in missing]
                + [Choice(t("ui.back"), "back")]
            )
            chosen = select(t("agent.select_install"), opts)
            if chosen == "__all__":
                if _confirm_action(t("agent.confirm_install_all", count=len(missing))):
                    clear_screen()
                    run_agent_install(
                        argparse.Namespace(
                            target=None, all=True, dry_run=False, force=False
                        )
                    )
                    _wait_enter()
            elif (
                chosen
                and chosen != "back"
                and _confirm_action(t("agent.confirm_install", name=chosen))
            ):
                clear_screen()
                run_agent_install(
                    argparse.Namespace(
                        target=chosen, all=False, dry_run=False, force=False
                    )
                )
                _wait_enter()
        elif action == "update":
            adapters = get_all_adapters()
            installed = [
                name
                for name in ("codex", "claude", "opencode", "agy", "pi", "cursor")
                if name in adapters and adapters[name].get_binary_path()
            ]
            if not installed:
                sys.stdout.write(f"\n{YELLOW}{t('agent.no_installed')}{RESET}\n")
                _wait_enter()
                continue
            opts = (
                [
                    Choice(
                        f"🌟 {t('agent.update_all')} ({', '.join(installed)})",
                        "__all__",
                    )
                ]
                + [Choice(name, name) for name in installed]
                + [Choice(t("ui.back"), "back")]
            )
            chosen = select(t("agent.select_update"), opts)
            if chosen == "__all__":
                if _confirm_action(t("agent.confirm_update_all", count=len(installed))):
                    clear_screen()
                    run_agent_update(
                        argparse.Namespace(target=None, all=True, dry_run=False)
                    )
                    _wait_enter()
            elif (
                chosen
                and chosen != "back"
                and _confirm_action(t("agent.confirm_update", name=chosen))
            ):
                clear_screen()
                run_agent_update(
                    argparse.Namespace(target=chosen, all=False, dry_run=False)
                )
                _wait_enter()


def run_interactive_main() -> int:
    """Main interactive menu dispatch loop."""
    while True:
        clear_screen()
        _render_banner()

        choices = [
            Choice(t("main.apply"), "apply", t("main.apply_desc")),
            Choice(t("main.status"), "status", t("main.status_desc")),
            Choice(t("main.agents"), "agents", t("main.agents_desc")),
            Choice(t("main.providers"), "providers", t("main.providers_desc")),
            Choice(t("main.models"), "models", t("main.models_desc")),
            Choice(t("main.doctor"), "doctor_ping", t("main.doctor_desc")),
            Choice(t("main.accounts"), "accounts", t("main.accounts_desc")),
            Choice(t("main.language"), "language", t("main.language_desc")),
            Choice(t("main.exit"), "exit", t("main.exit_desc")),
        ]

        action = select(t("main.prompt"), choices, page_size=9)
        if not action or action == "exit":
            sys.stdout.write(f"\n{t('ui.exit_msg')}\n")
            return 0

        try:
            if action == "apply":
                rc = run_interactive_apply()
                if rc == 0:
                    return 0
            elif action == "status":
                rc = run_interactive_status()
                if rc == 0:
                    return 0
            elif action == "agents":
                run_interactive_agents()
            elif action == "providers":
                run_interactive_providers()
            elif action == "models":
                run_interactive_models()
            elif action == "doctor_ping":
                run_interactive_doctor_ping()
            elif action == "accounts":
                run_interactive_accounts()
            elif action == "language":
                run_interactive_language()
        except KeyboardInterrupt:
            sys.stdout.write(f"\n{t('ui.cancelled')}\n")
        except Exception as exc:
            sys.stdout.write(f"\n{YELLOW}Error: {exc}{RESET}\n")

    return 0


@dataclass
class _ApplyFlow:
    """Mutable state threaded through the guided apply wizard phases."""

    pre_target: str | None
    pre_provider: str | None
    target_names: list[str]
    mode: str = "provider"
    chosen_account: str | None = None
    provider_name: str | None = None
    chosen_model: str | None = None
    gate: str = "now"
    opt_fast: bool | None = None
    opt_web_search: bool | None = None
    opt_dry_run: bool = False
    opt_no_save: bool = False
    opt_wire_api: str | None = None
    rc: int = 0


def _apply_header() -> None:
    clear_screen()
    sys.stdout.write(f"\n{BOLD}{t('apply.title')}{RESET}\n")


def _apply_phase_targets(
    flow: _ApplyFlow, installed: dict[str, Any], current_state: Any
) -> str:
    _apply_header()
    sys.stdout.write(f"\n{breadcrumb(1, 4, t('apply.target_prompt'))}")
    target_choices: list[Choice] = []
    for t_name in sorted(installed.keys()):
        ts = current_state.targets.get(t_name)
        adp = installed.get(t_name)
        ver = adp.get_cli_version() if adp else None
        ver_tag = f"[{ver}] " if ver else ""
        if ts and ts.active_name:
            act_str = f"{ver_tag}({ts.active_type}:{ts.active_name})"
        else:
            act_str = f"{ver_tag}(default)"
        target_choices.append(Choice(t_name, t_name, description=act_str))

    if not target_choices:
        sys.stdout.write(f"{YELLOW}{t('apply.no_targets')}{RESET}\n")
        flow.rc = 1
        return "EXIT"

    selected_targets = checkbox(
        t("apply.target_prompt"),
        target_choices,
        allow_empty=False,
    )
    if not selected_targets:
        # Aborted selection: keep the historical exit code of 0.
        flow.rc = 0
        return "EXIT"
    flow.target_names = [str(x) for x in selected_targets]
    return "MODE"


def _apply_phase_mode(flow: _ApplyFlow) -> str:
    _apply_header()
    targets_str = ", ".join(flow.target_names)
    bc = breadcrumb(
        2, 4, t("apply.mode_prompt", targets=targets_str), context=targets_str
    )
    sys.stdout.write(f"\n{bc}")
    mode_choices = [
        Choice(
            t("apply.mode_provider"),
            "provider",
            t("apply.mode_provider_desc"),
        ),
        Choice(
            t("apply.mode_account"),
            "account",
            t("apply.mode_account_desc"),
        ),
        Choice(
            t("apply.mode_reset"),
            "reset",
            t("apply.mode_reset_desc"),
        ),
    ]
    res_mode = select(
        t("apply.mode_prompt", targets=targets_str),
        mode_choices,
    )
    if not res_mode:
        return "TARGETS" if not flow.pre_target else "EXIT"
    flow.mode = res_mode
    if flow.mode == "reset":
        return "CONFIRM_EXECUTE"
    if flow.mode == "account":
        return "ACCOUNT"
    return "PROVIDER"


def _apply_phase_account(flow: _ApplyFlow, acc_store: AccountStore) -> str:
    _apply_header()
    saved_accounts = acc_store.list_all()
    if not saved_accounts:
        sys.stdout.write(f"{YELLOW}{t('apply.account_none')}{RESET}\n")
        return "MODE"

    acc_choices = [
        Choice(f"{a.target}:{a.name}", a.name, description=f"({a.target})")
        for a in saved_accounts
    ]
    chosen_acc = select(t("apply.account_prompt"), acc_choices)
    if not chosen_acc:
        return "MODE"
    flow.chosen_account = chosen_acc
    return "CONFIRM_EXECUTE"


def _apply_phase_provider(flow: _ApplyFlow, pv_store: ProviderStore) -> str:
    providers = pv_store.list_all()
    if not providers:
        sys.stdout.write(f"{YELLOW}{t('apply.provider_none')}{RESET}\n")
        flow.rc = 1
        return "EXIT"

    if flow.pre_provider:
        flow.provider_name = flow.pre_provider
        return "MODEL"

    _apply_header()
    targets_str = ", ".join(flow.target_names)
    sys.stdout.write(
        f"\n{breadcrumb(3, 4, t('apply.provider_prompt'), context=targets_str)}"
    )
    pv_choices: list[Choice] = []
    for pv in providers:
        model_hint = f" | {pv.default_model}" if pv.default_model else ""
        desc = f"({pv.protocol}{model_hint})"
        pv_choices.append(Choice(pv.name, pv.name, description=desc))

    chosen_pv = select(t("apply.provider_prompt"), pv_choices)
    if not chosen_pv:
        return "MODE"
    flow.provider_name = chosen_pv
    return "MODEL"


def _apply_phase_model(flow: _ApplyFlow) -> str:
    provider_name = flow.provider_name
    if provider_name is None:
        flow.rc = 1
        return "EXIT"
    _apply_header()
    targets_str = ", ".join(flow.target_names)
    bc = breadcrumb(
        4,
        4,
        t("apply.model_prompt", provider=provider_name),
        context=f"{targets_str} › {provider_name}",
    )
    sys.stdout.write(f"\n{bc}")
    chosen_model_action = _prompt_select_model(
        provider_name,
        include_keep=True,
        allow_custom=True,
    )
    if not chosen_model_action:
        return "PROVIDER" if not flow.pre_provider else "MODE"

    if chosen_model_action == "__keep__":
        flow.chosen_model = None
    else:
        flow.chosen_model = chosen_model_action

    return "FORK_GATE"


def _apply_phase_fork_gate(flow: _ApplyFlow) -> str:
    _apply_header()
    has_codex = "codex" in flow.target_names
    gate_adv_desc = (
        t("apply.gate_adv_desc") if has_codex else t("apply.gate_adv_desc_non_codex")
    )
    fork_choices = [
        Choice(
            t("apply.gate_now"),
            "now",
            t("apply.gate_now_desc"),
        ),
        Choice(
            t("apply.gate_adv"),
            "advanced",
            gate_adv_desc,
        ),
    ]
    res_gate = select(t("apply.gate_prompt"), fork_choices)
    if not res_gate:
        return "MODEL"
    flow.gate = res_gate
    if flow.gate == "advanced":
        return "ADVANCED_OPTIONS"
    flow.opt_fast = None
    flow.opt_web_search = None
    flow.opt_dry_run = False
    flow.opt_no_save = False
    flow.opt_wire_api = None
    return "CONFIRM_EXECUTE"


def _apply_flag_choices(flow: _ApplyFlow, has_codex: bool) -> list[Choice]:
    flag_choices: list[Choice] = []
    if has_codex:
        codex_tag = " (Codex)" if len(flow.target_names) > 1 else ""
        flag_choices.append(
            Choice(
                f"{t('apply.flag_fast')}{codex_tag}",
                "fast",
                t("apply.flag_fast_desc"),
                checked=bool(flow.opt_fast),
            )
        )
        flag_choices.append(
            Choice(
                f"{t('apply.flag_web_search')}{codex_tag}",
                "web_search",
                t("apply.flag_web_search_desc"),
                checked=bool(flow.opt_web_search),
            )
        )
    flag_choices.extend(
        [
            Choice(
                t("apply.flag_dry_run"),
                "dry_run",
                t("apply.flag_dry_run_desc"),
                checked=bool(flow.opt_dry_run),
            ),
            Choice(
                t("apply.flag_no_save"),
                "no_save",
                t("apply.flag_no_save_desc"),
                checked=bool(flow.opt_no_save),
            ),
        ]
    )
    return flag_choices


def _apply_phase_advanced(flow: _ApplyFlow) -> str:
    _apply_header()
    has_codex = "codex" in flow.target_names
    selected_flags = checkbox(
        t("apply.adv_prompt"),
        _apply_flag_choices(flow, has_codex),
        allow_empty=True,
    )
    if selected_flags is None:
        return "FORK_GATE"

    if has_codex:
        flow.opt_fast = True if "fast" in selected_flags else None
        flow.opt_web_search = True if "web_search" in selected_flags else None
    else:
        flow.opt_fast = None
        flow.opt_web_search = None
    flow.opt_dry_run = "dry_run" in selected_flags
    flow.opt_no_save = "no_save" in selected_flags

    if has_codex:
        wire_choice = select(
            t("apply.wire_prompt"),
            [
                Choice(t("apply.wire_default"), "__none__"),
                Choice("chat (chat.completions)", "chat"),
                Choice("responses (Codex responses)", "responses"),
            ],
        )
        if wire_choice is None:
            return "ADVANCED_OPTIONS"
        flow.opt_wire_api = wire_choice if wire_choice != "__none__" else None
    else:
        flow.opt_wire_api = None

    return "CONFIRM_EXECUTE"


def _apply_reset_args(targets_str: str) -> argparse.Namespace:
    return argparse.Namespace(
        target=targets_str,
        provider_spec=None,
        all=False,
        account=None,
        model=None,
        clear=True,
        dry_run=False,
        no_save=False,
        fast=None,
        wire_api=None,
        web_search=None,
        header=[],
    )


def _apply_account_args(
    targets_str: str, chosen_account: str | None
) -> argparse.Namespace:
    return argparse.Namespace(
        target=targets_str,
        provider_spec=None,
        all=False,
        account=chosen_account,
        model=None,
        clear=False,
        dry_run=False,
        no_save=False,
        fast=None,
        wire_api=None,
        web_search=None,
        header=[],
    )


def _apply_provider_args(
    flow: _ApplyFlow, targets_str: str, spec_str: str, has_codex: bool
) -> argparse.Namespace:
    return argparse.Namespace(
        target=targets_str,
        provider_spec=spec_str,
        all=False,
        account=None,
        model=flow.chosen_model,
        clear=False,
        dry_run=flow.opt_dry_run,
        no_save=flow.opt_no_save,
        fast=flow.opt_fast if has_codex else None,
        wire_api=flow.opt_wire_api if has_codex else None,
        web_search=flow.opt_web_search if has_codex else None,
        header=[],
    )


def _apply_provider_flags(
    flow: _ApplyFlow, cmd_parts: list[str], has_codex: bool
) -> list[str]:
    flags_info: list[str] = []
    multi = len(flow.target_names) > 1
    codex_tag = " (Codex)" if multi else ""
    if flow.opt_fast and has_codex:
        cmd_parts.append("--fast")
        flags_info.append(f"--fast{codex_tag}")
    if flow.opt_web_search and has_codex:
        cmd_parts.append("--web-search")
        flags_info.append(f"--web-search{codex_tag}")
    if flow.opt_wire_api and has_codex:
        cmd_parts.extend(["--wire-api", flow.opt_wire_api])
        flags_info.append(f"--wire-api {flow.opt_wire_api}{codex_tag}")
    if flow.opt_dry_run:
        cmd_parts.append("--dry-run")
        flags_info.append("--dry-run")
    if flow.opt_no_save:
        cmd_parts.append("--no-save")
        flags_info.append("--no-save")
    return flags_info


def _apply_confirm_summary(
    flow: _ApplyFlow, targets_str: str
) -> tuple[list[str], list[str], argparse.Namespace]:
    cmd_parts = ["xpx", "apply", targets_str]
    summary_lines: list[str] = [f"Targets:     {targets_str}"]
    has_codex = "codex" in flow.target_names

    if flow.mode == "reset":
        cmd_parts.append("--clear")
        summary_lines.append(f"Action:      {t('apply.mode_reset')}")
        return cmd_parts, summary_lines, _apply_reset_args(targets_str)
    if flow.mode == "account":
        cmd_parts.extend(["--account", str(flow.chosen_account)])
        summary_lines.append(f"Account:     {flow.chosen_account}")
        args = _apply_account_args(targets_str, flow.chosen_account)
        return cmd_parts, summary_lines, args

    spec_str = str(flow.provider_name)
    if flow.chosen_model:
        spec_str = f"{flow.provider_name}/{flow.chosen_model}"
    cmd_parts.append(spec_str)
    summary_lines.append(f"Provider:    {spec_str}")

    flags_info = _apply_provider_flags(flow, cmd_parts, has_codex)
    if flags_info:
        summary_lines.append(f"Options:     {', '.join(flags_info)}")
    args = _apply_provider_args(flow, targets_str, spec_str, has_codex)
    return cmd_parts, summary_lines, args


def _apply_phase_confirm(flow: _ApplyFlow) -> str:
    _apply_header()
    targets_str = ",".join(flow.target_names)
    cmd_parts, summary_lines, args = _apply_confirm_summary(flow, targets_str)
    summary_lines.append(f"Command:     {' '.join(cmd_parts)}")

    card_text = render_card(t("apply.confirm_card_title"), summary_lines)
    sys.stdout.write(f"\n{card_text}")
    sys.stdout.flush()

    confirmed = _confirm_action(t("apply.confirm_prompt"))
    if not confirmed:
        if flow.mode == "reset":
            return "MODE"
        if flow.mode == "account":
            return "ACCOUNT"
        if flow.gate == "advanced":
            return "ADVANCED_OPTIONS"
        return "FORK_GATE"

    clear_screen()
    flow.rc = run_apply(args)
    return "EXIT"


_APPLY_PHASES = {
    "TARGETS": _apply_phase_targets,
    "MODE": _apply_phase_mode,
    "ACCOUNT": _apply_phase_account,
    "PROVIDER": _apply_phase_provider,
    "MODEL": _apply_phase_model,
    "FORK_GATE": _apply_phase_fork_gate,
    "ADVANCED_OPTIONS": _apply_phase_advanced,
    "CONFIRM_EXECUTE": _apply_phase_confirm,
}


def run_interactive_apply(
    pre_target: str | None = None,
    pre_provider: str | None = None,
) -> int:
    """Guided Apply flow with Esc step-back and Enter final confirmation."""
    installed = detect_installed_adapters()
    current_state = StateStore().load()
    flow = _ApplyFlow(
        pre_target=pre_target,
        pre_provider=pre_provider,
        target_names=(
            [
                t_name.strip().lower()
                for t_name in pre_target.split(",")
                if t_name.strip()
            ]
            if pre_target
            else []
        ),
        provider_name=pre_provider,
    )
    phase = _APPLY_PHASES["TARGETS"] if not pre_target else _APPLY_PHASES["MODE"]
    while True:
        if phase is _apply_phase_targets:
            step = phase(flow, installed, current_state)
        elif phase is _apply_phase_account:
            step = phase(flow, AccountStore())
        elif phase is _apply_phase_provider:
            step = phase(flow, ProviderStore())
        else:
            step = phase(flow)
        if step == "EXIT":
            return flow.rc
        phase = _APPLY_PHASES[step]


def run_interactive_providers() -> int:
    """Providers management wizard."""
    while True:
        clear_screen()
        sys.stdout.write(f"\n{BOLD}{t('pv.title')}{RESET}\n")
        pv_store = ProviderStore()
        providers = pv_store.list_all()

        choices = [
            Choice(t("pv.browse", count=len(providers)), "list"),
            Choice(t("pv.add"), "add"),
            Choice(t("pv.sync_all"), "sync_all"),
            Choice(t("ui.back_menu"), "back"),
        ]
        action = select(t("pv.action_prompt"), choices)
        if not action or action == "back":
            return 0

        if action == "add":
            _wizard_add_provider()
        elif action == "list":
            _wizard_manage_providers(providers)
        elif action == "sync_all":
            clear_screen()
            if not providers:
                sys.stdout.write(f"{YELLOW}{t('apply.provider_none')}{RESET}\n")
            else:
                for pv in providers:
                    sys.stdout.write(f"Syncing models for {pv.name}...\n")
                    run_models_sync(argparse.Namespace(provider=pv.name, force=False))
                sys.stdout.write(f"{GREEN}✔ All models synchronized.{RESET}\n")
            _wait_enter()


def run_interactive_doctor_ping() -> int:
    """Doctor health check, connectivity testing, and prompt ping wizard."""
    while True:
        clear_screen()
        sys.stdout.write(f"\n{BOLD}{t('doc.title')}{RESET}\n")

        choices = [
            Choice(t("doc.doctor"), "doctor"),
            Choice(t("doc.doctor_fix"), "doctor_fix"),
            Choice(t("doc.test"), "test"),
            Choice(t("doc.deep_test"), "deep_test"),
            Choice(t("ui.back_menu"), "back"),
        ]
        action = select(t("pv.action_prompt"), choices)
        if not action or action == "back":
            return 0

        if action == "doctor":
            clear_screen()
            run_doctor(argparse.Namespace(fix=False))
            _wait_enter()
        elif action == "doctor_fix":
            if _confirm_action(t("doc.fix_confirm")):
                clear_screen()
                run_doctor(argparse.Namespace(fix=True))
                _wait_enter()
        elif action == "test":
            pv_store = ProviderStore()
            providers = pv_store.list_all()
            if not providers:
                sys.stdout.write(f"{YELLOW}{t('apply.provider_none')}{RESET}\n")
                _wait_enter()
                continue
            pv_choices = [
                Choice(pv.name, pv.name, description=pv.base_url) for pv in providers
            ]
            selected_pvs = checkbox(
                t("doc.test_prompt"),
                pv_choices,
                allow_empty=False,
            )
            if selected_pvs and _confirm_action(
                t("doc.test_confirm", count=len(selected_pvs))
            ):
                clear_screen()
                for p in selected_pvs:
                    run_test(argparse.Namespace(provider=p, all=False))
                _wait_enter()
        elif action == "deep_test":
            installed = detect_installed_adapters()
            if not installed:
                sys.stdout.write(f"{YELLOW}{t('apply.no_targets')}{RESET}\n")
                _wait_enter()
                continue
            target = select(t("doc.deep_target_prompt"), list(installed.keys()))
            if target:
                prompt_str = prompt_text(
                    t("doc.deep_prompt"),
                    default="say hi",
                )
                if prompt_str and _confirm_action(t("doc.deep_confirm", target=target)):
                    clear_screen()
                    run_test(
                        argparse.Namespace(
                            provider=None,
                            target=target,
                            deep=True,
                            prompt=prompt_str,
                            timeout=30,
                            model=None,
                            all=False,
                        )
                    )
                    _wait_enter()


def run_interactive_models() -> int:
    """Models list and sync wizard."""
    while True:
        clear_screen()
        sys.stdout.write(f"\n{BOLD}{t('models.title')}{RESET}\n")
        pv_store = ProviderStore()
        providers = pv_store.list_all()
        if not providers:
            sys.stdout.write(f"{YELLOW}{t('apply.provider_none')}{RESET}\n")
            _wait_enter()
            return 0

        pv_name = select(
            t("models.select_pv"),
            [pv.name for pv in providers],
        )
        if not pv_name:
            return 0

        clear_screen()
        sub_action = select(
            f"[{pv_name}]",
            [
                Choice(t("models.list"), "list"),
                Choice(t("models.sync"), "sync"),
                Choice(t("models.add"), "add"),
                Choice(t("ui.back"), "back"),
            ],
        )
        if sub_action == "list":
            clear_screen()
            run_models_list(argparse.Namespace(provider=pv_name, remote=False))
            _wait_enter()
        elif sub_action == "sync" and _confirm_action(
            t("models.sync_confirm", name=pv_name)
        ):
            clear_screen()
            run_models_sync(argparse.Namespace(provider=pv_name, force=False))
            _wait_enter()
        elif sub_action == "add":
            clear_screen()
            sys.stdout.write(f"\n{BOLD}{t('models.add_title', name=pv_name)}{RESET}\n")
            mid = prompt_text(t("models.add_prompt"), allow_empty=False)
            if mid and mid.strip():
                try:
                    from lib.xpx.models.catalog import add_model_to_catalog

                    meta, is_created = add_model_to_catalog(pv_name, mid.strip())
                    msg_key = (
                        "models.add_success" if is_created else "models.update_success"
                    )
                    res_msg = t(msg_key, model=meta.id, provider=pv_name)
                    sys.stdout.write(f"\n{GREEN}✔ {res_msg}{RESET}\n")
                except Exception as exc:
                    sys.stdout.write(f"\n{RED}✘ {exc}{RESET}\n")
                _wait_enter()


def run_interactive_accounts() -> int:
    """OAuth and session account management wizard."""
    while True:
        clear_screen()
        sys.stdout.write(f"\n{BOLD}{t('acc.title')}{RESET}\n")
        choices = [
            Choice(t("acc.list"), "list"),
            Choice(t("acc.login"), "login"),
            Choice(t("acc.usage"), "usage"),
            Choice(t("ui.back_menu"), "back"),
        ]
        action = select(t("pv.action_prompt"), choices)
        if not action or action == "back":
            return 0

        if action == "list":
            clear_screen()
            run_account_list(argparse.Namespace())
            _wait_enter()
        elif action == "login":
            target = select(t("acc.select_target"), ["agy", "codex", "cursor"])
            if target:
                alias = prompt_text(
                    t("acc.alias_prompt"),
                    default="",
                )
                if alias is not None and _confirm_action(
                    t("acc.login_confirm", target=target)
                ):
                    clear_screen()
                    run_account_login(
                        argparse.Namespace(target=target, name=alias or None)
                    )
                    _wait_enter()
        elif action == "usage":
            clear_screen()
            run_account_usage(argparse.Namespace(target="agy", name=None))
            _wait_enter()


def run_interactive_status() -> int | None:
    """Displays global status dashboard and allows instant action."""
    clear_screen()
    run_status(argparse.Namespace())
    sub = select(
        t("main.prompt"),
        [
            Choice(t("main.apply"), "apply"),
            Choice(t("ui.back_menu"), "back"),
        ],
    )
    if sub == "apply":
        return run_interactive_apply()
    return None
