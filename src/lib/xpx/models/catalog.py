from __future__ import annotations

import json
import re
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


DEFAULT_CONTEXT_WINDOW = 128000
DEFAULT_MAX_OUTPUT_TOKENS = 8192

# Gateway/regional namespaces are always a *prefix*: `cn:model`, `global:model`.
# The colon is ambiguous across providers, so every decision below is either an
# explicit allow-list or a catalog-backed check - never a blind split.
#
# Observed real-world shapes:
#   cn:deepseek-v4-flash      prefix namespace          strip namespace
#   global:z-ai/glm-5.3       prefix namespace + vendor keep vendor path
#   deepseek-chat:free        OpenRouter catalog variant keep base, keep variant
#   openai/gpt-5.2:nitro      OpenRouter routing variant keep base, drop variant
#   llama3:8b / :q4_k_m       Ollama tag                strip tag
#   llama3:8b@sha256:...      Ollama digest             strip digest
#   claude-opus-5@default     @version suffix           strip version
#   gpt-5.4[1m]               context annotation        strip annotation
#   arn:aws:bedrock:...       AWS ARN                   leave intact
KNOWN_NAMESPACES = frozenset(
    {
        "cn",
        "global",
        "us",
        "eu",
        "ap",
        "jp",
        "kr",
        "sg",
        "hk",
        "tw",
        "uk",
        "intl",
        "us-east",
        "us-west",
        "eu-west",
        "eu-central",
        "ap-east",
        "ap-south",
        "ap-southeast",
        "ap-northeast",
    }
)

# OpenRouter *catalog* variants exist as their own /models entries with their own
# metadata (usually a smaller context window and different pricing). They must
# never be silently collapsed into the paid base model.
CATALOG_VARIANTS = frozenset({"free", "batch", "thinking", "extended"})

# OpenRouter *routing* variants only affect routing; the docs state their
# metadata comes from the base model, so dropping them is safe and lossless.
ROUTING_VARIANTS = frozenset({"nitro", "floor", "exacto", "online", "auto", "random"})

# Every `:token` we are willing to treat as a *variant* (and thus show in display
# names). Anything else - Ollama tags, unknown colons - is left opaque, because
# guessing would mangle IDs like `acme:internal-model`.
_KNOWN_VARIANT_TOKENS = CATALOG_VARIANTS | ROUTING_VARIANTS

# `[1m]` / `[200k]` bracket annotations encode context-window overrides that the
# client strips before the request. They are not part of model identity.
_CONTEXT_ANNOTATION_RE = re.compile(r"\[(\d+(?:\.\d+)?)\s*([kmg]?)\]$", re.IGNORECASE)
_MULTIPLIERS = {"": 1, "k": 1_000, "m": 1_000_000, "g": 1_000_000_000}


def _split_context_annotation(model_id: str) -> tuple[str, int | None]:
    """Strip a trailing `[1m]` style context annotation.

    `gpt-5.4[1m]` -> ("gpt-5.4", 1000000)
    `vendor/model[200k]` -> ("vendor/model", 200000)
    """
    raw = model_id.strip()
    match = _CONTEXT_ANNOTATION_RE.search(raw)
    if not match:
        return raw, None

    base = raw[: match.start()].strip()
    if not base:
        return raw, None

    try:
        tokens = int(float(match.group(1)) * _MULTIPLIERS[match.group(2).lower()])
    except (ValueError, KeyError):
        return base, None
    return base, tokens


def _split_digest(model_id: str) -> tuple[str, str | None]:
    """Strip a trailing `@digest` / `@version` suffix.

    `llama3:8b@sha256:abc` -> ("llama3:8b", "sha256:abc")
    `claude-opus-5@default` -> ("claude-opus-5", "default")
    """
    raw = model_id.strip()
    if "@" not in raw:
        return raw, None

    base, digest = raw.rsplit("@", 1)
    base = base.strip()
    digest = digest.strip()
    if not base or not digest:
        return raw, None
    return base, digest


def _split_namespace(model_id: str) -> tuple[str | None, str]:
    """Split an optional known namespace prefix from a model ID.

    A known namespace is recognized purely by name. Unknown colons fall back to
    the Ollama ordering rule (`host:port/model` vs `model:tag`) so a colon after
    the last slash is never mistaken for a leading namespace.
    """
    raw = model_id.strip()
    if ":" not in raw:
        return None, raw

    # `arn:aws:bedrock:...` has empty segments; never treat it as namespaced.
    if "::" in raw:
        return None, raw

    prefix, remainder = raw.split(":", 1)
    prefix = prefix.strip()
    remainder = remainder.strip()
    if not prefix or not remainder:
        return None, raw

    # Known gateway/region namespace wins, even with a vendor path after it:
    # `global:z-ai/glm-5.3` is namespaced, not a `global` model with a tag.
    if prefix.lower() in KNOWN_NAMESPACES:
        return prefix, remainder

    # An unknown prefix is never guessed: `acme:internal-model` stays opaque,
    # and `host:8080/model` is not namespaced either.
    return None, raw


