from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from lib.common.errors import SwitchError
from lib.xpx.store import get_xpx_home
from lib.xpx.store.catalog_store import CatalogStore, ModelMetadata, ProviderCatalog
from lib.xpx.store.provider_store import ProviderStore

_LOCAL_CATALOG_CACHE: dict[str, Any] | None = None


def find_builtin_catalog_file() -> Path | None:
    # 1. PyInstaller bundled path
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        cand = Path(meipass) / "data" / "model-catalog.json"
        if cand.is_file():
            return cand

    # 2. Source tree path (relative to this file: src/lib/xpx/models/catalog.py)
    cand = Path(__file__).resolve().parents[4] / "data" / "model-catalog.json"
    if cand.is_file():
        return cand

    # 3. Cache under ~/.xpx/
    cand = get_xpx_home() / "shared_model_catalog.json"
    if cand.is_file():
        return cand

    return None


def load_shared_catalog_data() -> dict[str, Any]:
    global _LOCAL_CATALOG_CACHE
    if _LOCAL_CATALOG_CACHE is not None:
        return _LOCAL_CATALOG_CACHE

    path = find_builtin_catalog_file()
    if path and path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                _LOCAL_CATALOG_CACHE = raw
                return raw
        except Exception:
            pass

    _LOCAL_CATALOG_CACHE = {"models": {}, "aliases": {}}
    return _LOCAL_CATALOG_CACHE


def find_model_entry(model_id: str) -> dict[str, Any]:
    data = load_shared_catalog_data()
    models = data.get("models") or {}
    aliases = data.get("aliases") or {}

    clean_id = model_id.strip()
    if clean_id in models:
        return dict(models[clean_id])

    canonical = aliases.get(clean_id)
    if canonical and canonical in models:
        return dict(models[canonical])

    # Case-insensitive or suffix search
    lower_id = clean_id.lower()
    for ak, av in aliases.items():
        ak_lower = ak.lower()
        matched = (
            ak_lower == lower_id
            or clean_id.endswith(f"/{ak}")
            or lower_id.endswith(f"/{ak_lower}")
        )
        if matched and av in models:
            return dict(models[av])

    for k, v in models.items():
        if k.lower() == lower_id or clean_id.endswith(f"/{k}"):
            return dict(v)

    return {}


def enrich_model_metadata(
    model_id: str,
    existing: ModelMetadata | None = None,
    force_reset: bool = False,
) -> ModelMetadata:
    """Enrich a model ID with metadata from the shared catalog."""
    entry = find_model_entry(model_id)

    raw_levels = entry.get("reasoning_levels") or []
    levels: list[str] = []
    for item in raw_levels:
        if isinstance(item, str):
            levels.append(item)
        elif isinstance(item, dict) and "effort" in item:
            levels.append(str(item["effort"]))

    default_effort = entry.get("reasoning_default")
    context_win = int(entry.get("context_window") or 128000)
    max_tokens = int(entry.get("max_output_tokens") or 8192)
    display_name = str(entry.get("display_name") or model_id)
    modalities = list(entry.get("input_modalities") or ["text"])

    if existing and not force_reset:
        return ModelMetadata(
            id=model_id,
            display_name=existing.display_name or display_name,
            context_window=existing.context_window or context_win,
            max_output_tokens=existing.max_output_tokens or max_tokens,
            supported_reasoning_levels=(existing.supported_reasoning_levels or levels),
            default_reasoning_level=(
                existing.default_reasoning_level or default_effort
            ),
            input_modalities=existing.input_modalities or modalities,
        )

    return ModelMetadata(
        id=model_id,
        display_name=display_name,
        context_window=context_win,
        max_output_tokens=max_tokens,
        supported_reasoning_levels=levels,
        default_reasoning_level=default_effort,
        input_modalities=modalities,
    )


def resolve_model_effort(
    provider_name: str,
    model_id: str | None,
    explicit_effort: str | None = None,
) -> str | None:
    """Resolve the effective reasoning effort for a model.

    Resolution order:
    1. Explicit effort passed directly (CLI flag or target override)
    2. Provider's cached catalog default_reasoning_level
    3. Provider's cached catalog supported_reasoning_levels (prefers 'high')
    4. Authoritative shared model-catalog default_reasoning_level
    5. Authoritative shared model-catalog supported_reasoning_levels
    """
    if explicit_effort:
        clean = str(explicit_effort).strip()
        if clean:
            return clean
    if not model_id:
        return None

    clean_id = model_id.strip()
    prefix = f"{provider_name}/"
    if clean_id.startswith(prefix):
        clean_id = clean_id[len(prefix) :].strip()

    # 1. Try provider's cached catalog
    try:
        cat = CatalogStore().get(provider_name)
        if cat and clean_id in cat.models:
            meta = cat.models[clean_id]
            if meta.default_reasoning_level:
                return meta.default_reasoning_level
            if meta.supported_reasoning_levels:
                levels = [
                    lvl
                    for lvl in meta.supported_reasoning_levels
                    if lvl and str(lvl).lower() not in ("none", "off")
                ]
                if levels:
                    return "high" if "high" in levels else levels[-1]
    except Exception:
        pass

    # 2. Fallback to authoritative shared catalog metadata
    try:
        meta = enrich_model_metadata(clean_id)
        if meta.default_reasoning_level:
            return meta.default_reasoning_level
        if meta.supported_reasoning_levels:
            levels = [
                lvl
                for lvl in meta.supported_reasoning_levels
                if lvl and str(lvl).lower() not in ("none", "off")
            ]
            if levels:
                return "high" if "high" in levels else levels[-1]
    except Exception:
        pass

    return None


