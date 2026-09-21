from __future__ import annotations

import argparse
import sys
from typing import Any

from lib.xpx.adapters.registry import detect_installed_adapters
from lib.xpx.commands.cmd_account import (
    run_account_list,
    run_account_login,
    run_account_usage,
)
from lib.xpx.commands.cmd_apply import run_apply
from lib.xpx.commands.cmd_auth import run_auth_set
from lib.xpx.commands.cmd_doctor import run_doctor
from lib.xpx.commands.cmd_models import run_models_list, run_models_sync
from lib.xpx.commands.cmd_provider import run_add, run_delete, run_show
from lib.xpx.commands.cmd_status import run_status
from lib.xpx.commands.cmd_test_ping import run_ping, run_test
from lib.xpx.i18n import get_language, set_language, t
from lib.xpx.interactive.selector import (
    BOLD,
    CYAN,
    DIM,
    GREEN,
    RESET,
    YELLOW,
    Choice,
    checkbox,
    prompt_text,
    render_card,
    select,
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


def _wait_enter() -> None:
    sys.stdout.write(f"\n{t('ui.press_enter')}")
    sys.stdout.flush()
    sys.stdin.readline()


def _confirm_action(prompt: str, *, default_confirm: bool = True) -> bool:
    """Explicit confirmation step: Enter confirms, Esc returns to previous step."""
    choices = [
        Choice(t("ui.action_confirm"), True),
        Choice(t("ui.action_back"), False),
    ]
    idx = 0 if default_confirm else 1
    res = select(prompt, choices, default_index=idx, allow_search=False)
    return bool(res)


def _render_banner() -> None:
    """Renders a clean status banner above the menu."""
    state_store = StateStore()
    current_state = state_store.load()

    sys.stdout.write(f"\n{BOLD}{CYAN}=== {t('banner.title')} ==={RESET}\n")
    has_active = False
    for target in sorted(current_state.targets.keys()):
        ts = current_state.targets[target]
        if ts.active_type == "provider" and ts.active_name:
            has_active = True
            model_info = f" ({ts.active_model})" if ts.active_model else ""
            sys.stdout.write(
                f"  {GREEN}●{RESET} {BOLD}{target}{RESET}: "
                f"{CYAN}{ts.active_name}{model_info}{RESET}\n"
            )
        elif ts.active_type == "account" and ts.active_name:
            has_active = True
            sys.stdout.write(
                f"  {GREEN}●{RESET} {BOLD}{target}{RESET}: "
                f"{YELLOW}account:{ts.active_name}{RESET}\n"
            )
    if not has_active:
        sys.stdout.write(f"  {DIM}{t('banner.default_state')}{RESET}\n")
    sys.stdout.write("\n")
    sys.stdout.flush()


def run_interactive_language() -> None:
    """Interactive language switcher."""
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


def run_interactive_main() -> int:
    """Main interactive menu dispatch loop."""
    while True:
        _render_banner()

        choices = [
            Choice(t("main.apply"), "apply", t("main.apply_desc")),
            Choice(t("main.status"), "status", t("main.status_desc")),
            Choice(t("main.providers"), "providers", t("main.providers_desc")),
            Choice(t("main.models"), "models", t("main.models_desc")),
            Choice(t("main.doctor"), "doctor_ping", t("main.doctor_desc")),
            Choice(t("main.accounts"), "accounts", t("main.accounts_desc")),
            Choice(t("main.language"), "language", t("main.language_desc")),
            Choice(t("main.exit"), "exit", t("main.exit_desc")),
        ]

        action = select(t("main.prompt"), choices, page_size=8)
        if not action or action == "exit":
            sys.stdout.write(f"{t('ui.exit_msg')}\n")
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


def _prompt_select_model(
    provider_name: str,
    *,
    include_keep: bool = True,
    allow_custom: bool = True,
) -> str | None:
    """Interactive model selector with cached, popular, sync, and custom options."""
    from lib.xpx.models.catalog import enrich_model_metadata, load_shared_catalog_data
    from lib.xpx.models.sync import sync_provider_models
    from lib.xpx.store.catalog_store import CatalogStore
    from lib.xpx.store.provider_store import ProviderStore

    pv_store = ProviderStore()
    cat_store = CatalogStore()

    while True:
        pv = pv_store.require(provider_name)
        cat = cat_store.get(provider_name)
        cached_models = cat.models if cat else {}
        shared_data = load_shared_catalog_data()
        shared_models = shared_data.get("models") or {}

        choices: list[Choice] = []
        seen_ids: set[str] = set()

        # 1. Provider's configured default model (if set)
        if pv.default_model:
            tag = t("apply.model_default_tag")
            meta = cached_models.get(pv.default_model) or enrich_model_metadata(
                pv.default_model
            )
            dname = (
                f" - {meta.display_name}"
                if meta.display_name and meta.display_name != pv.default_model
                else ""
            )
            desc = f"[{tag}]{dname}"
            choices.append(
                Choice(f"🌟 {pv.default_model}", pv.default_model, description=desc)
            )
            seen_ids.add(pv.default_model)

        # 2. Keep current active model on target clients
        if include_keep:
            choices.append(
                Choice(
                    f"📌 {t('apply.model_keep')}",
                    "__keep__",
                    description=t("apply.model_keep_desc"),
                )
            )

        # 3. Action: Sync remote models live
        choices.append(
            Choice(
                f"🔄 {t('apply.model_sync_remote')}",
                "__sync_remote__",
                description=t("apply.model_sync_remote_desc"),
            )
        )

        # 4. Cached / discovered models for this specific provider
        if cached_models:
            for mid, meta in cached_models.items():
                if mid in seen_ids:
                    continue
                seen_ids.add(mid)
                ctx_k = f"{meta.context_window // 1000}k" if meta.context_window else ""
                desc_parts: list[str] = []
                if meta.display_name and meta.display_name != mid:
                    desc_parts.append(meta.display_name)
                if ctx_k:
                    desc_parts.append(ctx_k)
                desc = " | ".join(desc_parts)
                choices.append(Choice(mid, mid, description=desc))

        # 5. Curated popular models (from shared catalog)
        pv_lower = provider_name.lower()
        proto_lower = pv.protocol.lower()

        curated_priority: list[str] = []
        if proto_lower == "anthropic" or "claude" in pv_lower:
            curated_priority.extend(
                [
                    "claude-3-7-sonnet-latest",
                    "claude-3-5-sonnet-latest",
                    "claude-3-5-haiku-latest",
                ]
            )
        elif "deepseek" in pv_lower:
            curated_priority.extend(
                [
                    "deepseek-reasoner",
                    "deepseek-chat",
                    "deepseek-v4-flash",
                ]
            )
        elif "google" in pv_lower or "gemini" in pv_lower:
            curated_priority.extend(
                [
                    "gemini-2.5-pro",
                    "gemini-2.5-flash",
                    "gemini-2.0-flash",
                ]
            )
        elif "qwen" in pv_lower or "bailian" in pv_lower:
            curated_priority.extend(
                [
                    "qwen-2.5-coder-32b",
                    "qwen-max",
                    "qwen-plus",
                ]
            )

        universal_curated = [
            "deepseek-reasoner",
            "deepseek-chat",
            "deepseek-v4-flash",
            "claude-3-7-sonnet-latest",
            "claude-3-5-sonnet-latest",
            "gpt-4o",
            "gpt-4o-mini",
            "o3-mini",
            "gemini-2.5-pro",
            "gemini-2.5-flash",
            "qwen-2.5-coder-32b",
            "qwen-max",
        ]
        for mid in universal_curated:
            if mid not in curated_priority:
                curated_priority.append(mid)

        for mid in curated_priority:
            if mid in seen_ids:
                continue
            seen_ids.add(mid)
            info = shared_models.get(mid) or {}
            dname = info.get("display_name") or mid
            ctx = info.get("context_window")
            ctx_k = f"{ctx // 1000}k" if ctx else ""
            desc = f"{dname} | {ctx_k}" if ctx_k else dname
            choices.append(Choice(mid, mid, description=desc))

        # 6. Additional shared catalog models
        for mid, info in shared_models.items():
            if mid in seen_ids:
                continue
            seen_ids.add(mid)
            dname = info.get("display_name") or mid
            choices.append(Choice(mid, mid, description=dname))

        # 7. Custom input option
        if allow_custom:
            choices.append(
                Choice(
                    f"✏️  {t('apply.model_custom')}",
                    "__custom__",
                    description=t("apply.model_custom_desc"),
                )
            )

        chosen = select(
            t("apply.model_prompt", provider=provider_name),
            choices,
            page_size=10,
        )
        if not chosen:
            return None

        if chosen == "__sync_remote__":
            sys.stdout.write(
                f"\n{CYAN}{t('apply.model_sync_connecting', url=pv.base_url)}{RESET}\n"
            )
            try:
                new_cat = sync_provider_models(provider_name, force=True)
                count = len(new_cat.models)
                sys.stdout.write(
                    f"{GREEN}✔ {t('apply.model_sync_success', count=count)}{RESET}\n\n"
                )
            except Exception as exc:
                sys.stdout.write(
                    f"{YELLOW}⚠ {t('apply.model_sync_failed', err=str(exc))}{RESET}\n\n"
                )
            continue

        if chosen == "__custom__":
            custom_id = prompt_text(
                t("apply.model_custom_prompt"),
                allow_empty=False,
            )
            if not custom_id:
                continue
            return custom_id

        return chosen


def run_interactive_apply(
    pre_target: str | None = None,
    pre_provider: str | None = None,
) -> int:
    """Guided Apply flow with Esc step-back and Enter final confirmation."""
    sys.stdout.write(f"\n{BOLD}{t('apply.title')}{RESET}\n")

    installed = detect_installed_adapters()
    state_store = StateStore()
    current_state = state_store.load()
    pv_store = ProviderStore()
    acc_store = AccountStore()

    target_names: list[str] = (
        [t_name.strip().lower() for t_name in pre_target.split(",") if t_name.strip()]
        if pre_target
        else []
    )
    mode: str = "provider"
    chosen_account: str | None = None
    provider_name: str | None = pre_provider
    chosen_model: str | None = None
    gate: str = "now"
    opt_fast: bool | None = None
    opt_web_search: bool | None = None
    opt_dry_run: bool = False
    opt_no_save: bool = False
    opt_wire_api: str | None = None

    step = "TARGETS" if not pre_target else "MODE"

    while True:
        if step == "TARGETS":
            target_choices: list[Choice] = []
            for t_name in sorted(installed.keys()):
                ts = current_state.targets.get(t_name)
                if ts and ts.active_name:
                    act_str = f"({ts.active_type}:{ts.active_name})"
                else:
                    act_str = "(default)"
                target_choices.append(Choice(t_name, t_name, description=act_str))

            if not target_choices:
                sys.stdout.write(f"{YELLOW}{t('apply.no_targets')}{RESET}\n")
                return 1

            selected_targets = checkbox(
                t("apply.target_prompt"),
                target_choices,
                allow_empty=False,
            )
            if not selected_targets:
                return None
            target_names = [str(x) for x in selected_targets]
            step = "MODE"

        elif step == "MODE":
            targets_str = ", ".join(target_names)
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
                step = "TARGETS" if not pre_target else "EXIT"
                if step == "EXIT":
                    return 0
                continue
            mode = res_mode
            if mode == "reset":
                step = "CONFIRM_EXECUTE"
            elif mode == "account":
                step = "ACCOUNT"
            else:
                step = "PROVIDER"

        elif step == "ACCOUNT":
            saved_accounts = acc_store.list_all()
            if not saved_accounts:
                sys.stdout.write(f"{YELLOW}{t('apply.account_none')}{RESET}\n")
                step = "MODE"
                continue

            acc_choices = [
                Choice(f"{a.target}:{a.name}", a.name, description=f"({a.target})")
                for a in saved_accounts
            ]
            chosen_acc = select(t("apply.account_prompt"), acc_choices)
            if not chosen_acc:
                step = "MODE"
                continue
            chosen_account = chosen_acc
            step = "CONFIRM_EXECUTE"

        elif step == "PROVIDER":
            providers = pv_store.list_all()
            if not providers:
                sys.stdout.write(f"{YELLOW}{t('apply.provider_none')}{RESET}\n")
                return 1

            if pre_provider:
                provider_name = pre_provider
                step = "MODEL"
                continue

            pv_choices: list[Choice] = []
            for pv in providers:
                model_hint = f" | {pv.default_model}" if pv.default_model else ""
                desc = f"({pv.protocol}{model_hint})"
                pv_choices.append(Choice(pv.name, pv.name, description=desc))

            chosen_pv = select(t("apply.provider_prompt"), pv_choices)
            if not chosen_pv:
                step = "MODE"
                continue
            provider_name = chosen_pv
            step = "MODEL"

        elif step == "MODEL":
            assert provider_name is not None
            chosen_model_action = _prompt_select_model(
                provider_name,
                include_keep=True,
                allow_custom=True,
            )
            if not chosen_model_action:
                step = "PROVIDER" if not pre_provider else "MODE"
                continue

            if chosen_model_action == "__keep__":
                chosen_model = None
            else:
                chosen_model = chosen_model_action

            step = "FORK_GATE"

        elif step == "FORK_GATE":
            has_codex = "codex" in target_names
            gate_adv_desc = (
                t("apply.gate_adv_desc")
                if has_codex
                else t("apply.gate_adv_desc_non_codex")
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
                step = "MODEL"
                continue
            gate = res_gate
            if gate == "advanced":
                step = "ADVANCED_OPTIONS"
            else:
                opt_fast = None
                opt_web_search = None
                opt_dry_run = False
                opt_no_save = False
                opt_wire_api = None
                step = "CONFIRM_EXECUTE"

        elif step == "ADVANCED_OPTIONS":
            has_codex = "codex" in target_names
            flag_choices = []
            if has_codex:
                codex_tag = " (Codex)" if len(target_names) > 1 else ""
                flag_choices.append(
                    Choice(
                        f"{t('apply.flag_fast')}{codex_tag}",
                        "fast",
                        t("apply.flag_fast_desc"),
                        checked=bool(opt_fast),
                    )
                )
                flag_choices.append(
                    Choice(
                        f"{t('apply.flag_web_search')}{codex_tag}",
                        "web_search",
                        t("apply.flag_web_search_desc"),
                        checked=bool(opt_web_search),
                    )
                )
            flag_choices.extend(
                [
                    Choice(
                        t("apply.flag_dry_run"),
                        "dry_run",
                        t("apply.flag_dry_run_desc"),
                        checked=bool(opt_dry_run),
                    ),
                    Choice(
                        t("apply.flag_no_save"),
                        "no_save",
                        t("apply.flag_no_save_desc"),
                        checked=bool(opt_no_save),
                    ),
                ]
            )
            selected_flags = checkbox(
                t("apply.adv_prompt"),
                flag_choices,
                allow_empty=True,
            )
            if selected_flags is None:
                step = "FORK_GATE"
                continue

            if has_codex:
                opt_fast = True if "fast" in selected_flags else None
                opt_web_search = True if "web_search" in selected_flags else None
            else:
                opt_fast = None
                opt_web_search = None
            opt_dry_run = "dry_run" in selected_flags
            opt_no_save = "no_save" in selected_flags

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
                    continue
                opt_wire_api = wire_choice if wire_choice != "__none__" else None
            else:
                opt_wire_api = None

            step = "CONFIRM_EXECUTE"

        elif step == "CONFIRM_EXECUTE":
            targets_str = ",".join(target_names)
            cmd_parts = ["xpx", "apply", targets_str]
            summary_lines: list[str] = [f"Targets:     {targets_str}"]

            if mode == "reset":
                cmd_parts.append("--clear")
                summary_lines.append(f"Action:      {t('apply.mode_reset')}")
                args = argparse.Namespace(
                    target=targets_str,
                    provider_spec=None,
                    all=False,
                    account=None,
                    model=None,
                    clear=True,
                    reset=False,
                    dry_run=False,
                    no_save=False,
                    fast=None,
                    wire_api=None,
                    web_search=None,
                    header=[],
                )
            elif mode == "account":
                cmd_parts.extend(["--account", str(chosen_account)])
                summary_lines.append(f"Account:     {chosen_account}")
                args = argparse.Namespace(
                    target=targets_str,
                    provider_spec=None,
                    all=False,
                    account=chosen_account,
                    model=None,
                    clear=False,
                    reset=False,
                    dry_run=False,
                    no_save=False,
                    fast=None,
                    wire_api=None,
                    web_search=None,
                    header=[],
                )
            else:
                spec_str = str(provider_name)
                if chosen_model:
                    spec_str = f"{provider_name}/{chosen_model}"
                cmd_parts.append(spec_str)
                summary_lines.append(f"Provider:    {spec_str}")

                flags_info: list[str] = []
                has_codex = "codex" in target_names
                multi = len(target_names) > 1
                codex_tag = " (Codex)" if multi else ""
                if opt_fast and has_codex:
                    cmd_parts.append("--fast")
                    flags_info.append(f"--fast{codex_tag}")
                if opt_web_search and has_codex:
                    cmd_parts.append("--web-search")
                    flags_info.append(f"--web-search{codex_tag}")
                if opt_wire_api and has_codex:
                    cmd_parts.extend(["--wire-api", opt_wire_api])
                    flags_info.append(f"--wire-api {opt_wire_api}{codex_tag}")
                if opt_dry_run:
                    cmd_parts.append("--dry-run")
                    flags_info.append("--dry-run")
                if opt_no_save:
                    cmd_parts.append("--no-save")
                    flags_info.append("--no-save")

                if flags_info:
                    summary_lines.append(f"Options:     {', '.join(flags_info)}")

                args = argparse.Namespace(
                    target=targets_str,
                    provider_spec=spec_str,
                    all=False,
                    account=None,
                    model=chosen_model,
                    clear=False,
                    reset=False,
                    dry_run=opt_dry_run,
                    no_save=opt_no_save,
                    fast=opt_fast if has_codex else None,
                    wire_api=opt_wire_api if has_codex else None,
                    web_search=opt_web_search if has_codex else None,
                    header=[],
                )

            native_cmd = " ".join(cmd_parts)
            summary_lines.append(f"Command:     {native_cmd}")

            card_text = render_card(t("apply.confirm_card_title"), summary_lines)
            sys.stdout.write(f"\n{card_text}")
            sys.stdout.flush()

            confirmed = _confirm_action(t("apply.confirm_prompt"))
            if not confirmed:
                if mode == "reset":
                    step = "MODE"
                elif mode == "account":
                    step = "ACCOUNT"
                elif gate == "advanced":
                    step = "ADVANCED_OPTIONS"
                else:
                    step = "FORK_GATE"
                continue

            rc = run_apply(args)
            return rc


def run_interactive_providers() -> int:
    """Providers management wizard."""
    while True:
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
            if not providers:
                sys.stdout.write(f"{YELLOW}{t('apply.provider_none')}{RESET}\n")
            else:
                for pv in providers:
                    sys.stdout.write(f"Syncing models for {pv.name}...\n")
                    run_models_sync(argparse.Namespace(provider=pv.name, force=False))
                sys.stdout.write(f"{GREEN}✔ All models synchronized.{RESET}\n")
                _wait_enter()


def _wizard_add_provider() -> None:
    """Step-by-step wizard to add a new provider with Esc back and Enter confirm."""
    sys.stdout.write(f"\n{BOLD}{t('pv.add_title')}{RESET}\n")

    name: str | None = None
    base_url: str | None = None
    protocol: str = "openai"
    key: str | None = None
    default_model: str | None = None

    step = 1
    while True:
        if step == 1:
            res_name = prompt_text(
                t("pv.name_prompt"),
                default=name or "",
                allow_empty=False,
            )
            if not res_name:
                return
            name = res_name
            step = 2

        elif step == 2:
            assert name is not None
            preset = KNOWN_PROVIDER_PRESETS.get(name.lower(), {})
            def_url = base_url or preset.get("base_url", "")
            res_url = prompt_text(
                t("pv.url_prompt", name=name),
                default=def_url,
                allow_empty=False,
            )
            if not res_url:
                step = 1
                continue
            base_url = res_url
            step = 3

        elif step == 3:
            assert name is not None
            preset = KNOWN_PROVIDER_PRESETS.get(name.lower(), {})
            def_proto = preset.get("protocol", "openai")
            res_proto = select(
                t("pv.proto_prompt", name=name),
                [
                    Choice("openai (OpenAI API)", "openai"),
                    Choice("anthropic (Anthropic Claude)", "anthropic"),
                ],
                default_index=0 if def_proto == "openai" else 1,
            )
            if not res_proto:
                step = 2
                continue
            protocol = res_proto
            step = 4

        elif step == 4:
            assert name is not None
            res_key = prompt_text(
                t("pv.key_prompt", name=name),
                default=key or "",
                password=True,
                allow_empty=True,
            )
            if res_key is None:
                step = 3
                continue
            key = res_key
            step = 5

        elif step == 5:
            assert name is not None
            preset = KNOWN_PROVIDER_PRESETS.get(name.lower(), {})
            from lib.xpx.models.catalog import load_shared_catalog_data

            shared_models = load_shared_catalog_data().get("models") or {}
            def_model = default_model or preset.get("model", "")

            m_choices: list[Choice] = []
            if def_model:
                m_choices.append(
                    Choice(f"🌟 {def_model}", def_model, description="[推荐预设]")
                )
            m_choices.append(
                Choice("（无）留空稍后配置", "__none__", description="不指定默认模型")
            )
            m_choices.append(
                Choice(
                    f"✏️  {t('apply.model_custom')}",
                    "__custom__",
                    description=t("apply.model_custom_desc"),
                )
            )

            cand_list = [
                "deepseek-reasoner",
                "deepseek-chat",
                "deepseek-v4-flash",
                "claude-3-7-sonnet-latest",
                "claude-3-5-sonnet-latest",
                "gpt-4o",
                "gpt-4o-mini",
                "o3-mini",
                "gemini-2.5-pro",
                "gemini-2.5-flash",
                "qwen-2.5-coder-32b",
                "qwen-max",
            ]
            for mid in cand_list:
                if mid == def_model:
                    continue
                info = shared_models.get(mid) or {}
                dname = info.get("display_name") or mid
                m_choices.append(Choice(mid, mid, description=dname))

            chosen_m = select(t("pv.model_prompt", name=name), m_choices)
            if not chosen_m:
                step = 4
                continue

            if chosen_m == "__none__":
                default_model = ""
            elif chosen_m == "__custom__":
                res_custom = prompt_text(
                    t("apply.model_custom_prompt"), allow_empty=True
                )
                if res_custom is None:
                    continue
                default_model = res_custom
            else:
                default_model = chosen_m
            step = 6

        elif step == 6:
            native_cmd = f"xpx add {name} {base_url} --protocol {protocol}"
            if key:
                native_cmd += " --key sk-••••"
            if default_model:
                native_cmd += f" --default-model {default_model}"

            sys.stdout.write(
                f"\n{BOLD}┌── {t('pv.confirm_add_title')} "
                f"──────────────────────────────┐{RESET}\n"
            )
            sys.stdout.write(f"│  Name:      {name:<43}│\n")
            sys.stdout.write(f"│  Base URL:  {base_url:<43}│\n")
            sys.stdout.write(f"│  Protocol:  {protocol:<43}│\n")
            key_preview = "sk-••••••••" if key else "(none)"
            sys.stdout.write(f"│  API Key:   {key_preview:<43}│\n")
            model_preview = default_model or "(none)"
            sys.stdout.write(f"│  Model:     {model_preview:<43}│\n")
            sys.stdout.write(f"│  Command:   {native_cmd:<43}│\n")
            sys.stdout.write(
                f"{BOLD}└────────────────────────────────────────────────────────┘{RESET}\n"
            )

            confirmed = _confirm_action(t("pv.confirm_add_prompt", name=name))
            if not confirmed:
                step = 5
                continue

            args = argparse.Namespace(
                name=name,
                base_url=base_url,
                key=key,
                key_stdin=False,
                default_model=default_model or None,
                protocol=protocol,
            )
            run_add(args)
            sys.stdout.write(f"\n{GREEN}{t('pv.add_success', name=name)}{RESET}\n")
            _wait_enter()
            return


def _wizard_manage_providers(providers: list[Any]) -> None:
    """Manage an individual provider."""
    if not providers:
        sys.stdout.write(f"{YELLOW}{t('apply.provider_none')}{RESET}\n")
        return

    while True:
        pv_choices = [
            Choice(
                pv.name,
                pv.name,
                description=f"({pv.protocol} | {pv.base_url})",
            )
            for pv in providers
        ]
        target_pv = select(t("pv.select_manage"), pv_choices)
        if not target_pv:
            return

        sys.stdout.write(f"\n{BOLD}{t('pv.details_title', name=target_pv)}{RESET}\n")
        run_show(argparse.Namespace(name=target_pv))

        actions = [
            Choice(t("pv.action_auth_set"), "auth_set"),
            Choice(t("pv.action_model_set"), "model_set"),
            Choice(t("pv.action_sync"), "sync"),
            Choice(t("pv.action_test"), "test"),
            Choice(t("pv.action_delete"), "delete"),
            Choice(t("ui.back"), "back"),
        ]
        sub_action = select(f"[{target_pv}]", actions)
        if not sub_action or sub_action == "back":
            continue

        if sub_action == "auth_set":
            new_key = prompt_text(
                f"[{target_pv}] API Key",
                password=True,
                allow_empty=False,
            )
            if new_key and _confirm_action(f"Update API Key for '{target_pv}'?"):
                run_auth_set(
                    argparse.Namespace(name=target_pv, key=new_key, key_stdin=False)
                )
                _wait_enter()
        elif sub_action == "model_set":
            chosen_m = _prompt_select_model(target_pv, include_keep=False)
            if chosen_m:
                pv_store = ProviderStore()
                pv = pv_store.require(target_pv)
                pv.default_model = chosen_m
                upd_msg = t("pv.model_updated", name=target_pv, model=chosen_m)
                sys.stdout.write(f"\n{GREEN}{upd_msg}{RESET}\n")
                _wait_enter()
        elif sub_action == "sync":
            if _confirm_action(f"Synchronize remote models for '{target_pv}'?"):
                run_models_sync(argparse.Namespace(provider=target_pv, force=False))
                _wait_enter()
        elif sub_action == "test":
            run_test(argparse.Namespace(provider=target_pv, all=False))
            _wait_enter()
        elif sub_action == "delete":
            del_confirmed = _confirm_action(
                t("pv.delete_confirm", name=target_pv),
                default_confirm=False,
            )
            if del_confirmed:
                run_delete(argparse.Namespace(name=target_pv, full=True, dry_run=False))
                _wait_enter()
                return


def run_interactive_doctor_ping() -> int:
    """Doctor health check, connectivity testing, and prompt ping wizard."""
    while True:
        sys.stdout.write(f"\n{BOLD}{t('doc.title')}{RESET}\n")

        choices = [
            Choice(t("doc.doctor"), "doctor"),
            Choice(t("doc.doctor_fix"), "doctor_fix"),
            Choice(t("doc.test"), "test"),
            Choice(t("doc.ping"), "ping"),
            Choice(t("ui.back_menu"), "back"),
        ]
        action = select(t("pv.action_prompt"), choices)
        if not action or action == "back":
            return 0

        if action == "doctor":
            run_doctor(argparse.Namespace(fix=False))
            _wait_enter()
        elif action == "doctor_fix":
            if _confirm_action(t("doc.fix_confirm")):
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
                for p in selected_pvs:
                    run_test(argparse.Namespace(provider=p, all=False))
                _wait_enter()
        elif action == "ping":
            installed = detect_installed_adapters()
            if not installed:
                sys.stdout.write(f"{YELLOW}{t('apply.no_targets')}{RESET}\n")
                _wait_enter()
                continue
            target = select(t("doc.ping_client_prompt"), list(installed.keys()))
            if target:
                prompt_str = prompt_text(
                    t("doc.ping_prompt"),
                    default="say hi",
                )
                if prompt_str and _confirm_action(t("doc.ping_confirm", target=target)):
                    run_ping(
                        argparse.Namespace(
                            target=target,
                            provider_spec=None,
                            prompt=prompt_str,
                            timeout=30,
                            all=False,
                        )
                    )
                    _wait_enter()


def run_interactive_models() -> int:
    """Models list and sync wizard."""
    while True:
        sys.stdout.write(f"\n{BOLD}{t('models.title')}{RESET}\n")
        pv_store = ProviderStore()
        providers = pv_store.list_all()
        if not providers:
            sys.stdout.write(f"{YELLOW}{t('apply.provider_none')}{RESET}\n")
            return 0

        pv_name = select(
            t("models.select_pv"),
            [pv.name for pv in providers],
        )
        if not pv_name:
            return 0

        sub_action = select(
            f"[{pv_name}]",
            [
                Choice(t("models.list"), "list"),
                Choice(t("models.sync"), "sync"),
                Choice(t("ui.back"), "back"),
            ],
        )
        if sub_action == "list":
            run_models_list(argparse.Namespace(provider=pv_name, remote=False))
            _wait_enter()
        elif sub_action == "sync" and _confirm_action(
            t("models.sync_confirm", name=pv_name)
        ):
            run_models_sync(argparse.Namespace(provider=pv_name, force=False))
            _wait_enter()


def run_interactive_accounts() -> int:
    """OAuth and session account management wizard."""
    while True:
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
                    run_account_login(
                        argparse.Namespace(target=target, name=alias or None)
                    )
                    _wait_enter()
        elif action == "usage":
            run_account_usage(argparse.Namespace(target="agy", name=None))
            _wait_enter()


def run_interactive_status() -> int | None:
    """Displays global status dashboard and allows instant action."""
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