def _split_variant(model_id: str) -> tuple[str, str | None, bool]:
    """Split a trailing `:variant` suffix (OpenRouter style, Ollama tags).

    Returns `(base, variant_name, is_catalog_variant)`.

    `deepseek-chat:free` -> ("deepseek-chat", "free", True)
    `gpt-5.2:nitro`      -> ("gpt-5.2", "nitro", False)
    `llama3:8b`          -> ("llama3", "8b", False)
    """
    raw = model_id.strip()
    if ":" not in raw or "::" in raw:
        return raw, None, False

    last_colon = raw.rfind(":")
    # A colon before the last slash belongs to a namespace or host, not a tag.
    if last_colon < raw.rfind("/"):
        return raw, None, False

    base = raw[:last_colon].strip()
    variant = raw[last_colon + 1 :].strip()
    if not base or not variant:
        return raw, None, False

    return base, variant, variant.lower() in CATALOG_VARIANTS


def candidate_model_ids(
    model_id: str,
    known_ids: set[str] | None = None,
) -> list[str]:
    """Expand a model ID into catalog lookup candidates, most specific first.

    `known_ids` is the catalog key set. When supplied, every speculative
    fallback must exist there, so a stripped candidate can never resolve to an
    unrelated model. Suffix stripping is applied on `known_ids` alone otherwise.
    """
    raw = model_id.strip()
    candidates: list[str] = []
    if not raw:
        return candidates

    def _add(value: str, *, speculative: bool = False) -> None:
        value = value.strip()
        if not value or value in candidates:
            return
        if speculative and known_ids is not None and value not in known_ids:
            return
        candidates.append(value)

    # 1. Exact ID always wins: a catalog may price each region/variant apart.
    _add(raw)

    # 2. Peel metadata-only suffixes that are never part of model identity, in
    #    outer-to-inner order: `[1m]` annotation, then `@digest`/`@version`.
    base, _tokens = _split_context_annotation(raw)
    base, _digest = _split_digest(base)
    base = base.strip()
    if base != raw:
        _add(base, speculative=True)

    # 3. Optional known namespace prefix: `cn:model` -> `model`.
    namespace, remainder = _split_namespace(base)
    if namespace is not None:
        base = remainder.strip()
        _add(base, speculative=True)

    # 4. Trailing `:variant`. Catalog variants keep their identity (only the
    #    base is offered as a fallback); routing variants are lossless to drop
    #    because the docs state their metadata is the base model's.
    variant_base, variant, _is_catalog = _split_variant(base)
    if variant is not None:
        _add(variant_base, speculative=True)

    return candidates


def find_model_entry(model_id: str) -> dict[str, Any]:
    data = load_shared_catalog_data()
    models = data.get("models") or {}
    aliases = data.get("aliases") or {}

    for clean_id in candidate_model_ids(model_id, known_ids=set(models) | set(aliases)):
        entry = _lookup_catalog_entry(clean_id, models, aliases)
        if entry:
            return entry

    return {}


def _lookup_catalog_entry(
    clean_id: str,
    models: dict[str, Any],
    aliases: dict[str, Any],
) -> dict[str, Any]:
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


def is_placeholder_metadata(meta: ModelMetadata) -> bool:
    """Detect metadata that only carries fallback defaults.

    Entries created before catalog enrichment (or for unknown models) look like
    this. They must not shadow authoritative catalog data on re-sync.
    """
    return (
        int(meta.context_window or 0) in (0, DEFAULT_CONTEXT_WINDOW)
        and int(meta.max_output_tokens or 0) in (0, DEFAULT_MAX_OUTPUT_TOKENS)
        and not meta.supported_reasoning_levels
        and not meta.default_reasoning_level
        and list(meta.input_modalities or []) in ([], ["text"])
        and (not meta.display_name or meta.display_name == meta.id)
    )


def _model_id_qualifiers(model_id: str) -> list[str]:
    """Return the identity-bearing qualifiers of a model ID.

    Covers namespace prefixes (`cn:`), catalog variants and tags (`:free`,
    `:8b`), `@version` suffixes and `[1m]` annotations - everything that makes
    two otherwise-identical models distinguishable in a picker.
    """
    raw = model_id.strip()
    qualifiers: list[str] = []

    namespace, remainder = _split_namespace(raw)
    if namespace is not None:
        qualifiers.append(namespace)
        raw = remainder

    base, tokens = _split_context_annotation(raw)
    if tokens is not None:
        qualifiers.append(f"{tokens}ctx")
        raw = base

    base, digest = _split_digest(raw)
    if digest is not None:
        qualifiers.append(digest)
        raw = base

    base, variant, _is_catalog = _split_variant(raw)
    if variant is not None and variant.lower() in _KNOWN_VARIANT_TOKENS:
        qualifiers.append(variant)

    return qualifiers


