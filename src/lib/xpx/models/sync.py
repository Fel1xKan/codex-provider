from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from lib.common.constants import MAX_HTTP_BODY_BYTES, VERSION
from lib.common.errors import SwitchError
from lib.xpx.models.catalog import enrich_model_metadata
from lib.xpx.store.catalog_store import CatalogStore, ProviderCatalog
from lib.xpx.store.provider_store import ProviderStore


def build_models_request(
    base_url: str,
    api_key: str,
    protocol: str = "openai",
) -> urllib.request.Request:
    clean_base = base_url.rstrip("/")
    url = f"{clean_base}/models"

    headers: dict[str, str] = {
        "Accept": "application/json",
        "User-Agent": f"xpx/{VERSION}",
    }

    if protocol == "anthropic":
        if api_key:
            headers["x-api-key"] = api_key
        headers["anthropic-version"] = "2023-06-01"
    else:
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

    return urllib.request.Request(url, headers=headers, method="GET")


def fetch_remote_models(
    base_url: str,
    api_key: str,
    protocol: str = "openai",
    timeout: int = 15,
) -> list[str]:
    """Fetch model IDs from a provider's /models endpoint."""
    request = build_models_request(base_url, api_key, protocol)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read(MAX_HTTP_BODY_BYTES + 1)
            if len(payload) > MAX_HTTP_BODY_BYTES:
                raise SwitchError("models endpoint response exceeded size limit")
            data = json.loads(payload.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise SwitchError(
            f"models sync failed (HTTP {exc.code}): {exc.reason}"
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SwitchError(f"models sync network error: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SwitchError(f"models sync failed to parse JSON response: {exc}") from exc

    raw_list: list[Any] = []
    if isinstance(data, list):
        raw_list = data
    elif isinstance(data, dict):
        if "data" in data and isinstance(data["data"], list):
            raw_list = data["data"]
        elif "models" in data and isinstance(data["models"], list):
            raw_list = data["models"]

    model_ids: list[str] = []
    for item in raw_list:
        if isinstance(item, str) and item.strip():
            model_ids.append(item.strip())
        elif isinstance(item, dict):
            model_id = item.get("id") or item.get("name")
            if isinstance(model_id, str) and model_id.strip():
                model_ids.append(model_id.strip())

    return sorted(set(model_ids))


def sync_provider_models(
    provider_name: str,
    force: bool = False,
    timeout: int = 15,
) -> ProviderCatalog:
    """Synchronize remote models for a provider with the local catalog."""
    pv_store = ProviderStore()
    pv = pv_store.require(provider_name)

    model_ids = fetch_remote_models(
        pv.base_url,
        pv.api_key,
        protocol=pv.protocol,
        timeout=timeout,
    )

    cat_store = CatalogStore()
    cat = cat_store.get(provider_name)
    if cat is None:
        cat = ProviderCatalog(provider=provider_name, updated_at="")

    for mid in model_ids:
        existing = cat.models.get(mid)
        enriched = enrich_model_metadata(mid, existing=existing, force_reset=force)
        cat.models[mid] = enriched

    cat_store.save(cat)

    # If no default model set and we discovered models, default to first or matching
    if not pv.default_model and model_ids:
        pv.default_model = model_ids[0]
        pv_store.save(pv)

    return cat
