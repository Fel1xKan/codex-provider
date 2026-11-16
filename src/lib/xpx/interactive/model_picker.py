"""Model selection prompt shared by the apply flow and the provider wizards."""

from __future__ import annotations

import sys
from typing import Any

from lib.xpx.i18n import t
from lib.xpx.interactive.selector import (
    CYAN,
    GREEN,
    RESET,
    YELLOW,
    Choice,
    prompt_text,
    select,
)

UNIVERSAL_CURATED_MODELS = [
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


def prompt_select_model(
    provider_name: str,
    *,
    include_keep: bool = True,
    allow_custom: bool = True,
) -> str | None:
    """Interactive model selector with cached, popular, sync, and custom options."""
    from lib.xpx.store.catalog_store import CatalogStore
    from lib.xpx.store.provider_store import ProviderStore

    pv_store = ProviderStore()
    cat_store = CatalogStore()

    while True:
        pv = pv_store.require(provider_name)
        cat = cat_store.get(provider_name)
        shared_models = load_shared_models()
        choices = _build_choices(
            pv,
            provider_name,
            cat.models if cat else {},
            shared_models,
            include_keep=include_keep,
            allow_custom=allow_custom,
        )
        chosen = select(
            t("apply.model_prompt", provider=provider_name),
            choices,
            page_size=10,
        )
        if not chosen:
            return None
        if chosen == "__sync_remote__":
            _sync_remote_models(provider_name, pv.base_url)
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


def load_shared_models() -> dict[str, Any]:
    """Curated catalog entries shared by every provider, keyed by model id."""
    from lib.xpx.models.catalog import load_shared_catalog_data

    return load_shared_catalog_data().get("models") or {}


def _build_choices(
    pv: Any,
    provider_name: str,
    cached_models: dict[str, Any],
    shared_models: dict[str, Any],
    *,
    include_keep: bool,
    allow_custom: bool,
) -> list[Choice]:
    choices: list[Choice] = []
    seen_ids: set[str] = set()
    default_choice = _default_model_choice(pv, cached_models)
    if default_choice is not None:
        choices.append(default_choice)
        seen_ids.add(pv.default_model)
    if include_keep:
        choices.append(
            Choice(
                f"📌 {t('apply.model_keep')}",
                "__keep__",
                description=t("apply.model_keep_desc"),
            )
        )
    choices.append(
        Choice(
            f"🔄 {t('apply.model_sync_remote')}",
            "__sync_remote__",
            description=t("apply.model_sync_remote_desc"),
        )
    )
    choices.extend(_cached_choices(cached_models, seen_ids))
    choices.extend(
        _curated_choices(_curated_priority(pv, provider_name), shared_models, seen_ids)
    )
    choices.extend(_shared_choices(shared_models, seen_ids))
    if allow_custom:
        choices.append(
            Choice(
                f"✏️  {t('apply.model_custom')}",
                "__custom__",
                description=t("apply.model_custom_desc"),
            )
        )
    return choices


def _default_model_choice(pv: Any, cached_models: dict[str, Any]) -> Choice | None:
    if not pv.default_model:
        return None
    from lib.xpx.models.catalog import enrich_model_metadata

    meta = cached_models.get(pv.default_model) or enrich_model_metadata(
        pv.default_model
    )
    suffix = (
        f" - {meta.display_name}"
        if meta.display_name and meta.display_name != pv.default_model
        else ""
    )
    desc = f"[{t('apply.model_default_tag')}]{suffix}"
    return Choice(f"🌟 {pv.default_model}", pv.default_model, description=desc)


def _cached_choices(cached_models: dict[str, Any], seen_ids: set[str]) -> list[Choice]:
    choices: list[Choice] = []
    for mid, meta in cached_models.items():
        if mid in seen_ids:
            continue
        seen_ids.add(mid)
        ctx_k = f"{meta.context_window // 1000}k" if meta.context_window else ""
        parts: list[str] = []
        if meta.display_name and meta.display_name != mid:
            parts.append(meta.display_name)
        if ctx_k:
            parts.append(ctx_k)
        choices.append(Choice(mid, mid, description=" | ".join(parts)))
    return choices


def _curated_priority(pv: Any, provider_name: str) -> list[str]:
    name = provider_name.lower()
    proto = pv.protocol.lower()
    priority: list[str] = []
    if proto == "anthropic" or "claude" in name:
        priority.extend(
            [
                "claude-3-7-sonnet-latest",
                "claude-3-5-sonnet-latest",
                "claude-3-5-haiku-latest",
            ]
        )
    elif "deepseek" in name:
        priority.extend(["deepseek-reasoner", "deepseek-chat", "deepseek-v4-flash"])
    elif "google" in name or "gemini" in name:
        priority.extend(["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash"])
    elif "qwen" in name or "bailian" in name:
        priority.extend(["qwen-2.5-coder-32b", "qwen-max", "qwen-plus"])
    for mid in UNIVERSAL_CURATED_MODELS:
        if mid not in priority:
            priority.append(mid)
    return priority


def _curated_choices(
    priority: list[str], shared_models: dict[str, Any], seen_ids: set[str]
) -> list[Choice]:
    choices: list[Choice] = []
    for mid in priority:
        if mid in seen_ids:
            continue
        seen_ids.add(mid)
        info = shared_models.get(mid) or {}
        dname = info.get("display_name") or mid
        ctx = info.get("context_window")
        ctx_k = f"{ctx // 1000}k" if ctx else ""
        desc = f"{dname} | {ctx_k}" if ctx_k else dname
        choices.append(Choice(mid, mid, description=desc))
    return choices


def _shared_choices(shared_models: dict[str, Any], seen_ids: set[str]) -> list[Choice]:
    choices: list[Choice] = []
    for mid, info in shared_models.items():
        if mid in seen_ids:
            continue
        seen_ids.add(mid)
        dname = info.get("display_name") or mid
        choices.append(Choice(mid, mid, description=dname))
    return choices


def _sync_remote_models(provider_name: str, base_url: str) -> None:
    from lib.xpx.models.sync import sync_provider_models

    sys.stdout.write(
        f"\n{CYAN}{t('apply.model_sync_connecting', url=base_url)}{RESET}\n"
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
