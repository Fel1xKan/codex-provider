from __future__ import annotations

from typing import Any

from lib.xpx.models.catalog import add_model_to_catalog
from lib.xpx.models.sync import fetch_remote_models, sync_provider_models
from lib.xpx.store.catalog_store import CatalogStore
from lib.xpx.store.provider_store import ProviderStore


def run_models_set(args: Any) -> int:
    """Add or update a model in a provider's catalog.

    `add` and `set` were separate commands with different flags even though
    `add_model_to_catalog` always upserted. One command with an explicit
    `<provider> <model>` order removes both the duplication and the guesswork
    about which positional is which.
    """
    provider = args.provider
    model = args.model
    display_name = getattr(args, "display_name", None)
    is_default = getattr(args, "default", False)
    context = getattr(args, "context", None)
    max_output = getattr(args, "max_output", None)
    effort = getattr(args, "effort", None)
    overwrite = getattr(args, "overwrite", False)

    modalities_raw = getattr(args, "modalities", None)
    modalities: list[str] | None = None
    if modalities_raw:
        modalities = [m.strip() for m in str(modalities_raw).split(",") if m.strip()]

    meta, is_created = add_model_to_catalog(
        provider,
        model,
        display_name=display_name,
        context=context,
        max_output=max_output,
        effort=effort,
        modalities=modalities,
        is_default=is_default,
        overwrite=overwrite,
    )

    details: list[str] = []
    if is_default:
        details.append("marked as default")
    if meta.display_name and meta.display_name != meta.id:
        details.append(f"name='{meta.display_name}'")
    if meta.context_window:
        details.append(f"context={meta.context_window}")
    if meta.max_output_tokens:
        details.append(f"max_output={meta.max_output_tokens}")
    if meta.supported_reasoning_levels:
        details.append(f"effort=[{', '.join(meta.supported_reasoning_levels)}]")
    if meta.input_modalities and meta.input_modalities != ["text"]:
        details.append(f"modalities=[{', '.join(meta.input_modalities)}]")

    action_word = "Added" if is_created else "Updated"
    detail_str = f" ({', '.join(details)})" if details else ""
    print(
        f"\u2714 {action_word} model '{meta.id}' for provider '{provider}'{detail_str}."
    )
    return 0


def run_models_sync(args: Any) -> int:
    provider = args.provider
    force = getattr(args, "force", False)
    cat = sync_provider_models(provider, force=force)
    print(f"✔ Synced {len(cat.models)} models for '{provider}'.")
    return 0


def run_models_list(args: Any) -> int:
    provider = getattr(args, "provider", None)
    remote = getattr(args, "remote", False)
    pv_store = ProviderStore()
    cat_store = CatalogStore()

    if remote:
        if not provider:
            providers = pv_store.list_all()
        else:
            providers = [pv_store.require(provider)]

        for p in providers:
            print(f"Remote models for '{p.name}':")
            model_ids = fetch_remote_models(p.base_url, p.api_key, protocol=p.protocol)
            if not model_ids:
                print("  (no models returned)")
            for mid in model_ids:
                print(f"  - {mid}")
        return 0

    if provider:
        cat = cat_store.get(provider)
        if not cat or not cat.models:
            print(
                f"No cached models for '{provider}'. "
                f"Run 'xpx models sync {provider}' to synchronize."
            )
            return 0

        header = f"{'MODEL ID':<35} {'EFFORT':<25} {'CONTEXT':<10}"
        print(f"Models for '{provider}':")
        print(header)
        print("-" * len(header))
        for mid in sorted(cat.models.keys()):
            meta = cat.models[mid]
            levels = ", ".join(meta.supported_reasoning_levels) or "-"
            print(f"{meta.id:<35} {levels:<25} {meta.context_window:<10}")
        return 0

    # All providers
    all_pvs = pv_store.list_all()
    if not all_pvs:
        print("No providers configured.")
        return 0

    has_any = False
    for p in all_pvs:
        cat = cat_store.get(p.name)
        if cat and cat.models:
            has_any = True
            print(f"[{p.name}] ({len(cat.models)} models)")
            for mid in sorted(cat.models.keys())[:10]:
                print(f"  - {mid}")
            if len(cat.models) > 10:
                more_cnt = len(cat.models) - 10
                print(
                    f"  ... and {more_cnt} more "
                    f"(run 'xpx models list {p.name}' for all)"
                )
    if not has_any:
        print("No cached models. Run 'xpx models sync <provider>' to import models.")
    return 0