def _qualify_display_name(model_id: str, base_name: str) -> str:
    """Keep namespace/variant/annotation qualifiers visible in display names.

    Without this, `cn:glm-5.3` and `global:glm-5.3` would both render as
    "GLM 5.3", and `deepseek-chat:free` would look identical to the paid tier.
    """
    if base_name == model_id or not base_name:
        return base_name

    qualifiers = _model_id_qualifiers(model_id)
    if not qualifiers:
        return base_name

    suffix = " ".join(f"[{q}]" for q in qualifiers)
    if base_name.endswith(suffix):
        return base_name
    return f"{base_name} {suffix}"


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
    context_win = int(entry.get("context_window") or DEFAULT_CONTEXT_WINDOW)
    max_tokens = int(entry.get("max_output_tokens") or DEFAULT_MAX_OUTPUT_TOKENS)

    # A `[1m]` / `[200k]` annotation is a context-window override: the client
    # advertises the larger window and strips the suffix before the request.
    _, annotated_tokens = _split_context_annotation(model_id)
    if annotated_tokens:
        context_win = max(context_win, annotated_tokens)

    display_name = str(entry.get("display_name") or model_id)
    modalities = list(entry.get("input_modalities") or ["text"])
    display_name = _qualify_display_name(model_id, display_name)

    if existing and not force_reset and not is_placeholder_metadata(existing):
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


def add_model_to_catalog(
    provider_name: str,
    model_id: str,
    *,
    display_name: str | None = None,
    context: int | None = None,
    max_output: int | None = None,
    effort: str | None = None,
    reasoning_levels: list[str] | None = None,
    modalities: list[str] | None = None,
    is_default: bool = False,
    overwrite: bool = False,
) -> tuple[ModelMetadata, bool]:
    """Add or update a model in a provider's catalog and optionally set as default.

    Returns:
        (metadata, is_created): Resulting metadata and whether it was newly added.
    """
    clean_id = model_id.strip()
    if not clean_id:
        raise SwitchError("model ID cannot be empty")

    prefix = f"{provider_name}/"
    if clean_id.startswith(prefix):
        clean_id = clean_id[len(prefix) :].strip()
    if not clean_id:
        raise SwitchError("model ID cannot be empty")

    pv_store = ProviderStore()
    pv = pv_store.require(provider_name)

    cat_store = CatalogStore()
    cat = cat_store.get(provider_name)
    if cat is None:
        cat = ProviderCatalog(provider=provider_name, updated_at="")

    is_created = clean_id not in cat.models
    existing = None if overwrite else cat.models.get(clean_id)

    meta = enrich_model_metadata(clean_id, existing=existing, force_reset=overwrite)

    if display_name is not None and display_name.strip():
        meta.display_name = display_name.strip()

    if context is not None:
        if context <= 0:
            raise SwitchError("context window must be a positive integer")
        meta.context_window = context

    if max_output is not None:
        if max_output <= 0:
            raise SwitchError("max output tokens must be a positive integer")
        meta.max_output_tokens = max_output

    if effort is not None:
        if isinstance(effort, str):
            clean_levels = [
                lvl.strip().lower() for lvl in effort.split(",") if lvl.strip()
            ]
        elif isinstance(effort, (list, tuple)):
            clean_levels = [
                str(lvl).strip().lower() for lvl in effort if str(lvl).strip()
            ]
        else:
            clean_levels = [str(effort).strip().lower()]

        meta.supported_reasoning_levels = clean_levels
        active_levels = [lvl for lvl in clean_levels if lvl not in ("none", "off", "0")]
        if active_levels:
            meta.default_reasoning_level = (
                "high" if "high" in active_levels else active_levels[0]
            )
        else:
            meta.default_reasoning_level = None
    elif reasoning_levels is not None:
        clean_levels = [lvl.strip().lower() for lvl in reasoning_levels if lvl.strip()]
        meta.supported_reasoning_levels = clean_levels
        active_levels = [lvl for lvl in clean_levels if lvl not in ("none", "off", "0")]
        if active_levels:
            meta.default_reasoning_level = (
                "high" if "high" in active_levels else active_levels[0]
            )
        else:
            meta.default_reasoning_level = None

    if modalities is not None:
        clean_modalities = [m.strip().lower() for m in modalities if m.strip()]
        if clean_modalities:
            meta.input_modalities = clean_modalities

    cat.models[clean_id] = meta
    cat_store.save(cat)

    if is_default:
        pv.default_model = clean_id
        pv_store.save(pv)

    # Refresh active target adapter catalogs if applicable
    refresh_active_adapters(provider_name)

    return meta, is_created


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
    meta, _ = add_model_to_catalog(
        provider_name,
        model_id,
        is_default=is_default,
        context=context,
        max_output=max_output,
        effort=effort,
        overwrite=False,
    )
    return meta
