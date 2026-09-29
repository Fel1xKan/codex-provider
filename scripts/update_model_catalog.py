#!/usr/bin/env python3
"""Automated weekly model catalog updater with rolling 6-month retention.

Fetches the latest models and parameters from OpenRouter models API and LiteLLM
database, infers reasoning capabilities and token limits, prunes models older
than 180 days (6 months), and writes the updated catalog to data/model-catalog.json.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = REPO_ROOT / "data" / "model-catalog.json"

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
LITELLM_CATALOG_URL = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"

VENDOR_PREFIX_MAP = {
    "openai": "openai",
    "anthropic": "anthropic",
    "google": "google",
    "deepseek": "deepseek",
    "qwen": "qwen",
    "x-ai": "xai",
    "z-ai": "zhipu",
    "moonshotai": "moonshot",
    "mistralai": "mistral",
}

VALID_EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")


def fetch_json(url: str, timeout: int = 15) -> Any:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "xpx-catalog-updater/1.0", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def normalize_clean_id(raw_id: str) -> str:
    clean = raw_id.strip()
    if "/" in clean:
        clean = clean.split("/", 1)[-1].strip()
    if clean.startswith("claude-"):
        clean = re.sub(r"(\d+)\.(\d+)", r"\1-\2", clean)
    return clean


def infer_vendor(raw_id: str, existing_vendor: str | None = None) -> str:
    if existing_vendor:
        return existing_vendor
    if "/" in raw_id:
        pfx = raw_id.split("/")[0].lower()
        if pfx in VENDOR_PREFIX_MAP:
            return VENDOR_PREFIX_MAP[pfx]
    lower = raw_id.lower()
    if any(k in lower for k in ("gpt-", "o1", "o3", "o4")):
        return "openai"
    if "claude" in lower:
        return "anthropic"
    if "gemini" in lower or "gemma" in lower:
        return "google"
    if "deepseek" in lower:
        return "deepseek"
    if "qwen" in lower or "qwq" in lower:
        return "qwen"
    if "grok" in lower:
        return "xai"
    if "glm" in lower:
        return "zhipu"
    if "kimi" in lower or "moonshot" in lower:
        return "moonshot"
    if "mistral" in lower or "codestral" in lower or "pixtral" in lower:
        return "mistral"
    return "other"


def infer_reasoning(
    clean_id: str,
    vendor: str,
    openrouter_reasoning: dict[str, Any] | None = None,
) -> tuple[list[Any], str]:
    """Derive reasoning_levels and reasoning_default ensuring test constraints."""
    lower = clean_id.lower()

    # 1. Check if OpenRouter provided explicit supported efforts
    if openrouter_reasoning and isinstance(openrouter_reasoning, dict):
        raw_efforts = openrouter_reasoning.get("supported_efforts") or []
        filtered_efforts = [eff for eff in raw_efforts if eff in VALID_EFFORTS]
        filtered_efforts = sorted(
            filtered_efforts, key=lambda x: VALID_EFFORTS.index(x)
        )
        default_eff = openrouter_reasoning.get("default_effort")
        if default_eff not in filtered_efforts and filtered_efforts:
            default_eff = filtered_efforts[0]

        cheaper = [eff for eff in filtered_efforts if eff not in ("max", "ultra")]
        if cheaper and (default_eff in ("max", "ultra") or not default_eff):
            if "medium" in cheaper:
                default_eff = "medium"
            elif "high" in cheaper:
                default_eff = "high"
            elif "low" in cheaper:
                default_eff = "low"
            else:
                default_eff = cheaper[-1]

        if filtered_efforts and default_eff:
            # Check if vendor uses toggle descriptions
            if (
                vendor in ("qwen", "moonshot")
                or "haiku" in lower
                or "sonnet-4-5" in lower
            ):
                ladder = [
                    {"effort": "none", "description": "Thinking disabled"},
                    {"effort": "high", "description": "Thinking enabled"},
                ]
                return ladder, "high"
            return filtered_efforts, default_eff

    # 2. Known vendor patterns
    is_reasoner = any(
        k in lower
        for k in (
            "reasoner",
            "reasoning",
            "thinking",
            "qwq",
            "o1",
            "o3",
            "o4",
            "prime",
            "flash-thinking",
        )
    )

    if vendor == "openai":
        if is_reasoner or lower.startswith("o"):
            return ["none", "low", "medium", "high", "xhigh"], "medium"
        if any(x in lower for x in ("gpt-5.6-sol", "gpt-6")):
            return ["none", "low", "medium", "high", "xhigh", "max", "ultra"], "medium"
        if "gpt-5.6-luna" in lower:
            return ["none", "low", "medium", "high", "xhigh", "max"], "medium"
        if "gpt-5.4" in lower:
            return ["none", "low", "medium", "high", "xhigh"], "medium"
        if "gpt-5" in lower:
            return ["minimal", "low", "medium", "high"], "medium"
        return ["none"], "none"

    if vendor == "anthropic":
        if (
            "fable" in lower
            or "opus-5" in lower
            or "opus-4-7" in lower
            or "opus-4-8" in lower
        ):
            return ["low", "medium", "high", "xhigh", "max"], "high"
        if "sonnet-5" in lower or "sonnet-4-6" in lower:
            return ["low", "medium", "high", "max"], "high"
        if "opus-4-5" in lower:
            return ["low", "medium", "high"], "high"
        if any(x in lower for x in ("sonnet-4-5", "haiku-4-5", "3-7-sonnet")):
            return [
                {"effort": "none", "description": "Thinking disabled"},
                {"effort": "high", "description": "Thinking enabled"},
            ], "high"
        return ["none"], "none"

    if vendor == "deepseek":
        if is_reasoner or "v4" in lower:
            return ["none", "low", "high", "max"], "high"
        return ["none"], "none"

    if vendor == "google":
        if "gemini-3.8" in lower:
            return ["low", "medium", "high"], "medium"
        if "gemini-3.6" in lower:
            return ["minimal", "low", "medium", "high"], "medium"
        if "gemini-3.5" in lower:
            return ["high", "medium", "low", "minimal"], "minimal"
        if "3.1-pro" in lower:
            return ["low", "medium", "high"], "high"
        if "3.1-flash-lite-image" in lower:
            return ["minimal", "high"], "high"
        if is_reasoner:
            return ["low", "medium", "high"], "medium"
        return ["none"], "none"

    if vendor == "qwen":
        if (
            is_reasoner
            or "max" in lower
            or "qwq" in lower
            or "3.8" in lower
            or "3.7" in lower
        ):
            if "qwq-plus" in lower:
                return ["high"], "high"
            return [
                {"effort": "none", "description": "Thinking disabled"},
                {"effort": "high", "description": "Thinking enabled"},
            ], "high"
        return ["none"], "none"

    if vendor == "xai":
        if "grok-4.6" in lower or "grok-4.7" in lower:
            return ["low", "medium", "high", "xhigh"], "high"
        if "grok-4.5" in lower:
            return ["low", "medium", "high"], "high"
        if "grok-4.3" in lower:
            return ["high"], "high"
        if is_reasoner:
            return ["low", "medium", "high"], "high"
        return ["none"], "none"

    if vendor == "zhipu":
        if "glm-5.3" in lower:
            return ["low", "high", "max"], "high"
        if "glm-5.2" in lower:
            return ["none", "high", "max"], "high"
        if "glm-4.7" in lower:
            return ["high"], "high"
        return ["none"], "none"

    if vendor == "moonshot":
        if "k3" in lower:
            return ["low", "high", "max"], "high"
        if "k2.7" in lower:
            return ["high"], "high"
        if "k2.6" in lower:
            return [
                {"effort": "none", "description": "Thinking disabled"},
                {"effort": "high", "description": "Thinking enabled"},
            ], "high"
        return ["none"], "none"

    if vendor == "mistral":
        if "small-2603" in lower:
            return [
                {"effort": "none", "description": "Thinking disabled"},
                {"effort": "high", "description": "Thinking enabled"},
            ], "high"
        if "magistral" in lower:
            return ["high"], "high"
        return ["none"], "none"

    if is_reasoner:
        return ["low", "medium", "high"], "high"
    return ["none"], "none"


KNOWN_HISTORICAL_DATES = {
    "deepseek-reasoner": "2025-01-20",
    "deepseek-chat": "2024-12-26",
    "claude-3-7-sonnet-latest": "2025-02-19",
    "claude-3-5-sonnet-latest": "2024-10-22",
    "claude-3-5-haiku-latest": "2024-10-22",
    "gpt-4o": "2024-05-13",
    "gpt-4o-mini": "2024-07-18",
    "gpt-4.1": "2025-04-15",
    "gpt-4.1-mini": "2025-04-15",
    "gpt-4.1-nano": "2025-04-15",
    "gpt-5": "2025-08-07",
    "gpt-5-mini": "2025-08-07",
    "gpt-5-nano": "2025-08-07",
    "gpt-5.1": "2025-11-19",
    "gpt-5.2": "2025-12-16",
    "gpt-5.3-codex": "2026-02-28",
    "gpt-5.4": "2026-03-09",
    "gemini-2.5-pro": "2025-06-17",
    "gemini-2.5-flash": "2025-06-17",
    "gemini-2.5-flash-lite": "2025-07-22",
    "qwen3-coder-plus": "2025-09-01",
    "qwen-max": "2024-01-01",
    "qwen-plus": "2024-01-01",
    "qwen-turbo": "2024-01-01",
    "qwen-flash": "2024-01-01",
    "qwen-long": "2024-01-01",
    "glm-4.5": "2025-06-01",
    "glm-4.6": "2025-08-01",
    "glm-4.7": "2025-12-01",
    "kimi-k2.6": "2025-11-01",
    "kimi-k2.7-code": "2026-03-01",
    "mistral-large-latest": "2024-11-01",
}


def infer_date_from_name(model_id: str) -> str | None:
    m = re.search(r"202[4-6][-_]?[0-1][0-9][-_]?[0-3][0-9]", model_id)
    if m:
        val = m.group(0).replace("_", "-")
        if len(val) == 8:  # 20260902
            return f"{val[:4]}-{val[4:6]}-{val[6:]}"
        return val
    m_short = re.search(r"2[5-6][0-1][0-9]", model_id)
    if m_short:
        val = m_short.group(0)
        return f"20{val[:2]}-{val[2:]}-01"
    return None


def resolve_model_release_date(
    mid: str,
    openrouter_dates: dict[str, str],
) -> str | None:
    if mid in openrouter_dates:
        return openrouter_dates[mid]
    cid = normalize_clean_id(mid)
    if cid in openrouter_dates:
        return openrouter_dates[cid]
    if cid in KNOWN_HISTORICAL_DATES:
        return KNOWN_HISTORICAL_DATES[cid]
    if mid in KNOWN_HISTORICAL_DATES:
        return KNOWN_HISTORICAL_DATES[mid]
    return infer_date_from_name(mid)


def update_catalog(
    cutoff_days: int = 180,
    dry_run: bool = False,
    catalog_path: Path = CATALOG_PATH,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    today_str = now.strftime("%Y-%m-%d")
    cutoff_date = (now - timedelta(days=cutoff_days)).strftime("%Y-%m-%d")
    cutoff_ts = int((now - timedelta(days=cutoff_days)).timestamp())

    print(
        f"Running catalog update: today={today_str}, "
        f"cutoff={cutoff_date} ({cutoff_days} days)"
    )

    # 1. Load existing catalog
    if catalog_path.is_file():
        catalog_data = json.loads(catalog_path.read_text(encoding="utf-8"))
    else:
        catalog_data = {
            "schema_version": 1,
            "catalog_version": today_str,
            "models": {},
            "aliases": {},
            "sources": {},
        }

    existing_models = catalog_data.get("models", {})
    existing_aliases = catalog_data.get("aliases", {})
    sources = catalog_data.get("sources", {})

    # Deduplicate existing models by canonical ID
    deduped_existing: dict[str, Any] = {}
    for mid, mdata in existing_models.items():
        cid = normalize_clean_id(mid)
        if cid != mid:
            existing_aliases[mid] = cid
            if cid in deduped_existing:
                continue
        deduped_existing[cid] = mdata
    existing_models = deduped_existing

    # 2. Fetch OpenRouter models
    openrouter_models: list[dict[str, Any]] = []
    try:
        print("Fetching latest models from OpenRouter...")
        res = fetch_json(OPENROUTER_MODELS_URL)
        openrouter_models = res.get("data", [])
        print(f"Fetched {len(openrouter_models)} models from OpenRouter.")
    except Exception as exc:
        print(f"Warning: Failed to fetch OpenRouter models: {exc}", file=sys.stderr)

    # Build date lookup table for ALL OpenRouter models
    openrouter_dates: dict[str, str] = {}
    for m in openrouter_models:
        rid = m.get("id", "")
        if ":" in rid or rid.startswith("~"):
            continue
        ts = m.get("created")
        if not ts:
            continue
        d_str = datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d")
        rclean = rid.split("/")[-1].strip()
        cclean = normalize_clean_id(rclean)
        openrouter_dates[rclean] = d_str
        openrouter_dates[cclean] = d_str
        if "/" in rid:
            openrouter_dates[rid] = d_str

    # 3. Ensure existing models have accurate release_date and valid reasoning defaults
    for mid in list(existing_models.keys()):
        mdata = existing_models[mid]
        rel_date = resolve_model_release_date(mid, openrouter_dates)
        if not rel_date:
            del existing_models[mid]
            continue
        mdata["release_date"] = rel_date
        levels = mdata.get("reasoning_levels")
        r_def = mdata.get("reasoning_default")
        if levels and r_def:
            names = [x if isinstance(x, str) else x.get("effort") for x in levels]
            cheaper = [x for x in names if x not in ("max", "ultra")]
            if cheaper and r_def in ("max", "ultra"):
                if "medium" in cheaper:
                    mdata["reasoning_default"] = "medium"
                elif "high" in cheaper:
                    mdata["reasoning_default"] = "high"
                elif "low" in cheaper:
                    mdata["reasoning_default"] = "low"
                else:
                    mdata["reasoning_default"] = cheaper[-1]
            if all(isinstance(x, str) for x in levels):
                mdata["reasoning_levels"] = sorted(
                    [x for x in levels if x in VALID_EFFORTS],
                    key=lambda x: VALID_EFFORTS.index(x),
                )

    # 4. Fetch LiteLLM model database
    litellm_data: dict[str, Any] = {}
    try:
        print("Fetching LiteLLM model database...")
        litellm_data = fetch_json(LITELLM_CATALOG_URL)
        print(f"Fetched {len(litellm_data)} models from LiteLLM.")
    except Exception as exc:
        print(f"Warning: Failed to fetch LiteLLM models: {exc}", file=sys.stderr)

    # 5. Ingest and merge OpenRouter models
    new_count = 0
    updated_count = 0

    for m in openrouter_models:
        created_ts = m.get("created")
        if not created_ts or created_ts < cutoff_ts:
            continue

        raw_id = m.get("id", "")
        if ":" in raw_id or raw_id.startswith("~"):
            # skip variants like :free, :batch
            continue

        clean_id = normalize_clean_id(raw_id)
        raw_clean = raw_id.split("/")[-1].strip()
        rel_date = datetime.fromtimestamp(created_ts, UTC).strftime("%Y-%m-%d")

        vendor = infer_vendor(raw_id, existing_models.get(clean_id, {}).get("vendor"))
        if vendor == "other":
            continue

        ctx = int(
            m.get("context_length")
            or m.get("top_provider", {}).get("context_length")
            or 128000
        )
        max_out = int(m.get("top_provider", {}).get("max_completion_tokens") or 8192)

        # LiteLLM enrichment if available
        if raw_id in litellm_data:
            lt = litellm_data[raw_id]
            if lt.get("max_input_tokens"):
                ctx = max(ctx, int(lt["max_input_tokens"]))
            if lt.get("max_output_tokens"):
                max_out = max(max_out, int(lt["max_output_tokens"]))

        input_mods = list(m.get("architecture", {}).get("input_modalities") or ["text"])
        if "file" in input_mods:
            input_mods.remove("file")
        if not input_mods:
            input_mods = ["text"]

        ladder, def_eff = infer_reasoning(clean_id, vendor, m.get("reasoning"))

        entry: dict[str, Any] = {
            "display_name": m.get("name") or clean_id,
            "context_window": ctx,
            "max_output_tokens": max_out,
            "input_modalities": input_mods,
            "vendor": vendor,
            "source": f"https://openrouter.ai/models/{raw_id}",
            "reasoning_levels": ladder,
            "reasoning_default": def_eff,
            "release_date": rel_date,
        }

        if clean_id not in existing_models:
            existing_models[clean_id] = entry
            new_count += 1
        else:
            curr = existing_models[clean_id]
            curr["context_window"] = max(curr.get("context_window", 0), ctx)
            curr["max_output_tokens"] = max(curr.get("max_output_tokens", 0), max_out)
            curr["release_date"] = rel_date
            updated_count += 1

        # Register aliases
        if "/" in raw_id:
            existing_aliases[raw_id] = clean_id
        if raw_clean != clean_id:
            existing_aliases[raw_clean] = clean_id

    # 5. Prune models older than cutoff_date (Strict 6-month retention, no whitelist)
    pruned_models = []
    final_models: dict[str, Any] = {}

    for mid, mdata in existing_models.items():
        m_date = mdata.get("release_date")
        if not m_date or m_date < cutoff_date:
            pruned_models.append(mid)
        else:
            final_models[mid] = mdata

    # Clean orphaned aliases
    final_aliases: dict[str, str] = {}
    for alias, target in existing_aliases.items():
        if target in final_models:
            final_aliases[alias] = target

    print(
        f"Catalog stats: {len(final_models)} retained, {new_count} new, "
        f"{updated_count} updated, {len(pruned_models)} pruned."
    )

    # 6. Sort and assemble final data
    sorted_models = {k: final_models[k] for k in sorted(final_models.keys())}
    sorted_aliases = {k: final_aliases[k] for k in sorted(final_aliases.keys())}

    output_data = {
        "schema_version": catalog_data.get("schema_version", 1),
        "catalog_version": today_str,
        "models": sorted_models,
        "aliases": sorted_aliases,
        "updated_at": today_str,
        "sources": sources,
    }

    if not dry_run:
        payload = json.dumps(output_data, indent=2, ensure_ascii=False) + "\n"
        catalog_path.write_text(payload, encoding="utf-8")
        print(f"Successfully saved updated catalog to {catalog_path}")

    return output_data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cutoff-days",
        type=int,
        default=180,
        help="Retention window in days (default: 180 for 6 months)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing to file",
    )
    parser.add_argument(
        "--catalog-file",
        type=Path,
        default=CATALOG_PATH,
        help="Path to model catalog json file",
    )
    args = parser.parse_args()

    update_catalog(
        cutoff_days=args.cutoff_days,
        dry_run=args.dry_run,
        catalog_path=args.catalog_file,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