def get_consolidated_provider_models(
    provider_name: str,
    applied_model: str | None = None,
    previous_model: str | None = None,
    extra_models: list[str] | dict[str, Any] | None = None,
) -> dict[str, ModelMetadata]:
    """Retrieve and consolidate all effective models for a provider.

    Combines:
    - Provider's cached catalog models
    - Applied model (current target selection)
    - Previous model
    - Provider's configured default model
    - Any client-specific extra models
    - Metadata enrichment from the shared catalog
    - Standard fallback models if empty
    """
    cat_store = CatalogStore()
    catalog = cat_store.get(provider_name)
    models_map: dict[str, ModelMetadata] = {}

    if catalog and catalog.models:
        for mid, m_meta in catalog.models.items():
            if not m_meta.supported_reasoning_levels:
                models_map[mid] = enrich_model_metadata(mid, existing=m_meta)
            else:
                models_map[mid] = m_meta

    prefix = f"{provider_name}/"

    def _strip_and_add(raw_name: str | None) -> str | None:
        if not raw_name or not str(raw_name).strip():
            return None
        clean = str(raw_name).strip()
        if clean.startswith(prefix):
            clean = clean[len(prefix) :].strip()
        if not clean:
            return None
        if clean not in models_map:
            models_map[clean] = enrich_model_metadata(clean)
        elif not models_map[clean].supported_reasoning_levels:
            models_map[clean] = enrich_model_metadata(clean, existing=models_map[clean])
        return clean

    _strip_and_add(applied_model)
    _strip_and_add(previous_model)

    try:
        pv = ProviderStore().get(provider_name)
        if pv and pv.default_model:
            _strip_and_add(pv.default_model)
    except Exception:
        pass

    if extra_models:
        for em in extra_models:
            _strip_and_add(em)

    if not models_map:
        try:
            shared = load_shared_catalog_data()
            shared_models = shared.get("models") or {}
            for mid in shared_models:
                models_map[mid] = enrich_model_metadata(mid)
        except Exception:
            pass

    if not models_map:
        for mid in ("gpt-5.4", "gpt-5.5", "deepseek-v4-flash"):
            models_map[mid] = enrich_model_metadata(mid)

    return models_map


def refresh_active_adapters(provider_name: str) -> None:
    """Refresh model catalog across all active and detected target adapters."""
    try:
        from lib.xpx.adapters.registry import get_all_adapters

        for adp in get_all_adapters().values():
            try:
                if adp.detect():
                    st = adp.get_status()
                    if st.active_type == "provider" and st.active_name == provider_name:
                        adp.refresh_catalog(provider_name)
            except Exception:
                pass
    except Exception:
        pass


def update_model_preference(
    provider_name: str,
    model_id: str,
    *,
    is_default: bool = False,
    context: int | None = None,
    max_output: int | None = None,
    effort: str | None = None,
) -> ModelMetadata:
    """Update settings for a model and optionally set as provider default."""
    pv_store = ProviderStore()
    pv = pv_store.require(provider_name)

    cat_store = CatalogStore()
    cat = cat_store.get(provider_name)
    if cat is None:
        cat = ProviderCatalog(provider=provider_name, updated_at="")

    existing = cat.models.get(model_id)
    meta = enrich_model_metadata(model_id, existing=existing)

    if context is not None:
        if context <= 0:
            raise SwitchError("context window must be a positive integer")
        meta.context_window = context

    if max_output is not None:
        if max_output <= 0:
            raise SwitchError("max output tokens must be a positive integer")
        meta.max_output_tokens = max_output

    if effort is not None:
        clean_effort = effort.strip().lower()
        if (
            meta.supported_reasoning_levels
            and clean_effort not in meta.supported_reasoning_levels
        ):
            avail = ", ".join(meta.supported_reasoning_levels)
            raise SwitchError(
                f"unsupported reasoning level '{effort}'. Supported: {avail}"
            )
        meta.default_reasoning_level = clean_effort

    cat.models[model_id] = meta
    cat_store.save(cat)

    if is_default:
        pv.default_model = model_id
        pv_store.save(pv)

    # Refresh active target adapter catalogs if applicable
    refresh_active_adapters(provider_name)

    return meta
